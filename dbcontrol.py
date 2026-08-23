import sqlite3
from media import Media
from mediaversion import MediaVersion
from mediaconnection import MediaConnection
from exceptions import LocalLibraryError

class DBControl:

    def __init__(self, dbLocation):
        """Initialize db class variables"""
        self.conn = sqlite3.connect(dbLocation)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.c = self.conn.cursor()

    def close(self):
        """close sqlite3 connection"""
        self.conn.close()

    def createMediaDB(self):
        with self.conn:
            # media table holds both media present in library and those only linked by IMDb connections. differentiator if medium is actually present is subdir not being NULL.
            # covers movies, series, and episodes alike. subdir is not UNIQUE: an episode's subdir is
            # its season folder's path, shared by every sibling episode in that season (see
            # ScrapeLocal.__scrapeSingleSeries) -- ownership is per-episode via imdb_id, not subdir.
            # season_number/episode_number/series_imdb_id are only ever set for episodes (titleType
            # in Media.episodeTitleTypes); NULL there means IMDb has no season/episode number for
            # this episode (never conflated with a real number -- see ScrapeIMDbOffline.parseTitleEpisode)
            self.c.execute("""CREATE TABLE media (
            imdb_id integer NOT NULL,
            title_type_id integer NOT NULL,
            originalTitle text NOT NULL,
            primaryTitle text NOT NULL,
            startYear integer NOT NULL,
            endYear integer,
            rating_mul10 integer,
            numVotes integer,
            releaseMonth integer,
            releaseDay integer,
            subdir text,
            language_id integer NOT NULL DEFAULT 0,
            plotSummary text,
            season_number integer,
            episode_number integer,
            series_imdb_id integer,
            PRIMARY KEY (imdb_id),
            FOREIGN KEY (title_type_id)
                REFERENCES title_type_enum (title_type_id)
                    ON UPDATE CASCADE
                    ON DELETE RESTRICT,
            FOREIGN KEY (language_id)
                REFERENCES language_enum (imdb_interest_id)
                    ON UPDATE CASCADE
                    ON DELETE RESTRICT,
            FOREIGN KEY (series_imdb_id)
                REFERENCES media (imdb_id)
                    ON UPDATE CASCADE
                    ON DELETE RESTRICT
            )""")

            # media_interests holds both standard genres and IMDb "interests" (subgenres), differentiated in interest_enum
            # only populated for locally-owned media (subdir NOT NULL); referenced-only media have no entries here.
            # imdb_interest_id is stored as the integer form of IMDb's "inXXXXXXX" id (see imdbinterestid.py)
            self.c.execute("""CREATE TABLE media_interests (
            imdb_id integer NOT NULL,
            imdb_interest_id integer NOT NULL,
            PRIMARY KEY (imdb_id, imdb_interest_id),
            FOREIGN KEY (imdb_id)
                REFERENCES media (imdb_id)
                    ON UPDATE CASCADE
                    ON DELETE CASCADE,
            FOREIGN KEY (imdb_interest_id)
                REFERENCES interest_enum (imdb_interest_id)
                    ON UPDATE CASCADE
                    ON DELETE CASCADE
            )""")

            # keyed by the integer form of IMDb's own interest id (e.g. "in0000076" -> 76).
            # parent_imdb_interest_id is NULL for standard genres and always set for subgenre "interests".
            # populated dynamically as new interests are discovered during online scraping, not pre-seeded.
            self.c.execute("""CREATE TABLE interest_enum (
            imdb_interest_id integer NOT NULL,
            name text NOT NULL,
            description text NOT NULL,
            parent_imdb_interest_id integer,
            PRIMARY KEY (imdb_interest_id),
            FOREIGN KEY (parent_imdb_interest_id)
                REFERENCES interest_enum (imdb_interest_id)
                    ON UPDATE CASCADE
                    ON DELETE RESTRICT
            )""")

            # lookup for IMDb interests that turned out to be languages rather than genres/subgenres
            # (e.g. "German"), keyed by the integer form of IMDb's interest id. Referenced by
            # media.language_id; also serves as a cache to avoid re-classifying an already-known language.
            self.c.execute("""CREATE TABLE language_enum (
            imdb_interest_id integer NOT NULL,
            name text NOT NULL UNIQUE,
            description text NOT NULL,
            PRIMARY KEY (imdb_interest_id)
            )""")
            # English has no IMDb interest id of its own (confirmed absent from IMDb's full interest
            # directory) since it's the unmarked default -- 0 is used as a reserved id here, since
            # real IMDb interest ids (in\d+) are always 1 or greater and can never collide with it
            self.c.execute("INSERT INTO language_enum VALUES (?, ?, ?)", (0, "English", "English-language cinema encompasses a vast and influential body of filmmaking, from Hollywood's genre-defining blockbusters to British drama and independent voices across the English-speaking world. It has driven major innovations in visual effects, narrative structure, and global distribution, shaping how audiences everywhere experience film. Its reach and influence remain unmatched, setting trends that ripple through the international film industry."))

            self.c.execute("""CREATE TABLE title_type_enum (
            title_type_id integer NOT NULL,
            title_type_name text NOT NULL UNIQUE,
            PRIMARY KEY (title_type_id)
            )""")
            i = 1
            for titleType in Media.movieTitleTypes + Media.seriesTitleTypes + Media.episodeTitleTypes:
                self.c.execute("INSERT INTO title_type_enum VALUES (?, ?)", (i, titleType))
                i += 1

            self.c.execute("""CREATE TABLE media_versions (
            imdb_id integer NOT NULL,
            filename text NOT NULL,
            source text NOT NULL,
            version text,
            PRIMARY KEY (imdb_id, filename),
            UNIQUE (imdb_id, version),
            FOREIGN KEY (imdb_id)
                REFERENCES media (imdb_id)
                    ON UPDATE CASCADE
                    ON DELETE CASCADE
            )""")

            # fixed, pre-seeded classification of physical/digital media a mediaVersion's source(s)
            # can come from (see Media.source_type_list)
            self.c.execute("""CREATE TABLE source_type_enum (
            source_type_id integer NOT NULL,
            source_type_name text NOT NULL UNIQUE,
            PRIMARY KEY (source_type_id)
            )""")
            i = 1
            for source_type in Media.source_type_list:
                self.c.execute("INSERT INTO source_type_enum VALUES (?, ?)", (i, source_type))
                i += 1

            # fixed, pre-seeded structural role a single leaf source plays within a mediaVersion's
            # overall source description (see Media.source_role_list)
            self.c.execute("""CREATE TABLE source_role_enum (
            role_id integer NOT NULL,
            role_name text NOT NULL UNIQUE,
            PRIMARY KEY (role_id)
            )""")
            i = 1
            for source_role in Media.source_role_list:
                self.c.execute("INSERT INTO source_role_enum VALUES (?, ?)", (i, source_role))
                i += 1

            # web download providers (e.g. "AMZN" -> "Amazon"), sourced from config.WEB_PROVIDERS.
            # Not pre-seeded here; kept in sync additively on every sync instead (see
            # syncWebProvidersFromConfig), so the enum -- not config -- is the actual source of
            # truth: removing a provider from config only stops it being re-affirmed, it doesn't
            # remove it or anything that already references it. web_provider_id is a plain SQLite
            # rowid (we mint these ourselves, unlike interest/language ids which come from IMDb)
            self.c.execute("""CREATE TABLE source_web_provider_enum (
            web_provider_id INTEGER PRIMARY KEY,
            abbreviation text NOT NULL UNIQUE,
            full_name text NOT NULL
            )""")

            # the leaf source(s) that make up a single mediaVersion's provenance. A version with a
            # single plain source has one row (role=main). hybrid/dynhdrhybrid/combined splits use
            # the video/audio/video_base/video_dynhdr roles, one row each. fanres allows more than
            # one row per role (seq disambiguates them), since a fan restoration can blend an
            # arbitrary number of sources for the same role.
            self.c.execute("""CREATE TABLE media_version_sources (
            imdb_id integer NOT NULL,
            filename text NOT NULL,
            role_id integer NOT NULL,
            seq integer NOT NULL,
            source_type_id integer NOT NULL,
            disc_id integer,
            disc_corrected integer,
            web_provider_id integer,
            base_layer integer,
            downmixed integer,
            core integer,
            fanres integer,
            PRIMARY KEY (imdb_id, filename, role_id, seq),
            FOREIGN KEY (imdb_id, filename)
                REFERENCES media_versions (imdb_id, filename)
                    ON UPDATE CASCADE
                    ON DELETE CASCADE,
            FOREIGN KEY (role_id)
                REFERENCES source_role_enum (role_id)
                    ON UPDATE CASCADE
                    ON DELETE RESTRICT,
            FOREIGN KEY (source_type_id)
                REFERENCES source_type_enum (source_type_id)
                    ON UPDATE CASCADE
                    ON DELETE RESTRICT,
            FOREIGN KEY (web_provider_id)
                REFERENCES source_web_provider_enum (web_provider_id)
                    ON UPDATE CASCADE
                    ON DELETE RESTRICT
            )""")

            self.c.execute("""CREATE TABLE media_connections (
            imdb_id integer NOT NULL,
            foreign_imdb_id integer NOT NULL,
            connection_type_id integer NOT NULL,
            PRIMARY KEY (imdb_id, foreign_imdb_id, connection_type_id),
            FOREIGN KEY (imdb_id)
                REFERENCES media (imdb_id)
                    ON UPDATE CASCADE
                    ON DELETE CASCADE,
            FOREIGN KEY (foreign_imdb_id)
                REFERENCES media (imdb_id)
                    ON UPDATE CASCADE
                    ON DELETE RESTRICT,
            FOREIGN KEY (connection_type_id)
                REFERENCES connection_type_enum (connection_type_id)
                    ON UPDATE CASCADE
                    ON DELETE RESTRICT
            )""")

            self.c.execute("""CREATE TABLE connection_type_enum (
            connection_type_id integer NOT NULL,
            connection_type_name text NOT NULL UNIQUE,
            PRIMARY KEY (connection_type_id)
            )""")
            i = 1
            for connection_type in MediaConnection.connectionTypeList:
                self.c.execute("INSERT INTO connection_type_enum VALUES (?, ?)", (i, connection_type))
                i += 1

            # imdb ids that must never appear in the DB at all; kept in sync (non-additively) from
            # config.IGNORED_IDS_PATH (see syncIgnoredAndWontaddIDs/enforceIgnoredAndWontaddIDs)
            self.c.execute("""CREATE TABLE ignored_ids (
            imdb_id integer NOT NULL,
            PRIMARY KEY (imdb_id)
            )""")

            # imdb ids allowed to reside in the DB as referenced-only media, but never intended to
            # be added as local media; kept in sync (non-additively) from config.WONTADD_IDS_PATH
            self.c.execute("""CREATE TABLE wontadd_ids (
            imdb_id integer NOT NULL,
            PRIMARY KEY (imdb_id)
            )""")

            # imdb interest ids already known to be franchise-type (e.g. "Evil Dead") -- these are
            # deliberately never attached to any medium or added to interest_enum itself (that
            # relationship is already covered via media_connections/MediaConnection); this table
            # exists purely so a franchise doesn't need to be re-classified (an extra IMDb page
            # visit) on every future sync. Populated additively as new ones are discovered, see
            # ScrapeIMDbOnline.__classifyChips / DBControl.ensureFranchiseInterestExists
            self.c.execute("""CREATE TABLE franchise_interest_ids (
            imdb_interest_id integer NOT NULL,
            PRIMARY KEY (imdb_interest_id)
            )""")

    def addSingleMediaWoConnections(self, thisMedia):
        if not isinstance(thisMedia, Media):
            raise TypeError('no media object')
        with self.conn:
            self.c.execute("SELECT originalTitle, subdir FROM media WHERE imdb_id = ?", (thisMedia.imdb_id,)) # need to get originalTitle as well, as otherwise no NULL subdirs will be returned
            data = self.c.fetchall()
            if len(data) == 0:
                self.c.execute("INSERT INTO media VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (thisMedia.imdb_id, self.__getTitleTypeIDByTitleTypeName(thisMedia.titleType), thisMedia.originalTitle, thisMedia.primaryTitle, thisMedia.startYear, thisMedia.endYear, thisMedia.rating_mul10, thisMedia.numVotes, thisMedia.releaseMonth, thisMedia.releaseDay, thisMedia.subdir, thisMedia.language_id, thisMedia.plotSummary, thisMedia.season_number, thisMedia.episode_number, thisMedia.series_imdb_id))
            elif data[0][1] == None:
                self.c.execute("UPDATE media SET title_type_id=?, originalTitle=?, primaryTitle=?, startYear=?, endYear=?, rating_mul10=?, numVotes=?, releaseMonth=?, releaseDay=?, subdir=?, language_id=?, plotSummary=?, season_number=?, episode_number=?, series_imdb_id=? WHERE imdb_id=?", (self.__getTitleTypeIDByTitleTypeName(thisMedia.titleType), thisMedia.originalTitle, thisMedia.primaryTitle, thisMedia.startYear, thisMedia.endYear, thisMedia.rating_mul10, thisMedia.numVotes, thisMedia.releaseMonth, thisMedia.releaseDay, thisMedia.subdir, thisMedia.language_id, thisMedia.plotSummary, thisMedia.season_number, thisMedia.episode_number, thisMedia.series_imdb_id, thisMedia.imdb_id))
            else:
                raise RuntimeError('already existing media object supposed to be newly added: ' + data[0][0])
            for imdb_interest_id in thisMedia.interests:
                self.c.execute("INSERT INTO media_interests VALUES (?, ?)", (thisMedia.imdb_id, imdb_interest_id))
            for mediaVersion in thisMedia.mediaVersions:
                self.c.execute("INSERT INTO media_versions VALUES (?, ?, ?, ?)", (thisMedia.imdb_id, mediaVersion.filename, mediaVersion.source, mediaVersion.version))
                for source in mediaVersion.sources:
                    self.c.execute("INSERT INTO media_version_sources VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (
                        thisMedia.imdb_id,
                        mediaVersion.filename,
                        self.__getSourceRoleIDByName(source.role),
                        source.seq,
                        self.__getSourceTypeIDByName(source.source_type),
                        source.disc_id,
                        int(source.disc_corrected),
                        self.__getWebProviderIDByAbbreviation(source.web_provider) if source.web_provider is not None else None,
                        int(source.base_layer),
                        int(source.downmixed),
                        int(source.core),
                        int(source.fanres),
                    ))

    def addSingleMediaConnections(self, thisMedia):
        if not isinstance(thisMedia, Media):
            raise TypeError('no media object')
        with self.conn:
            for mediaConnection in thisMedia.mediaConnections:
                self.c.execute("INSERT INTO media_connections VALUES (?, ?, ?)", (thisMedia.imdb_id, mediaConnection.foreignIMDbID, self.__getConnectionTypeIDByConnectionTypeName(mediaConnection.connectionType)))

    def addMultipleMedia(self, mediaDict): # media and connections must be separated, so that foreign constraints are always fulfilled during db entry
        for x in mediaDict.values():
            self.addSingleMediaWoConnections(x)
        for x in mediaDict.values():
            self.addSingleMediaConnections(x)

    def removeMultipleMedia(self, removedDict):
        for x in removedDict.values():
            self.removeSingleMedia(x)

    def removeSingleMedia(self, mediumToRemove):
        with self.conn:
            #1. remove all media_versions of mediumToRemove
            self.c.execute("DELETE FROM media_versions WHERE imdb_id=?", (mediumToRemove.imdb_id,))

            #2. remove and save all connections FROM mediumToRemove to list referencesToRemove
            self.c.execute("SELECT imdb_id, foreign_imdb_id FROM media_connections WHERE imdb_id=?", (mediumToRemove.imdb_id,))
            referencesToRemove = self.c.fetchall()
            self.c.execute("DELETE FROM media_connections WHERE imdb_id=?", (mediumToRemove.imdb_id,))

            #3. check whether there are any connections TO mediumToRemove
            self.c.execute("SELECT * FROM media_connections WHERE foreign_imdb_id=?", (mediumToRemove.imdb_id,))
            remainingConnections = self.c.fetchall()

            # a series can't be safely deleted while it still has an episode that's owned or
            # referenced (series_imdb_id's FK requires the series row to exist); clean up any
            # no-longer-needed episodes first (no-op if mediumToRemove isn't a series), and treat
            # the series as still-referenced if any episode remains afterward
            seriesHasNeededEpisodes = not self.__removeUnneededSeriesEpisodes(mediumToRemove.imdb_id)

            # capture mediumToRemove's current interests and language before they're removed, so
            # anything left with no remaining attachments afterward can be pruned
            self.c.execute("SELECT imdb_interest_id FROM media_interests WHERE imdb_id=?", (mediumToRemove.imdb_id,))
            affectedInterestIDs = [row[0] for row in self.c.fetchall()]
            self.c.execute("SELECT language_id FROM media WHERE imdb_id=?", (mediumToRemove.imdb_id,))
            affectedLanguageIDs = [row[0] for row in self.c.fetchall()]

            #3a. if yes: only "light-remove" mediumToRemove (remove subdir, interests, and reset
            # language to the default; these are only valid for locally-owned media)
            if len(remainingConnections) != 0 or seriesHasNeededEpisodes:
                print("Removing " + mediumToRemove.originalTitle + " from DB as local medium (still being referenced)")
                self.c.execute("UPDATE media SET subdir = NULL, language_id = 0 WHERE imdb_id=?", (mediumToRemove.imdb_id,))
                self.c.execute("DELETE FROM media_interests WHERE imdb_id=?", (mediumToRemove.imdb_id,))

            #3b. if no: remove media entry (media_interests rows are removed via ON DELETE CASCADE)
            else:
                print("Removing " + mediumToRemove.originalTitle + " from DB")
                self.c.execute("DELETE FROM media WHERE imdb_id=?", (mediumToRemove.imdb_id,))

            self.__pruneOrphanedInterests(affectedInterestIDs)
            self.__pruneOrphanedLanguages(affectedLanguageIDs)

            # if mediumToRemove was itself an episode, its parent series might now be orphaned
            if mediumToRemove.series_imdb_id is not None:
                self.__pruneOrphanedSeries([mediumToRemove.series_imdb_id])

            #4. for all x in list referencesToRemove:
            for x in referencesToRemove:

                #4a. if x not in db table media or if subdir NOT EMPTY: continue
                self.c.execute("SELECT imdb_id, originalTitle, subdir FROM media WHERE imdb_id=?", (x[1],))
                mediumData = self.c.fetchall()
                if len(mediumData) == 0 or mediumData[0][2] != None:
                    continue

                #4b. check whether there are any connections TO x
                self.c.execute("SELECT * FROM media_connections WHERE foreign_imdb_id=?", (x[1],))
                remainingConnections = self.c.fetchall()

                #4b1. if yes: continue
                if len(remainingConnections) != 0:
                    continue

                #4b2. if no: remove media entry (media_interests rows are removed via ON DELETE CASCADE)
                else:
                    print("Removing referenced medium " + mediumData[0][1] + " from DB")
                    self.c.execute("DELETE FROM media WHERE imdb_id=?", (x[1],))

    def refreshRatings(self, mediaDict):
        with self.conn:
            for imdbID, media in mediaDict.items():
                self.c.execute("UPDATE media SET rating_mul10=?, numVotes=? WHERE imdb_id=?", (media.rating_mul10, media.numVotes, imdbID))

    def getAllMediaIDs(self):
        with self.conn:
            self.c.execute("SELECT imdb_id FROM media")
            return(self.c.fetchall())

    def getDictWithImdbIDs(self):
        dbResult = self.getAllMediaIDs()
        resultDict = {}
        for entry in dbResult:
            resultDict[entry[0]] = Media(None, None, entry[0])
        return(resultDict)

    def getAllKnownInterestIDs(self):
        """Set of all IMDb interest ids already present in interest_enum (both genres and subgenres)."""
        with self.conn:
            self.c.execute("SELECT imdb_interest_id FROM interest_enum")
            return set(row[0] for row in self.c.fetchall())

    def getAllKnownPseudoGenreIDs(self):
        """Name -> imdb_interest_id map of already-known pseudo-genres: synthetic, negative ids
        minted for an IMDb taxonomy category (e.g. "Seasonal") that groups subgenres without being
        a real, individually taggable interest itself -- see ScrapeIMDbOnline.__classifyChips.
        Real genres/subgenres always have a positive id, so this can't collide with them."""
        with self.conn:
            self.c.execute("SELECT name, imdb_interest_id FROM interest_enum WHERE imdb_interest_id < 0")
            return {row[0]: row[1] for row in self.c.fetchall()}

    def getMediaIDsWithInterests(self):
        """Set of imdb_ids that already have at least one media_interests row."""
        with self.conn:
            self.c.execute("SELECT DISTINCT imdb_id FROM media_interests")
            return set(row[0] for row in self.c.fetchall())

    def ensureInterestExists(self, imdb_interest_id, name, description, parent_imdb_interest_id=None):
        """Insert a newly-discovered interest (genre or subgenre) into interest_enum if not already known."""
        with self.conn:
            self.c.execute("INSERT OR IGNORE INTO interest_enum VALUES (?, ?, ?, ?)", (imdb_interest_id, name, description, parent_imdb_interest_id))

    def getAllKnownLanguageIDs(self):
        """Set of all IMDb interest ids already known to be languages (in language_enum)."""
        with self.conn:
            self.c.execute("SELECT imdb_interest_id FROM language_enum")
            return set(row[0] for row in self.c.fetchall())

    def ensureLanguageExists(self, imdb_interest_id, name, description):
        """Insert a newly-discovered language interest into language_enum if not already known."""
        with self.conn:
            self.c.execute("INSERT OR IGNORE INTO language_enum VALUES (?, ?, ?)", (imdb_interest_id, name, description))

    def getAllKnownFranchiseIDs(self):
        """Set of all IMDb interest ids already known to be franchise-type (in franchise_interest_ids
        -- see ScrapeIMDbOnline.__classifyChips)."""
        with self.conn:
            self.c.execute("SELECT imdb_interest_id FROM franchise_interest_ids")
            return set(row[0] for row in self.c.fetchall())

    def ensureFranchiseInterestExists(self, imdb_interest_id):
        """Records a newly-discovered franchise-type interest id into franchise_interest_ids if not
        already known, so it's skipped without re-classification on future syncs."""
        with self.conn:
            self.c.execute("INSERT OR IGNORE INTO franchise_interest_ids VALUES (?)", (imdb_interest_id,))

    def syncWebProvidersFromConfig(self, web_providers):
        """Additively syncs source_web_provider_enum from a {abbreviation: full_name} dict (see
        config.WEB_PROVIDERS). Only ever inserts; never updates or removes an existing row, so the
        enum -- not config -- remains the actual source of truth (see createMediaDB's comment on
        this table). Meant to be called on every sync."""
        with self.conn:
            for abbreviation, full_name in web_providers.items():
                self.c.execute("INSERT OR IGNORE INTO source_web_provider_enum (abbreviation, full_name) VALUES (?, ?)", (abbreviation, full_name))

    def checkWebProvidersKnown(self, mediaDict):
        """Raises LocalLibraryError listing every web provider abbreviation referenced by
        mediaDict's local sources that isn't (yet) in source_web_provider_enum. Meant to be called
        right after the local scan and syncWebProvidersFromConfig, before any online scraping --
        this only depends on locally-scraped source strings, so there's no reason to only discover
        a config.ini gap at DB-write time, after a full sync's worth of scraping already ran."""
        usedAbbreviations = set()
        for medium in mediaDict.values():
            for mediaVersion in medium.mediaVersions:
                for source in mediaVersion.sources:
                    if source.web_provider is not None:
                        usedAbbreviations.add(source.web_provider)
        with self.conn:
            self.c.execute("SELECT abbreviation FROM source_web_provider_enum")
            knownAbbreviations = {row[0] for row in self.c.fetchall()}
        missing = usedAbbreviations - knownAbbreviations
        if missing:
            raise LocalLibraryError("unknown web provider abbreviation(s) " + ", ".join(sorted(missing)) +
                                     " -- add them to config.ini's [web_providers] section and sync again")

    def syncIgnoredAndWontaddIDs(self, ignored_ids, wontadd_ids):
        """Non-additively syncs ignored_ids/wontadd_ids from the given sets of imdb ids (see
        config.IGNORED_IDS_PATH/WONTADD_IDS_PATH) -- unlike syncWebProvidersFromConfig, removing
        an id from the source list actually removes it here, since these lists are meant to be
        fully user-editable. Meant to be called on every sync, before enforceIgnoredAndWontaddIDs."""
        with self.conn:
            self.c.execute("DELETE FROM ignored_ids")
            self.c.executemany("INSERT INTO ignored_ids VALUES (?)", [(imdb_id,) for imdb_id in ignored_ids])
            self.c.execute("DELETE FROM wontadd_ids")
            self.c.executemany("INSERT INTO wontadd_ids VALUES (?)", [(imdb_id,) for imdb_id in wontadd_ids])

    def enforceIgnoredAndWontaddIDs(self):
        """Enforces ignored_ids/wontadd_ids against the current DB state: raises LocalLibraryError
        if any locally-owned medium's id is on either list (this is a configuration error the user
        needs to fix), and removes any referenced-only medium whose id is on ignored_ids -- fully,
        regardless of what still references it, unlike removeSingleMedia's "light-remove" (which
        exists for media that merely stopped being locally owned, not for media that must never be
        in the DB at all). Meant to be called right after syncIgnoredAndWontaddIDs, at the very
        start of every sync (before any local scanning/scraping) -- this reconciles drift left over
        from a list edited since the last sync. New violations introduced during the rest of the
        sync itself are instead caught on the go: newly-added local media are checked right after
        the local scan, and newly-discovered referenced ids on ignored_ids are simply never added
        in the first place, so nothing new for this method to clean up accumulates by the end."""
        with self.conn:
            self.c.execute("""SELECT imdb_id, originalTitle FROM media WHERE subdir IS NOT NULL
                AND imdb_id IN (SELECT imdb_id FROM ignored_ids UNION SELECT imdb_id FROM wontadd_ids)""")
            violatingLocal = self.c.fetchall()
        if violatingLocal:
            raise LocalLibraryError("locally-owned media found on the ignored/wontadd list(s): " +
                                     ", ".join(row[1] + " (tt" + str(row[0]).zfill(7) + ")" for row in violatingLocal))

        with self.conn:
            self.c.execute("""SELECT imdb_id, originalTitle, series_imdb_id FROM media WHERE subdir IS NULL
                AND imdb_id IN (SELECT imdb_id FROM ignored_ids)""")
            referencedIgnored = self.c.fetchall()
            for imdb_id, originalTitle, series_imdb_id in referencedIgnored:
                print("Removing referenced medium " + originalTitle + " from DB (now on ignored list)")
                self.c.execute("SELECT imdb_interest_id FROM media_interests WHERE imdb_id=?", (imdb_id,))
                affectedInterestIDs = [row[0] for row in self.c.fetchall()]
                self.c.execute("SELECT language_id FROM media WHERE imdb_id=?", (imdb_id,))
                affectedLanguageIDs = [row[0] for row in self.c.fetchall()]

                # an ignored series must go regardless of any episode still needing it -- unlike
                # normal removal, "ignored" means gone no matter what, so its episodes are forced
                # out too (no-op if imdb_id isn't a series)
                self.c.execute("SELECT imdb_id FROM media WHERE series_imdb_id=?", (imdb_id,))
                for (episode_id,) in self.c.fetchall():
                    self.c.execute("DELETE FROM media_connections WHERE imdb_id=? OR foreign_imdb_id=?", (episode_id, episode_id))
                    self.c.execute("DELETE FROM media WHERE imdb_id=?", (episode_id,))

                self.c.execute("DELETE FROM media_connections WHERE imdb_id=? OR foreign_imdb_id=?", (imdb_id, imdb_id))
                self.c.execute("DELETE FROM media WHERE imdb_id=?", (imdb_id,))
                self.__pruneOrphanedInterests(affectedInterestIDs)
                self.__pruneOrphanedLanguages(affectedLanguageIDs)

                # if imdb_id was itself an episode, its parent series might now be orphaned
                if series_imdb_id is not None:
                    self.__pruneOrphanedSeries([series_imdb_id])

    def __pruneOrphanedInterests(self, imdb_interest_ids):
        """Removes any of the given interests (genre or subgenre) from interest_enum once they're
        no longer attached to any medium (media_interests) AND no longer have any subgenre
        depending on them as a parent. The second condition is always true for subgenres (nothing
        is ever a subgenre's child in this two-level taxonomy), so it only meaningfully restricts
        genres: a genre survives as long as it's either directly used, or still has a live
        subgenre under it. When a subgenre is pruned, its parent genre is re-checked too, since
        losing that subgenre may make the parent newly eligible."""
        idsToCheck = list(imdb_interest_ids)
        while idsToCheck:
            imdb_interest_id = idsToCheck.pop()

            self.c.execute("SELECT parent_imdb_interest_id FROM interest_enum WHERE imdb_interest_id = ?", (imdb_interest_id,))
            row = self.c.fetchone()
            if row is None:
                continue # already pruned (e.g. via an earlier id in this same batch), or never existed
            parent_id = row[0]

            self.c.execute("""
                DELETE FROM interest_enum
                WHERE imdb_interest_id = ?
                AND NOT EXISTS (SELECT 1 FROM media_interests WHERE imdb_interest_id = ?)
                AND NOT EXISTS (SELECT 1 FROM interest_enum WHERE parent_imdb_interest_id = ?)
            """, (imdb_interest_id, imdb_interest_id, imdb_interest_id))

            if self.c.rowcount > 0 and parent_id is not None:
                idsToCheck.append(parent_id)

    def __pruneOrphanedLanguages(self, imdb_interest_ids):
        """Removes any of the given languages from language_enum once no medium uses them anymore.
        English (id 0) is never pruned, since it's the permanent default media.language_id falls
        back to (and is required to exist by that column's foreign key)."""
        for imdb_interest_id in imdb_interest_ids:
            if imdb_interest_id == 0:
                continue
            self.c.execute("""
                DELETE FROM language_enum
                WHERE imdb_interest_id = ?
                AND NOT EXISTS (SELECT 1 FROM media WHERE language_id = ?)
            """, (imdb_interest_id, imdb_interest_id))

    def __removeUnneededSeriesEpisodes(self, series_imdb_id):
        """Removes every episode of the given series that's neither locally owned nor referenced by
        anything else (media_connections). Returns True if none remain afterward -- i.e. the series
        itself has no more reason to exist because of its episodes -- or False if at least one is
        still needed, in which case the series must survive too (series_imdb_id's FK requires the
        series row to exist as long as any episode points at it). A no-op, returning True, for a
        medium that isn't a series (nothing ever has series_imdb_id pointing at a movie/episode)."""
        self.c.execute("SELECT imdb_id, originalTitle, subdir FROM media WHERE series_imdb_id=?", (series_imdb_id,))
        episodes = self.c.fetchall()
        anyStillNeeded = False
        for episode_id, episode_title, episode_subdir in episodes:
            if episode_subdir is not None:
                anyStillNeeded = True
                continue
            self.c.execute("SELECT * FROM media_connections WHERE foreign_imdb_id=?", (episode_id,))
            if len(self.c.fetchall()) != 0:
                anyStillNeeded = True
                continue
            print("Removing episode " + str(episode_title) + " from DB (no longer needed)")
            self.c.execute("DELETE FROM media_connections WHERE imdb_id=? OR foreign_imdb_id=?", (episode_id, episode_id))
            self.c.execute("DELETE FROM media WHERE imdb_id=?", (episode_id,))
        return not anyStillNeeded

    def __pruneOrphanedSeries(self, series_imdb_ids):
        """Removes any of the given series once it's no longer locally owned, no longer referenced
        by anything else, and has no episode still depending on it either (via
        __removeUnneededSeriesEpisodes) -- the series/episode analogue of __pruneOrphanedInterests's
        genre/subgenre shape. Unlike that one, no further cascading re-check is needed here: a
        series has no "parent" of its own to affect once it's gone."""
        for series_imdb_id in series_imdb_ids:
            self.c.execute("SELECT subdir, originalTitle FROM media WHERE imdb_id=?", (series_imdb_id,))
            row = self.c.fetchone()
            if row is None or row[0] is not None:
                continue # already removed, never existed, or still locally owned
            self.c.execute("SELECT * FROM media_connections WHERE foreign_imdb_id=?", (series_imdb_id,))
            if len(self.c.fetchall()) != 0:
                continue # still referenced by something else
            if not self.__removeUnneededSeriesEpisodes(series_imdb_id):
                continue # still has a needed episode
            print("Removing series " + str(row[1]) + " from DB (no longer needed)")
            self.c.execute("DELETE FROM media_connections WHERE imdb_id=? OR foreign_imdb_id=?", (series_imdb_id, series_imdb_id))
            self.c.execute("DELETE FROM media WHERE imdb_id=?", (series_imdb_id,))

    def __getTitleTypeIDByTitleTypeName(self, title_type_name):
        with self.conn:
            self.c.execute("SELECT title_type_id FROM title_type_enum WHERE title_type_name=?", (title_type_name,))
            title_type_id = self.c.fetchone()
            if not title_type_id or not title_type_id[0]:
                raise RuntimeError('unknown titleType ' + title_type_name)
            return(title_type_id[0])

    def __getTitleTypeNameByTitleTypeID(self, title_type_id):
        with self.conn:
            self.c.execute("SELECT title_type_name FROM title_type_enum WHERE title_type_id=?", (title_type_id,))
            title_type_name = self.c.fetchone()
            if not title_type_name or not title_type_name[0]:
                raise RuntimeError('unknown titleType ID ' + str(title_type_id))
            return(title_type_name[0])

    def __getConnectionTypeIDByConnectionTypeName(self, connectionType_name):
        with self.conn:
            self.c.execute("SELECT connection_type_id FROM connection_type_enum WHERE connection_type_name=?", (connectionType_name,))
            connection_type_id = self.c.fetchone()
            if not connection_type_id or not connection_type_id[0]:
                raise RuntimeError('unknown connection type ' + connectionType_name)
            return(connection_type_id[0])

    def __getConnectionTypeNameByConnectionTypeID(self, connectionType_id):
        with self.conn:
            self.c.execute("SELECT connection_type_name FROM connection_type_enum WHERE connection_type_id=?", (connectionType_id,))
            connection_type_name = self.c.fetchone()
            if not connection_type_name or not connection_type_name[0]:
                raise RuntimeError('unknown connection type ' + str(connectionType_id))
            return(connection_type_name[0])

    def __getSourceTypeIDByName(self, source_type_name):
        # source_type_name always comes from Media.source_type_list, which is what seeds this
        # enum, so a miss here means the two have drifted -- an internal bug, not bad local data
        with self.conn:
            self.c.execute("SELECT source_type_id FROM source_type_enum WHERE source_type_name=?", (source_type_name,))
            source_type_id = self.c.fetchone()
            if not source_type_id:
                raise RuntimeError('unknown source type ' + source_type_name)
            return(source_type_id[0])

    def __getSourceRoleIDByName(self, role_name):
        # role_name always comes from Media.source_role_list, which is what seeds this enum, so
        # a miss here means the two have drifted -- an internal bug, not bad local data
        with self.conn:
            self.c.execute("SELECT role_id FROM source_role_enum WHERE role_name=?", (role_name,))
            role_id = self.c.fetchone()
            if not role_id:
                raise RuntimeError('unknown source role ' + role_name)
            return(role_id[0])

    def __getWebProviderIDByAbbreviation(self, abbreviation):
        # unlike the two lookups above, a miss here is a genuine local-data problem: the source
        # string references a web provider abbreviation not present in source_web_provider_enum
        # (and therefore not in config.ini's [web_providers] section either, at least not as of
        # the last sync -- see DBControl.syncWebProvidersFromConfig)
        with self.conn:
            self.c.execute("SELECT web_provider_id FROM source_web_provider_enum WHERE abbreviation=?", (abbreviation,))
            web_provider_id = self.c.fetchone()
            if not web_provider_id:
                raise LocalLibraryError("unknown web provider abbreviation '" + abbreviation + "' -- add it to config.ini's [web_providers] section and sync again")
            return(web_provider_id[0])

    def determineNewlyAddedMedia(self, mediaDict):
        newlyAddedDict = {}
        with self.conn:
            for medium in mediaDict.values():
                self.c.execute("SELECT originalTitle, subdir FROM media WHERE imdb_id = ?", (medium.imdb_id,)) # need to get originalTitle as well, as otherwise no NULL subdirs will be returned
                data = self.c.fetchall()
                if len(data) == 0 or data[0][1] == None:
                    newlyAddedDict[medium.imdb_id] = medium
        return newlyAddedDict

    def determineLocallyRemovedMedia(self, mediaDict):
        removedDict = {}
        with self.conn:
            self.c.execute("SELECT imdb_id, originalTitle, series_imdb_id FROM media WHERE media.subdir IS NOT NULL")
            data = self.c.fetchall()
            for db_medium in data:
                if db_medium[0] not in mediaDict:
                    removedMedium = Media(None, None, db_medium[0])
                    removedMedium.originalTitle = db_medium[1]
                    removedMedium.series_imdb_id = db_medium[2]
                    removedDict[removedMedium.imdb_id] = removedMedium
        return removedDict

    def getReferencedOnlyMedia(self):
        with self.conn:
            self.c.execute("SELECT originalTitle, startYear, rating_mul10, numVotes FROM media WHERE subdir IS NULL ORDER BY numVotes DESC")
            return(self.c.fetchall())

    def __getMovieObjectFromDBRow(self, dbRow):
        # imdb_id, title_type_id, originalTitle, primaryTitle, startYear, endYear, rating_mul10, numVotes, releaseMonth, releaseDay, subdir, language_id, plotSummary, season_number, episode_number, series_imdb_id
        mediaObject = Media(None, None, dbRow[0])
        mediaObject.originalTitle = dbRow[2]
        mediaObject.primaryTitle = dbRow[3]
        mediaObject.startYear = dbRow[4]
        mediaObject.endYear = dbRow[5]
        mediaObject.rating_mul10 = dbRow[6]
        mediaObject.numVotes = dbRow[7]
        mediaObject.releaseMonth = dbRow[8]
        mediaObject.releaseDay = dbRow[9]
        mediaObject.subdir = dbRow[10]
        mediaObject.language_id = dbRow[11]
        mediaObject.plotSummary = dbRow[12]
        mediaObject.season_number = dbRow[13]
        mediaObject.episode_number = dbRow[14]
        mediaObject.series_imdb_id = dbRow[15]
        mediaObject.titleType = self.__getTitleTypeNameByTitleTypeID(dbRow[1])
        mediaObject.interests = self.__getInterestIDList(dbRow[0])
        mediaObject.mediaVersions = self.__getMediaVersionList(dbRow[0])
        mediaObject.mediaConnections = self.__getMediaConnectionsList(dbRow[0])
        return mediaObject

    def __getInterestIDList(self, imdbID):
        with self.conn:
            self.c.execute("SELECT imdb_interest_id FROM media_interests WHERE imdb_id=?", (imdbID,))
            return [row[0] for row in self.c.fetchall()]

    def __getMediaVersionList(self, imdbID):
        with self.conn:
            self.c.execute("SELECT * FROM media_versions WHERE imdb_id=?", (imdbID,))
            dbResult = self.c.fetchall()
            resultList = []
            for mediaVersionRow in dbResult:
                resultList.append(MediaVersion(mediaVersionRow[1], mediaVersionRow[2], mediaVersionRow[3]))
            return resultList

    def __getMediaConnectionsList(self, imdbID):
        with self.conn:
            self.c.execute("SELECT * FROM media_connections WHERE imdb_id=?", (imdbID,))
            dbResult = self.c.fetchall()
            resultList = []
            for mediaConnectionRow in dbResult:
                resultList.append(MediaConnection(mediaConnectionRow[1], self.__getConnectionTypeNameByConnectionTypeID(mediaConnectionRow[2])))
            return resultList

    def getAllMovieObjects(self):
        resultDict = {}
        with self.conn:
            self.c.execute("SELECT * FROM media")
            dbResult = self.c.fetchall()
            for dbRow in dbResult:
                resultDict[dbRow[0]] = self.__getMovieObjectFromDBRow(dbRow)
        return resultDict
