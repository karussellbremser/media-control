import csv, requests, gzip, shutil, os, sqlite3, tempfile
from media import Media
from scrapeimdbonline import ScrapeIMDbOnline
from exceptions import OfflineDatasetError

class ScrapeIMDbOffline:

    # class for looking up IMDb's offline dataset data (see https://www.imdb.com/interfaces/ and
    # https://datasets.imdbws.com/), backed by a small, indexed SQLite helper DB (see
    # updateIMDbOfflineDB) instead of scanning IMDb's raw, multi-gigabyte dataset files directly --
    # those files are only ever downloaded and read during the (infrequent) update itself, into a
    # temporary directory that's gone again by the time this class's other methods are ever used.

    title_basics_filename = "title.basics.tsv"
    title_ratings_filename = "title.ratings.tsv"
    title_episode_filename = "title.episode.tsv"
    name_basics_filename = "name.basics.tsv"

    # how many placeholders to put in one "WHERE imdb_id IN (...)" query at a time -- keeps a
    # refresh over a large library (thousands of ids) well clear of SQLite's bound-parameter limit
    BATCH_SIZE = 500

    def __init__(self, scrapeimdbonline, helper_db_path):
        self.scrapeimdbonline = scrapeimdbonline
        self.helper_db_path = helper_db_path
        self.__conn = None # lazily opened on first actual lookup -- see __getCursor; this also
                            # means constructing this class never fails just because the helper DB
                            # doesn't exist yet (e.g. before the first-ever --update)

    def __getCursor(self):
        if self.__conn is None:
            self.__conn = sqlite3.connect(self.helper_db_path)
        return self.__conn.cursor()

    def __chunks(self, items):
        items = list(items)
        for i in range(0, len(items), self.BATCH_SIZE):
            yield items[i:i + self.BATCH_SIZE]

    # ------------------------------------------------------------------
    # updating the helper DB
    # ------------------------------------------------------------------

    def __downloadAndDecompress(self, out_path, url):
        with requests.get(url, stream=True) as r:
            r.raise_for_status()
            with gzip.GzipFile(fileobj=r.raw) as gz:
                with open(out_path, "wb") as f_out:
                    shutil.copyfileobj(gz, f_out)

    def updateIMDbOfflineDB(self):
        """Rebuilds the offline dataset helper DB from scratch: downloads and decompresses IMDb's
        four dataset files into a temporary directory (auto-cleaned, even on failure, since nothing
        else ever shares it), builds a fresh indexed SQLite DB from them, then atomically swaps it
        in for the previous one. Always a full rebuild -- IMDb ships full snapshots, not deltas, so
        there's no meaningful "diff" to apply. Any currently-open lookup connection is closed and
        reopened against the new file afterward."""
        print("Updating IMDb offline dataset DB...")

        with tempfile.TemporaryDirectory() as temp_dir:
            self.__downloadAndDecompress(os.path.join(temp_dir, self.title_basics_filename), "https://datasets.imdbws.com/title.basics.tsv.gz")
            self.__downloadAndDecompress(os.path.join(temp_dir, self.title_ratings_filename), "https://datasets.imdbws.com/title.ratings.tsv.gz")
            self.__downloadAndDecompress(os.path.join(temp_dir, self.title_episode_filename), "https://datasets.imdbws.com/title.episode.tsv.gz")
            self.__downloadAndDecompress(os.path.join(temp_dir, self.name_basics_filename), "https://datasets.imdbws.com/name.basics.tsv.gz")

            new_db_path = self.helper_db_path + ".new"
            if os.path.exists(new_db_path):
                os.remove(new_db_path)
            build_conn = sqlite3.connect(new_db_path)
            try:
                self.__buildHelperDB(build_conn, temp_dir)
            except:
                build_conn.close()
                os.remove(new_db_path)
                raise
            build_conn.close()

        # swap the freshly-built DB in for the previous one, closing/reopening our own lookup
        # connection so it never keeps a stale file handle open across the swap
        if self.__conn is not None:
            self.__conn.close()
            self.__conn = None
        if os.path.exists(self.helper_db_path):
            os.remove(self.helper_db_path)
        os.rename(new_db_path, self.helper_db_path)

    def __buildHelperDB(self, conn, source_dir):
        c = conn.cursor()
        c.execute("""CREATE TABLE people (
            imdb_id integer NOT NULL,
            name text NOT NULL,
            birth_year integer,
            death_year integer,
            PRIMARY KEY (imdb_id)
        )""")
        c.execute("""CREATE TABLE titles (
            imdb_id integer NOT NULL,
            title_type_name text NOT NULL,
            primary_title text NOT NULL,
            original_title text NOT NULL,
            start_year integer NOT NULL,
            end_year integer,
            rating_mul10 integer,
            num_votes integer,
            PRIMARY KEY (imdb_id)
        )""")
        c.execute("""CREATE TABLE episodes (
            imdb_id integer NOT NULL,
            parent_id integer NOT NULL,
            season_number integer,
            episode_number integer,
            PRIMARY KEY (imdb_id)
        )""")
        # deliberately no foreign keys on episodes.parent_id or against titles/people at all --
        # IMDb's own files can and do disagree with each other (see e.g. the "found in
        # title.episode.tsv but missing from title.basics.tsv" case __applyTitles still checks for
        # at lookup time), and this DB is a disposable, rebuilt-from-scratch cache, not a place to
        # enforce integrity between two independently-sourced files
        c.execute("CREATE INDEX idx_episodes_parent ON episodes (parent_id, season_number, episode_number)")

        self.__buildPeopleTable(c, source_dir)
        self.__buildTitlesTable(c, source_dir)
        self.__buildEpisodesTable(c, source_dir)

        conn.commit()

    def __buildPeopleTable(self, c, source_dir):
        batch = []
        with open(os.path.join(source_dir, self.name_basics_filename), "r", encoding="utf8") as f:
            r = csv.reader(f, delimiter="\t")
            next(r, None) # header
            for row in r: # row: nconst || primaryName || birthYear || deathYear || primaryProfession || knownForTitles
                batch.append((
                    int(row[0][2:]),
                    row[1],
                    int(row[2]) if row[2] != "\\N" else None,
                    int(row[3]) if row[3] != "\\N" else None,
                ))
                if len(batch) >= 50000:
                    c.executemany("INSERT INTO people VALUES (?, ?, ?, ?)", batch)
                    batch = []
            if batch:
                c.executemany("INSERT INTO people VALUES (?, ?, ?, ?)", batch)

    def __buildTitlesTable(self, c, source_dir):
        # a row missing any of titleType/primaryTitle/originalTitle/startYear ("\N") is skipped
        # entirely -- it was never usable (see __applyTitles's "illegal" handling below, which
        # previously treated this the same as a row not being found at all); this collapses what
        # used to be two separate "not found" cases into one, simplifying every caller
        batch = []
        with open(os.path.join(source_dir, self.title_basics_filename), "r", encoding="utf8") as f:
            r = csv.reader(f, delimiter="\t")
            next(r, None) # header
            for row in r: # row: tconst || titleType || primaryTitle || originalTitle || isAdult || startYear || endYear || runtimeMinutes || genres
                if row[1] == "\\N" or row[2] == "\\N" or row[3] == "\\N" or row[5] == "\\N":
                    continue
                batch.append((
                    int(row[0][2:]),
                    row[1],
                    row[2],
                    row[3],
                    int(row[5]),
                    int(row[6]) if row[6] != "\\N" else None,
                    None, # rating_mul10, filled in below from title.ratings.tsv
                    None, # num_votes
                ))
                if len(batch) >= 50000:
                    c.executemany("INSERT INTO titles VALUES (?, ?, ?, ?, ?, ?, ?, ?)", batch)
                    batch = []
            if batch:
                c.executemany("INSERT INTO titles VALUES (?, ?, ?, ?, ?, ?, ?, ?)", batch)

        # enrich with ratings -- title.ratings.tsv only covers a subset of titles.basics' ids
        # (only ever-rated titles), so this is an UPDATE against whatever's already there; an id
        # present in title.ratings.tsv but absent from titles (excluded above, or never in
        # title.basics.tsv at all) simply has no row to update, a silent no-op
        batch = []
        with open(os.path.join(source_dir, self.title_ratings_filename), "r", encoding="utf8") as f:
            r = csv.reader(f, delimiter="\t")
            next(r, None) # header
            for row in r: # row: tconst || averageRating || numVotes
                if row[1] == "\\N":
                    rating_mul10 = None
                else:
                    rating_mul10 = int(row[1].replace(".", ""))
                    if rating_mul10 < 10 or rating_mul10 > 100:
                        raise OfflineDatasetError("rating conversion problem for title " + row[0])
                batch.append((
                    rating_mul10,
                    int(row[2]) if row[2] != "\\N" else None,
                    int(row[0][2:]),
                ))
                if len(batch) >= 50000:
                    c.executemany("UPDATE titles SET rating_mul10=?, num_votes=? WHERE imdb_id=?", batch)
                    batch = []
            if batch:
                c.executemany("UPDATE titles SET rating_mul10=?, num_votes=? WHERE imdb_id=?", batch)

    def __buildEpisodesTable(self, c, source_dir):
        batch = []
        with open(os.path.join(source_dir, self.title_episode_filename), "r", encoding="utf8") as f:
            r = csv.reader(f, delimiter="\t")
            next(r, None) # header
            for row in r: # row: tconst || parentTconst || seasonNumber || episodeNumber
                seasonRaw, episodeRaw = row[2], row[3]
                if (seasonRaw == "\\N") != (episodeRaw == "\\N"):
                    raise OfflineDatasetError("episode " + row[0] + " has a season/episode number mismatch (one is unknown, the other isn't): " + seasonRaw + "/" + episodeRaw)
                batch.append((
                    int(row[0][2:]),
                    int(row[1][2:]),
                    int(seasonRaw) if seasonRaw != "\\N" else None,
                    int(episodeRaw) if episodeRaw != "\\N" else None,
                ))
                if len(batch) >= 50000:
                    c.executemany("INSERT INTO episodes VALUES (?, ?, ?, ?)", batch)
                    batch = []
            if batch:
                c.executemany("INSERT INTO episodes VALUES (?, ?, ?, ?)", batch)

        # duplicate real (season, episode) pairs for the same series are checked once here,
        # comprehensively, across the whole dataset -- rather than only if/when a --sync or
        # --refresh happens to touch the affected series (as getEpisodesForSeries used to check it,
        # per-call, at lookup time). Flagged, not raised: this turned out to be a real, if rare,
        # data quirk in IMDb's own dataset (confirmed against a live build -- e.g. tt0103396, a
        # long-running daily/weekly show, genuinely has two episode ids both claiming season 29
        # episode 49), and this now covers IMDb's *entire* episode catalogue, not just series
        # someone owns -- a single such quirk anywhere shouldn't block --update for everyone. Both
        # rows are kept in the table either way (no FK/uniqueness enforced here at all -- see the
        # table comment above); a caller keying by (season, episode) just has one of them silently
        # win, same tolerance already applied to multiple unnumbered episodes of one series.
        c.execute("""SELECT parent_id, season_number, episode_number, GROUP_CONCAT(imdb_id)
            FROM episodes WHERE season_number IS NOT NULL
            GROUP BY parent_id, season_number, episode_number HAVING COUNT(*) > 1""")
        for parent_id, season, episode, ids in c.fetchall():
            print("WARNING: duplicate season/episode (" + str(season) + ", " + str(episode) + ") for series tt" +
                  str(parent_id).zfill(7) + ": " + ids)

    # ------------------------------------------------------------------
    # looking things up in the helper DB
    # ------------------------------------------------------------------

    def parseTitleRatings(self, content_dict):
        return self.__applyTitles(content_dict, mode="ratings", remove_illegal=True)

    def refreshTitleRatings(self, content_dict):
        return self.__applyTitles(content_dict, mode="ratings", remove_illegal=False)

    def parseTitleBasics(self, content_dict):
        return self.__applyTitles(content_dict, mode="basics", remove_illegal=True)

    def refreshTitleBasics(self, content_dict):
        """Like refreshTitleRatings, but for title basics: primaryTitle/originalTitle/endYear are
        silently updated to whatever the dataset currently says (titles get corrected, an airing
        series' endYear becomes known once it concludes). titleType and startYear are treated as
        near-immutable instead -- see __insertTitleBasicsRefresh for exactly what's allowed to
        change and what raises OfflineDatasetError."""
        return self.__applyTitles(content_dict, mode="basics_refresh", remove_illegal=False)

    def parsePeople(self, content_dict):
        """Resolves name/birth_year/death_year for every newly-discovered person in content_dict
        (a {imdb_id: Person} dict) from the helper DB's people table. Unlike parseTitleBasics/
        parseTitleRatings, a person missing from the dataset (e.g. added to IMDb more recently than
        the dataset snapshot) is tolerated rather than treated as an error or discarded -- a person
        record is supplementary to a credit, not structural the way a title's own basics are, so
        this just leaves the person's name as whatever was scraped from the credits page (see
        Person), with birth_year/death_year staying None."""
        return self.__applyPeople(content_dict)

    def refreshPeople(self, content_dict):
        """Like refreshTitleBasics, but for people: name/birth_year/death_year are silently updated
        to whatever the dataset currently says (a living person's death_year becomes known, names
        get corrected). A person missing from the dataset keeps their current DB values unchanged,
        same tolerance as parsePeople."""
        return self.__applyPeople(content_dict)

    def __applyPeople(self, content_dict):
        if len(content_dict) == 0:
            return content_dict

        c = self.__getCursor()
        foundIDs = set()
        for batch in self.__chunks(content_dict.keys()):
            placeholders = ",".join("?" for _ in batch)
            c.execute("SELECT imdb_id, name, birth_year, death_year FROM people WHERE imdb_id IN (" + placeholders + ")", batch)
            for imdb_id, name, birth_year, death_year in c.fetchall():
                person = content_dict[imdb_id]
                person.name = name
                person.birth_year = birth_year
                person.death_year = death_year
                foundIDs.add(imdb_id)

        # flagged, not raised (see parsePeople/refreshPeople's docstrings) -- but still worth
        # surfacing, since it's the one case where a person's dataset data was actually expected
        # and didn't show up
        for missing_id in content_dict.keys() - foundIDs:
            print("WARNING: person " + content_dict[missing_id].getIDString() + " (" + str(content_dict[missing_id].name) +
                  ") not found in the offline dataset -- keeping existing data unchanged")

        return content_dict

    def parseTitleEpisode(self, content_dict):
        """Resolves season_number/episode_number/series_imdb_id for every id in content_dict that
        turns out to be an episode, via one batched lookup against the helper DB's episodes table.
        An id with no matching row simply isn't an episode -- unlike parseTitleBasics/
        parseTitleRatings, membership in this table is what DEFINES an id as an episode here, not
        something checked against an already-known type. A season/episode value of None means
        IMDb itself has no number for it (e.g. an uncategorized episode), never 0 -- 0 is a
        legitimate real episode number, and real season numbers are always >= 1, so None stays
        unambiguous regardless of what season/episode number IMDb might use in the future.

        Must run before parseTitleBasics: __insertTitleBasics's fail-loud type-consistency check
        relies on series_imdb_id already being set to know an id is expected to be an episode."""

        if len(content_dict) == 0:
            return content_dict

        c = self.__getCursor()
        for batch in self.__chunks(content_dict.keys()):
            placeholders = ",".join("?" for _ in batch)
            c.execute("SELECT imdb_id, parent_id, season_number, episode_number FROM episodes WHERE imdb_id IN (" + placeholders + ")", batch)
            for imdb_id, parent_id, season_number, episode_number in c.fetchall():
                media_obj = content_dict[imdb_id]
                media_obj.series_imdb_id = parent_id
                media_obj.season_number = season_number
                media_obj.episode_number = episode_number

        return content_dict

    def getEpisodesForSeries(self, series_imdb_ids):
        """Returns {series_imdb_id: {(season_number, episode_number): episode_imdb_id}} for every
        series in series_imdb_ids. The reverse direction of parseTitleEpisode -- resolves a known
        (series, season, episode) to an episode id, rather than a known episode id to its
        season/episode/series.

        Only useful for looking up a real, numbered (season, episode) pair -- an unnumbered episode
        maps to the (None, None) key like everywhere else, but since a series can legitimately have
        more than one unnumbered episode, only the last one encountered survives under that key
        (order is whatever SQLite returns, unspecified but consistent within one call). The same
        last-one-wins tolerance also covers the rare case of two different episodes genuinely
        claiming the same real (season, episode) for one series -- a live IMDb data quirk, not just
        a hypothetical (see updateIMDbOfflineDB, which warns about every such case once when the
        helper DB is built, rather than raising here per-call). That's fine for resolving
        locally-found episode files (a local filename always carries a real season/episode number,
        so (None, None) is never looked up here), but this method isn't meant for enumerating a
        series' full episode list including every unnumbered (or duplicate-numbered) one.

        Still raises OfflineDatasetError if any given series has zero episodes at all -- a series
        with nothing there isn't a "just hasn't been catalogued yet" situation worth quietly
        returning an empty result for, since every caller only ever asks about a series it already
        has a concrete reason to expect episodes for."""

        if len(series_imdb_ids) == 0:
            return {}

        result = {series_imdb_id: {} for series_imdb_id in series_imdb_ids}

        c = self.__getCursor()
        for batch in self.__chunks(series_imdb_ids):
            placeholders = ",".join("?" for _ in batch)
            c.execute("SELECT parent_id, season_number, episode_number, imdb_id FROM episodes WHERE parent_id IN (" + placeholders + ")", batch)
            for parent_id, season_number, episode_number, episode_imdb_id in c.fetchall():
                key = (season_number, episode_number) if season_number is not None else (None, None)
                result[parent_id][key] = episode_imdb_id

        for series_imdb_id, episodes in result.items():
            if len(episodes) == 0:
                raise OfflineDatasetError("series tt" + str(series_imdb_id).zfill(7) + " has zero episodes in the offline dataset")

        return result

    def getFullEpisodeListForSeries(self, series_imdb_ids):
        """Returns {series_imdb_id: [(season_number, episode_number, episode_imdb_id), ...]} -- the
        FULL episode list for each series in series_imdb_ids, including every unnumbered episode
        individually (unlike getEpisodesForSeries, which collapses those under one (None, None)
        dict key). Used where completeness matters more than convenient keyed lookup, e.g.
        discovering new episodes or detecting vanished ones for an owned series during a refresh."""

        if len(series_imdb_ids) == 0:
            return {}

        result = {series_imdb_id: [] for series_imdb_id in series_imdb_ids}

        c = self.__getCursor()
        for batch in self.__chunks(series_imdb_ids):
            placeholders = ",".join("?" for _ in batch)
            c.execute("SELECT parent_id, season_number, episode_number, imdb_id FROM episodes WHERE parent_id IN (" + placeholders + ")", batch)
            for parent_id, season_number, episode_number, episode_imdb_id in c.fetchall():
                result[parent_id].append((season_number, episode_number, episode_imdb_id))

        return result

    def __fetchTitles(self, ids):
        """Returns {imdb_id: (title_type_name, primary_title, original_title, start_year, end_year,
        rating_mul10, num_votes)} for every id in ids found in the titles table. An id with no
        matching row simply wasn't usable in title.basics.tsv (missing entirely, or missing
        titleType/primaryTitle/originalTitle/startYear -- see __buildTitlesTable) -- not an error by
        itself, __applyTitles's callers decide what that means."""
        result = {}
        if len(ids) == 0:
            return result
        c = self.__getCursor()
        for batch in self.__chunks(ids):
            placeholders = ",".join("?" for _ in batch)
            c.execute("SELECT imdb_id, title_type_name, primary_title, original_title, start_year, end_year, rating_mul10, num_votes FROM titles WHERE imdb_id IN (" + placeholders + ")", batch)
            for row in c.fetchall():
                result[row[0]] = row[1:]
        return result

    def __applyTitles(self, content_dict, mode, remove_illegal): # mode: "ratings" | "basics" | "basics_refresh"
        if len(content_dict) == 0:
            return content_dict

        titlesById = self.__fetchTitles(content_dict.keys())
        for imdb_id, row in titlesById.items():
            media_obj = content_dict[imdb_id]
            if mode == "ratings":
                content_dict[imdb_id] = self.__insertTitleRatings(media_obj, row)
            elif mode == "basics":
                content_dict[imdb_id] = self.__insertTitleBasics(media_obj, row)
            elif mode == "basics_refresh":
                content_dict[imdb_id] = self.__insertTitleBasicsRefresh(media_obj, row)
            else:
                raise RuntimeError("unknown mode " + str(mode)) # internal misuse: mode is always one of the above, passed by this class's own methods

        if remove_illegal:
            # make sure that all items have been touched; mark ones that are illegal for deletion
            illegal_ids = []
            for x in content_dict.values():
                if mode == "ratings" and x.numVotes == None and x.subdir == None:
                    # numVotes missing entirely is otherwise unremarkable (see __insertTitleRatings --
                    # it's a perfectly normal, nullable field), so this specific combination -- no
                    # votes at all, and not locally owned -- is the only case worth an online check;
                    # print it as it happens, since it's the one thing in this whole step that
                    # actually visits an IMDb page rather than just querying the local helper DB
                    print("  checking in-development status for " + x.getIDString() + "...")
                    if self.scrapeimdbonline.isInDevelopment(x.imdb_id): # in-development titles are excluded
                        print("  discarding referenced-only title " + x.getIDString() + ": in development, no ratings yet")
                        # illegal title. mark for deletion from dict keys and mediaConnections
                        illegal_ids.append(x.imdb_id)
                        continue

                if mode == "basics" and x.titleType in (None, "localMovie", "localSeries"): # titleType still unset or still the local-scrape placeholder: no usable row was found in titles
                    if x.series_imdb_id is not None:
                        # known to be an episode via the episodes table, but missing from titles --
                        # the two offline datasets disagree with each other. Always an error, regardless
                        # of ownership (unlike movies/series, a referenced-only episode is never silently
                        # discarded -- catalog completeness for a series' episodes is the whole point)
                        raise OfflineDatasetError("episode " + x.getIDString() + " found in title.episode.tsv but missing usable data in title.basics.tsv")
                    if x.titleType == "localSeries":
                        # a locally-owned series missing usable data in titles: by this point its local
                        # episodes have already resolved successfully against the episodes table (see
                        # main.py step 2), so that table already treats this id as a real, cataloged
                        # series -- title.basics.tsv disagreeing is a dataset inconsistency, not a
                        # genuinely obscure title worth an online fallback lookup, unlike a movie
                        raise OfflineDatasetError("series " + x.getIDString() + " has episodes in title.episode.tsv but is missing usable data in title.basics.tsv")
                    if x.subdir == None:
                        # referenced-only title missing usable data: not worth an online fallback scrape, discard
                        print("  discarding referenced-only title " + x.getIDString() + ": missing usable data in the offline dataset")
                        illegal_ids.append(x.imdb_id)
                        continue
                    else:
                        # locally-owned title missing usable data (e.g. very obscure titles): flag for online fallback instead of silently dropping it
                        x.needsOnlineFallback = True
                        continue

                if mode == "basics" and x.titleType not in Media.movieTitleTypes + Media.seriesTitleTypes + Media.episodeTitleTypes:
                    # found in the dataset, but not an acceptable title type (e.g. a TV episode ending up in the movie library)
                    print("  discarding referenced-only title " + x.getIDString() + ": unacceptable title type '" + str(x.titleType) + "'")
                    illegal_ids.append(x.imdb_id)

            # remove illegal media from dict
            for x in illegal_ids:
                content_dict.pop(x)

            # remove references to illegal media
            for x in content_dict.values():
                content_dict[x.imdb_id].mediaConnections = [y for y in x.mediaConnections if not y.foreignIMDbID in illegal_ids]

        return content_dict

    def __insertTitleRatings(self, media_obj, row): # row: (title_type_name, primary_title, original_title, start_year, end_year, rating_mul10, num_votes)
        media_obj.rating_mul10 = row[5]
        media_obj.numVotes = row[6]
        return media_obj

    def __titleTypeCategory(self, titleType):
        """Which of Media's three titleType lists titleType belongs to ("movie"/"series"/"episode"),
        or None if it doesn't belong to any of them."""
        if titleType in Media.movieTitleTypes:
            return "movie"
        if titleType in Media.seriesTitleTypes:
            return "series"
        if titleType in Media.episodeTitleTypes:
            return "episode"
        return None

    def __insertTitleBasics(self, media_obj, row): # row: (title_type_name, primary_title, original_title, start_year, end_year, rating_mul10, num_votes)
        localTitleType = media_obj.titleType # result of local parsing (movie or series), or None for referenced-only media and episodes
        titleType = row[0]
        if ((localTitleType == "localMovie" and titleType not in Media.movieTitleTypes)
            or (localTitleType == "localSeries" and titleType not in Media.seriesTitleTypes)
            or (media_obj.series_imdb_id is not None and titleType not in Media.episodeTitleTypes)):
            # the third condition catches title.basics.tsv disagreeing with title.episode.tsv about
            # whether this id is actually an episode (series_imdb_id is only ever set by parseTitleEpisode)
            raise OfflineDatasetError("title type " + titleType + " not acceptable for local parsing result " + str(localTitleType))
        media_obj.titleType = titleType
        media_obj.primaryTitle = row[1]
        media_obj.originalTitle = row[2]
        if media_obj.startYear != None and media_obj.startYear != row[3]:
            raise OfflineDatasetError("startYear does not match for title " + media_obj.getIDString() + " " + row[2] + " (" + str(media_obj.startYear) + " vs. " + str(row[3]) + ")")
        media_obj.startYear = row[3]
        media_obj.endYear = row[4]

        return media_obj

    def __insertTitleBasicsRefresh(self, media_obj, row): # row: (title_type_name, primary_title, original_title, start_year, end_year, rating_mul10, num_votes)
        """Refreshes an already-known medium's basics against the current dataset. primaryTitle/
        originalTitle/endYear are silently updated. titleType may only change within the same
        category (movie/series/episode) it was already in -- e.g. "movie" -> "tvMovie" is fine,
        "movie" -> "tvSeries" is not, since that would mean this id fundamentally isn't the kind of
        thing it was added as. startYear must not have changed at all. Any violation raises
        OfflineDatasetError. An id with no matching row at all (gone missing, or now missing
        titleType/primaryTitle/originalTitle/startYear, since it was first read) is left with its
        previously-known fields unchanged -- __applyTitles simply never calls this for it."""

        titleType = row[0]
        oldCategory = self.__titleTypeCategory(media_obj.titleType)
        newCategory = self.__titleTypeCategory(titleType)
        if newCategory is None or newCategory != oldCategory:
            raise OfflineDatasetError("titleType for " + media_obj.getIDString() + " changed from '" + str(media_obj.titleType) + "' to '" + titleType + "', crossing categories")
        media_obj.titleType = titleType

        media_obj.primaryTitle = row[1]
        media_obj.originalTitle = row[2]

        if media_obj.startYear != row[3]:
            raise OfflineDatasetError("startYear for " + media_obj.getIDString() + " changed from " + str(media_obj.startYear) + " to " + str(row[3]))

        media_obj.endYear = row[4]

        return media_obj
