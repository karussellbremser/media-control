from media import Media
import customconnections
from dbcontrol import DBControl
from dbbackup import DBBackup
from scrapelocal import ScrapeLocal
from scrapeimdboffline import ScrapeIMDbOffline
from scrapeimdbonline import ScrapeIMDbOnline
from scrapemediainfo import ScrapeMediaInfo
from scrapecropping import ScrapeCropping
from croppingcache import CroppingCache
from statistics import Statistics
from exceptions import LocalLibraryError, OfflineDatasetError, MediaInfoError, FFmpegError, CroppingError
from verbosity import printAlways, printDetail, printPerson, printVerbose
import config
import getopt, os, sys, time

def requireMainDBExists():
    """Fail fast, before any real work starts, if the main DB hasn't been created yet -- otherwise
    DBControl's sqlite3.connect() would silently create an empty file at this path, and the first
    real query against it would fail with a confusing "no such table" error instead. Same
    reasoning, and same exception type, as DBBackup.forceBackup's equivalent check. Called both by
    -s/-r's own CLI dispatch (before anything else, including ensureHelperDBFresh's potentially
    slow helper-DB rebuild -- no point doing that work first just to fail on this afterwards) and
    by syncLocal/refreshTitleData themselves (so each still protects its own precondition even if
    called some other way)."""
    if not os.path.isfile(config.DB_PATH):
        raise FileNotFoundError("DB not found at " + config.DB_PATH +
                                 " -- run 'python main.py -c' (or --createdb) to create it first")

def readIDList(path):
    """Reads a user-maintained list of imdb ids, one 'tt#######' per line (blank lines ignored). A
    '#' starts a comment, either on its own line or trailing after an id -- everything from '#'
    onward on a line is discarded before parsing. A missing file is treated as an empty list, since
    these lists are optional."""
    if not os.path.exists(path):
        return set()
    with open(path, "r") as f:
        ids = set()
        for line in f:
            content = line.split("#", 1)[0].strip()
            if content:
                ids.add(int(content[2:]))
        return ids

def printStep(number, description):
    """Prints a step-header line for syncLocal's console output, matching the step numbering in
    syncLocal's own comments. Only ever called once a step is already known to have something to
    do this run -- a run that finds nothing new stays short instead of listing all 15 steps
    unconditionally. Steps 7/8/9/12/15 print their own matching header instead (see
    ScrapeIMDbOnline.__printStepHeader), since each of those is owned by a single method there.
    The fail-fast validations right after step 2 (ignored/wontadd/web-provider checks) and right
    after step 5 (checkTitleBasicsConsistency) have no number of their own -- neither ever has
    anything to print on success, only ever an exception on failure, so a step number for either
    would never correspond to anything appearing in this output. Always printed, regardless of
    config.VERBOSITY -- see verbosity.printAlways."""
    printAlways("\nStep " + str(number) + ": " + description)

def printProgress(index, total, media):
    """Prints a uniform per-title progress line, matching ScrapeIMDbOnline.__printProgress's
    format -- used for step 6's MediaInfo/cropping loop, the one step here that visits multiple
    titles but (unlike steps 7/8/9/12/15) isn't owned by a single ScrapeIMDbOnline method. Printed
    at config.VERBOSITY >= LEVEL_NORMAL -- see verbosity.printDetail."""
    printDetail("  [" + str(index) + "/" + str(total) + "] " + str(media.original_title) + " (" + media.getIDString() + ")")

def syncLocal(mediaDir, coverDir, thumbnailDir):
    printAlways("Starting sync...")

    requireMainDBExists()

    # fail fast, before any real work starts, if the offline dataset helper DB hasn't been built
    # yet -- otherwise this would only surface much later (and far less clearly) the first time
    # something actually queries it, e.g. as a sqlite "no such table" error, sqlite3.connect()
    # having silently created an empty file at this path in the meantime (see
    # ScrapeIMDbOffline.__getCursor)
    if not os.path.isfile(config.IMDB_HELPER_DB_PATH):
        raise OfflineDatasetError("IMDb offline dataset helper DB not found at " + config.IMDB_HELPER_DB_PATH +
                                   " -- run 'python main.py -u' (or --update) to build it first")

    db = DBControl(config.DB_PATH)

    # fixed, complete reference data (see iso_language_enum/iso_country_enum in
    # DBControl.createMediaDB) -- fetched once up front since step 6 (MediaInfo-parsed track
    # languages) and step 7 (IMDb-parsed languages/countries) need it, and unlike knownInterestIDs
    # below there's no per-run mutation or dependency ordering to worry about
    isoLanguageLookup = db.getIsoLanguageLookup()
    isoCountryLookup = db.getIsoCountryLookup()

    # captured before anything else in this run touches the DB (including the ignored/wontadd
    # enforcement right below, which can itself remove a referenced-only medium) -- otherwise the
    # final "Sync complete" summary's before/after comparison would miss whatever that enforcement
    # changed, since both numbers would already reflect its result
    referencedInitial = len(db.getReferencedOnlyMedia())

    db.syncWebProvidersFromConfig(config.WEB_PROVIDERS)

    ignoredIDs = readIDList(config.IGNORED_IDS_PATH)
    wontaddIDs = readIDList(config.WONTADD_IDS_PATH)
    db.syncIgnoredAndWontaddIDs(ignoredIDs, wontaddIDs)
    db.enforceIgnoredAndWontaddIDs()

    # 1. scan local media library
    printStep(1, "scanning local media library")
    scrape = ScrapeLocal(mediaDir)
    mediaDictOriginal = scrape.scrapeLocalComplete()

    # 2. resolve locally-found episodes (season/episode number, from each series' raw .episodes)
    # to their real IMDb episode ids, via the offline title.episode.tsv dataset -- purely local, so
    # this belongs before any scraping too, same as the fail-fast validation right below. Resolved episodes become
    # ordinary top-level entries in mediaDictOriginal, just like movies/series, so every check and
    # sync step from here on already applies to them with no further special-casing.
    localSeries = [m for m in mediaDictOriginal.values() if m.episodes]
    if localSeries:
        printStep(2, "resolving locally-found episodes to IMDb ids")
        offlineForEpisodes = ScrapeIMDbOffline(None, config.IMDB_HELPER_DB_PATH)
        episodesBySeries = offlineForEpisodes.getEpisodesForSeries({series.imdb_id for series in localSeries})

        # unnumbered (S00) episodes already carry their own id from the filename; verify each one
        # in one extra pass rather than trusting it blindly, since getEpisodesForSeries's (season,
        # episode) lookup can't be used for these (IMDb's "unnumbered" key collides across episodes)
        unnumberedCandidates = {le.imdb_id: Media(None, None, le.imdb_id)
                                 for series in localSeries for le in series.episodes if le.imdb_id is not None}
        if unnumberedCandidates:
            offlineForEpisodes.parseTitleEpisode(unnumberedCandidates)

        for series in localSeries:
            seriesEpisodes = episodesBySeries[series.imdb_id]
            for localEpisode in series.episodes:
                if localEpisode.imdb_id is not None:
                    candidate = unnumberedCandidates[localEpisode.imdb_id]
                    if candidate.series_imdb_id != series.imdb_id or candidate.season_number is not None:
                        raise LocalLibraryError("locally-found unnumbered episode " + candidate.getIDString() +
                                                 " in " + localEpisode.subdir + " is not an unnumbered episode of " + series.original_title + " per title.episode.tsv")
                    episode_imdb_id = localEpisode.imdb_id
                else:
                    key = (localEpisode.season_number, localEpisode.episode_number)
                    if key not in seriesEpisodes:
                        raise LocalLibraryError("locally-found episode S" + str(localEpisode.season_number) + "E" + str(localEpisode.episode_number) +
                                                 " of " + series.original_title + " not found in title.episode.tsv")
                    episode_imdb_id = seriesEpisodes[key]
                    # catch IMDb reassigning this exact season/episode slot to a different id since
                    # this local file was last resolved (e.g. a renumbering/correction) -- without
                    # this, the file (still named after the OLD position -- nothing renames it
                    # automatically) would otherwise get silently reattached to whichever id now
                    # claims the slot, misattributing it to the wrong episode. Only reachable for a
                    # locally-owned episode whose stored position still disagrees with the fresh
                    # dataset -- refreshTitleData deliberately leaves that staleness in place rather
                    # than correcting it, specifically so this check still has something to catch
                    conflictingID = db.getLocallyOwnedEpisodeAtPosition(series.imdb_id, localEpisode.season_number, localEpisode.episode_number, episode_imdb_id)
                    if conflictingID is not None:
                        raise LocalLibraryError("local episode file in " + localEpisode.subdir + " resolves to tt" + str(episode_imdb_id).zfill(7) +
                                                 " for S" + str(localEpisode.season_number) + "E" + str(localEpisode.episode_number) + " of " + series.original_title +
                                                 ", but tt" + str(conflictingID).zfill(7) + " is already locally owned at that exact position -- " +
                                                 "IMDb's episode numbering for this series appears to have changed; verify and rename the local file to match if so")
                episodeMedia = Media(None, None, episode_imdb_id)
                episodeMedia.subdir = localEpisode.subdir
                episodeMedia.season_number = localEpisode.season_number
                episodeMedia.episode_number = localEpisode.episode_number
                episodeMedia.series_imdb_id = series.imdb_id
                episodeMedia.mediaVersions = localEpisode.mediaVersions
                episodeMedia.intended_order = localEpisode.intended_order
                # temporary placeholder, same role as a movie/series' locally-parsed original_title:
                # used for progress printing before offline parsing (step 11) unconditionally
                # overwrites it with the real title from title.basics
                episodeMedia.original_title = (series.original_title + " S" + str(episodeMedia.season_number).zfill(2) + "E" + str(episodeMedia.episode_number).zfill(2)
                                               if episodeMedia.season_number is not None else series.original_title + " " + episodeMedia.getIDString())
                mediaDictOriginal[episode_imdb_id] = episodeMedia
            series.episodes = [] # consumed -- resolved episodes now live as their own top-level entries

    # fail-fast local validation, before any scraping starts -- no step number of its own (see
    # printStep's docstring): the ignored/wontadd/web-provider checks below never produce any
    # output on success, only ever an exception on failure
    # - any locally-owned title on the ignored list is always a configuration error (ignored_ids is
    # about whether a title deserves to exist in the DB at all, regardless of type). On wontadd_ids
    # it's only a violation if it's not a series -- wontadd_ids is about local-ownership effort, not
    # DB-worthiness, and for a series specifically it only ever means "no more episodes of this
    # series are planned to be added", not a ban on the series (or any of its episodes) being
    # locally owned -- see DBControl.enforceIgnoredAndWontaddIDs for the fuller reasoning. titleType
    # is already reliably "localSeries" vs "localMovie" at this point, straight from the local scan.
    violating = [m for m in mediaDictOriginal.values()
                 if m.imdb_id in ignoredIDs or (m.imdb_id in wontaddIDs and m.titleType != "localSeries")]
    if violating:
        raise LocalLibraryError("locally-owned media found on the ignored/wontadd list(s): " +
                                 ", ".join(m.original_title + " (" + m.getIDString() + ")" for m in violating))

    # - any locally-owned source referencing an unknown web provider is also a configuration error
    db.checkWebProvidersKnown(mediaDictOriginal)

    # 3. apply local removals, as early as possible -- right after the local scan (and its fail-fast
    # validation) establish the ground truth of what's still locally owned, and before anything else
    # queries the DB for "does X currently exist / is X locally owned". Removals are self-contained
    # (a removed item's connection edges, and any now-orphaned interests/languages/countries/people, are
    # cleaned up within removeSingleMedium itself), so this doesn't need to wait for the rest of the
    # sync to succeed -- "removals applied, nothing added yet" is a perfectly safe, retriable state,
    # same as any other partially-progressed sync. Running it this early instead closes off a whole
    # class of stale-DB-state bugs further down: e.g. without this, a series about to be removed
    # here would still look "already exists" to step 11's parent-series-stub check, which could then
    # skip creating a stub for it -- if that series then legitimately gets removed while a brand-new
    # referenced episode (discovered elsewhere this same run) still points at it, the write in step
    # 13 would hit a foreign-key violation over a series row that no longer exists.
    # Media whose file(s) changed are removed here too, for the exact same reason -- they're then
    # simply rediscovered as newly-added by step 4 below and re-added from scratch like any other
    # title, no special-casing needed past this point. A changed filename set (renamed/added/removed
    # version) is always checked; config.ini's [media_update] auto_update_media only additionally
    # gates the mtime-bump heuristic (see DBControl.determineMediaNeedingUpdate for why that part is
    # opt-in and the filename-set part isn't).
    removedDict = db.determineLocallyRemovedMedia(mediaDictOriginal)
    updatedDict = db.determineMediaNeedingUpdate(mediaDictOriginal, config.MEDIA_AUTO_UPDATE_ENABLED)
    if removedDict or updatedDict:
        printStep(3, "removing " + str(len(removedDict)) + " title(s) no longer locally owned, " +
                  str(len(updatedDict)) + " needing an update")
    removedDict.update(updatedDict)
    db.removeMultipleMedia(removedDict)

    # 4. determine newly added media
    newlyAddedMediaDict = db.determineNewlyAddedMedia(mediaDictOriginal)
    newlyAddedMediaDictOriginal = newlyAddedMediaDict.copy()
    printStep(4, str(len(newlyAddedMediaDict)) + " newly-added title(s) found")

    scrapeimdbonline = ScrapeIMDbOnline(coverDir, thumbnailDir, config.SCRAPE_DELAY, config.SCRAPE_MAX_COUNT, config.CHROME_PROFILE_DIR, config.SCRAPE_HEADLESS, config.SCRAPE_PAGE_LOAD_WAIT, config.SCRAPE_PAGE_LOAD_TIMEOUT, config.SCRAPE_NETWORK_RETRY_MAX_WAIT, config.SCRAPE_NETWORK_RETRY_DELAY)

    # 5. restrict to the configured per-run budget before any scraping starts, bounding both how many
    # new movies/series get added this run and the online main-page/connections scraping below (steps
    # 7+8) that goes with them. A series (together with all of its resolved episodes) counts as a single
    # unit against the cap, so a sync run is never cut off midway through a series -- see
    # restrictToScrapeBudget. Referenced-only stub media (step 10, discovered from these items'
    # connections) fall outside this budget entirely -- they're cheap, offline-dataset-only additions:
    # a stub missing from the offline dataset is discarded outright rather than ever being scraped
    # online (see scrapeimdboffline.py's dataset-illegal handling), so they can never reach step 12's
    # online fallback either. Anything excluded here is simply not "newly added" yet as far as the rest
    # of this run is concerned; it's still missing from the DB afterwards, so it's picked up again on
    # the next sync.
    beforeBudgetCount = len(newlyAddedMediaDict)
    newlyAddedMediaDict = scrapeimdbonline.restrictToScrapeBudget(newlyAddedMediaDict)
    if len(newlyAddedMediaDict) < beforeBudgetCount:
        printStep(5, "restricted to " + str(len(newlyAddedMediaDict)) + " title(s) this run (scrape budget = " +
                  str(config.SCRAPE_MAX_COUNT) + "; " + str(beforeBudgetCount - len(newlyAddedMediaDict)) + " deferred to a later sync)")

    # created here rather than at step 11 (its previous, later spot) so checkTitleBasicsConsistency
    # right below can use it too -- constructing it is free either way (see ScrapeIMDbOffline.__init__:
    # the helper DB connection itself is only opened lazily, on first real query)
    scrapeimdboffline = ScrapeIMDbOffline(scrapeimdbonline, config.IMDB_HELPER_DB_PATH)

    # fail-fast, before any of the expensive per-title work below (steps 6-10) runs: catch a
    # locally-owned title whose folder-parsed start_year (or movie/series/episode category) already
    # disagrees with the offline dataset -- same check step 11's parseTitleFields would eventually
    # raise on anyway, just early enough to not waste this run's MediaInfo/cropping analysis and
    # online scraping on titles that would only get discarded once that check ran. No step number of
    # its own (see printStep's docstring) -- nothing to print on success, only ever an exception on
    # failure.
    scrapeimdboffline.checkTitleBasicsConsistency(newlyAddedMediaDict)

    # 6. run MediaInfo analysis on every file belonging to a title that's both newly added and
    # survived the scrape budget above -- movies' own mediaVersions, plus already-resolved episodes'
    # (from step 2); series themselves and any later-discovered referenced-only stub media have no
    # mediaVersions at all, so nothing extra needs excluding here.
    # Cropping/aspect-ratio detection (ScrapeCropping) runs immediately after, per file, rather than
    # as its own bulk pass -- it reuses this file's just-computed duration/width/height instead of a
    # separate ffmpeg probe, and interleaving keeps repeat reads of the same file close together in
    # time rather than walking the whole file list twice (both MediaInfo and ffmpeg are local-file
    # reads, unlike the online scraping below).
    # Kaleidescape-sourced versions are skipped entirely -- there's no local file to analyze, just an
    # empty .kscape placeholder (see MediaVersion.isKaleidescapeOnly); duration/mediainfo_version/
    # format/width/height etc. stay None until a future online Kaleidescape scraper fills them in.
    # cropping gets a single (0,0,0,0) placeholder row instead, same reasoning as media_versions
    # itself still getting a row -- there's simply nothing to detect yet. The size check guards the
    # one dangerous mismatch: a real, non-empty file whose source was mistakenly declared as kscape
    # would otherwise have its analysis silently skipped rather than flagged (the reverse mismatch --
    # a .kscape-extension file with a non-kscape source -- already can't happen, since ScrapeLocal
    # requires every .kscape file to be empty regardless of source).
    # Unlike everything else in this pipeline, a failure here doesn't abort the whole sync: a missing
    # file (LocalLibraryError, including the kscape-mismatch case above), malformed MediaInfo output
    # (MediaInfoError), a misbehaving ffmpeg (FFmpegError), or an inconclusive cropping result
    # (CroppingError) each only ever affect the one title they came from -- there's no reason a bad
    # file for one title should block every other title in this run. So each is caught, printed as a
    # warning, and that title (all its mediaVersions, not just the one that failed) is dropped from
    # newlyAddedMediaDict rather than written this run. This needs no special handling downstream:
    # a dropped title falls straight into the same "was in the wider newlyAddedMediaDictOriginal
    # snapshot but isn't in the current set anymore" fallback step 10 already has for scrape-budget-
    # excluded titles, and it's naturally retried as newly-added again on the next sync (still
    # missing/still a referenced-only stub in the DB either way) -- self-healing for a transient
    # problem, a recurring warning every run for a persistent one, same as ensureHelperDBFresh's own
    # update-failure handling.
    # If every one of a series' newly-added episodes fails this way, the series itself is dropped
    # too -- otherwise it would still get written as locally-owned (subdir set) with zero episodes,
    # a state nothing else in this codebase can otherwise produce. No extra "is it already locally
    # owned" check needed: determineNewlyAddedMedia already guarantees a series still present in
    # newlyAddedMediaDict at this point isn't -- an already-owned series never enters this dict in
    # the first place (its DB row already has subdir set, so it never looks "newly added"). And no
    # need to track what a series started step 6 with either: restrictToScrapeBudget's own per-
    # series-unit rule guarantees a series never reaches step 6 with only some of its episodes
    # present, so "zero episodes remain" is checkable directly against the current dict.
    mediaWithVersions = [m for m in newlyAddedMediaDict.values() if m.mediaVersions]
    if mediaWithVersions:
        printStep(6, "analyzing local media files with MediaInfo and detecting cropping")
    scrapeMediaInfo = ScrapeMediaInfo(config.MEDIAINFO_PATH, isoLanguageLookup)
    # see CroppingCache: persists auto-detected cropping results across runs (outside myMovieDB.db),
    # since every version of a title gets re-detected here whenever any one of its sibling versions
    # changes -- without this an unchanged file would pay for ffmpeg's cropdetect analysis again for
    # no reason. config.CROPPING_CACHE_ENABLED is the only thing deciding whether this exists at all.
    croppingCache = CroppingCache(config.CROPPING_CACHE_PATH, config.CROPPING_BURST_FRAME_COUNT, config.CROPPING_RUNTIME_PERCENTAGES,
                                   config.CROPPING_CLUSTER_TOLERANCE, config.CROPPING_SYMMETRY_TOLERANCE,
                                   config.CROPPING_MINIMUM_CLUSTER_SIZE, config.CROPPING_WINDOWBOXING_TOLERANCE,
                                   config.CROPPING_MINIMUM_DEVIATION) if config.CROPPING_CACHE_ENABLED else None
    scrapeCropping = ScrapeCropping(config.FFMPEG_PATH, config.CROPPING_BURST_FRAME_COUNT, config.CROPPING_RUNTIME_PERCENTAGES,
                                     config.CROPPING_CLUSTER_TOLERANCE, config.CROPPING_SYMMETRY_TOLERANCE,
                                     config.CROPPING_MINIMUM_CLUSTER_SIZE, config.CROPPING_WINDOWBOXING_TOLERANCE,
                                     config.CROPPING_MINIMUM_DEVIATION, cache=croppingCache)
    excludedIDs = []
    for i, currentMedia in enumerate(mediaWithVersions, 1):
        printProgress(i, len(mediaWithVersions), currentMedia)
        excluded = False
        for mediaVersion in currentMedia.mediaVersions:
            try:
                if mediaVersion.isKaleidescapeOnly():
                    filepath = os.path.join(mediaDir, currentMedia.subdir, mediaVersion.filename)
                    if os.path.isfile(filepath) and os.path.getsize(filepath) > 0:
                        raise LocalLibraryError("Kaleidescape-sourced file is not empty: " + filepath)
                    printDetail("  skipping Kaleidescape-owned file (no local file to analyze): " + filepath)
                    mediaVersion.cropping = [(0, 0, 0, 0)]
                    continue
                scrapeMediaInfo.analyzeMediaVersion(mediaDir, currentMedia.subdir, mediaVersion)
                scrapeCropping.detectCropping(mediaDir, currentMedia.subdir, mediaVersion, currentMedia.imdb_id)
            except (LocalLibraryError, MediaInfoError, FFmpegError, CroppingError) as e:
                printAlways("WARNING: skipping " + str(currentMedia.original_title) + " (" + currentMedia.getIDString() +
                            ") this run -- MediaInfo/cropping analysis failed: " + str(e))
                excluded = True
                break
        # pruning needs this title's processing for this run to be fully complete, which excluded's
        # early break above means it isn't -- skip it rather than risk pruning an entry that's
        # actually still valid (it'll simply be reconsidered next run, same as the rest of an
        # excluded title)
        if excluded:
            excludedIDs.append(currentMedia.imdb_id)
        elif croppingCache is not None:
            croppingCache.pruneUnused(currentMedia.imdb_id)
    for imdb_id in excludedIDs:
        del newlyAddedMediaDict[imdb_id]
    if croppingCache is not None:
        croppingCache.save()

    affectedSeriesIDs = {m.series_imdb_id for m in mediaWithVersions if m.imdb_id in excludedIDs and m.series_imdb_id is not None}
    for series_id in affectedSeriesIDs:
        series = newlyAddedMediaDict.get(series_id)
        if series is not None and not any(m.series_imdb_id == series_id for m in newlyAddedMediaDict.values()):
            printAlways("WARNING: excluding series " + str(series.original_title) + " (" + series.getIDString() +
                        ") this run -- all of its newly-added episodes failed analysis")
            del newlyAddedMediaDict[series_id]

    # 7. scrape main pages of newly added media: download covers if missing, scrape interests/
    # languages/countries. episodes (identified here by series_imdb_id already being set, from step 2)
    # are excluded -- they get none of this: no cover, no interests, no languages/countries, no plot
    # summary. Series do get interests/languages/countries/plot summary here, but scrapeMainPages
    # itself skips the cover download for them -- see its docstring
    moviesAndSeriesDict = {k: v for k, v in newlyAddedMediaDict.items() if v.series_imdb_id is None}
    knownInterestIDs = db.getAllKnownInterestIDs()
    knownIgnoredIDs = db.getAllKnownIgnoredInterestIDs()
    # newly-discovered interests/ignored chips are NOT persisted here -- ensureInterestExists etc.
    # are deferred until just before addMultipleMedia (see below), so an aborted sync can never
    # leave a subgenre registered in the DB without the title that triggered it actually being
    # added. knownInterestIDs/knownIgnoredIDs are mutated in place regardless, so this deferral
    # costs nothing within this run -- a title later in the same loop that hits the same new
    # interest still recognizes it as already known. isoLanguageLookup/isoCountryLookup (fetched up
    # front, see above) need none of this -- both are fixed reference data, not grown as new ones
    # are discovered.
    newInterestRegistrations, newIgnoredRegistrations = scrapeimdbonline.scrapeMainPages(moviesAndSeriesDict, knownInterestIDs, isoLanguageLookup, isoCountryLookup, knownIgnoredIDs)

    # 8. parse media connections
    newlyAddedMediaDict = scrapeimdbonline.parseMediaConnections(newlyAddedMediaDict)

    # 9. scrape full credits (director/writer/actor) for every locally-owned newly-added medium,
    # excluding series themselves -- the inverse of step 7's filter. A series' own director/writer/
    # cast credits are just IMDb's own aggregate rollup of its episodes' credits (verified live: every
    # category scraped here -- director/writer/actor -- is episode-attributable, including
    # series-wide "created by" writer credits, which IMDb repeats on every individual episode's page,
    # not just the first), so storing them again at the series level would be redundant for a fully-
    # owned series, and for a partially-owned one would force scraping (and keeping in sync) the
    # entire series' cast just to catalog the few owned episodes -- not worth it. Movies and episodes
    # still get scraped directly, same as before.
    moviesAndEpisodesDict = {k: v for k, v in newlyAddedMediaDict.items() if v.titleType != "localSeries"}
    knownPersonIDs = db.getAllKnownPersonIDs()
    newPersonRegistrations = scrapeimdbonline.scrapeFullCredits(moviesAndEpisodesDict, knownPersonIDs)

    # 10. add media to dict that are not in local library, but are referenced by local media (per IMDb connection)
    beforeReferencedCount = len(newlyAddedMediaDict)
    newlyAddedMediaDictCopy = newlyAddedMediaDict.copy()
    for x in newlyAddedMediaDictCopy.values():
        for y in x.mediaConnections:
            if y.foreign_imdb_id in ignoredIDs:
                continue
            if y.foreign_imdb_id not in mediaDictOriginal or (y.foreign_imdb_id in newlyAddedMediaDictOriginal and y.foreign_imdb_id not in newlyAddedMediaDictCopy):
                newlyAddedMediaDict[y.foreign_imdb_id] = Media(None, None, y.foreign_imdb_id)
    if len(newlyAddedMediaDict) > beforeReferencedCount:
        printStep(10, str(len(newlyAddedMediaDict) - beforeReferencedCount) + " referenced-only title(s) added from connections")

    # 11. offline parsing; flags locally-owned titles missing from the dataset for online fallback (step 12),
    # discards referenced-only titles missing from the dataset. Also resolves name/birth_year/death_year
    # for every person newly discovered in step 9's credits scrape (see ScrapeIMDbOffline.parsePeople).
    if newlyAddedMediaDict:
        printStep(11, "querying the offline dataset helper DB (ratings, basics, episode resolution, new people)")

    newPeopleDict = {p.imdb_id: p for p in newPersonRegistrations}
    newPeopleDict = scrapeimdboffline.parsePeople(newPeopleDict)

    # a referenced connection target might be an episode rather than a movie/series -- resolve any
    # such id's season/episode/parent series (must run before parseTitleFields, see
    # parseTitleEpisode), then add the parent series too if not already known: series_imdb_id's FK
    # requires the series row to exist, not just nice for display. If the series is itself ignored,
    # drop the episode instead (it can't be added without its series; a locally-owned series being
    # ignored would already have failed the earlier local-scan check, so this can only happen for a
    # referenced-only episode). A series doesn't need a stub if it already has a row in the DB --
    # e.g. a new episode of an already-synced series -- checking newlyAddedMediaDict alone isn't
    # enough, since that only reflects what's newly added *this run*
    scrapeimdboffline.parseTitleEpisode(newlyAddedMediaDict)
    existingIDs = {row[0] for row in db.getAllMediaIDs()}
    for imdb_id, x in list(newlyAddedMediaDict.items()):
        if x.series_imdb_id is None:
            continue
        if x.series_imdb_id in ignoredIDs:
            printDetail("  dropping referenced episode " + x.getIDString() + ": parent series tt" + str(x.series_imdb_id).zfill(7) + " is ignored")
            del newlyAddedMediaDict[imdb_id]
        elif x.series_imdb_id not in newlyAddedMediaDict and x.series_imdb_id not in existingIDs:
            newlyAddedMediaDict[x.series_imdb_id] = Media(None, None, x.series_imdb_id)

    newlyAddedMediaDict = scrapeimdboffline.parseTitleFields(newlyAddedMediaDict)

    # 12. online fallback for locally-owned titles missing from the offline dataset (should happen very
    # infrequently). No cap of its own -- needsOnlineFallback is only ever set for locally-owned media
    # (see ScrapeIMDbOffline's dataset-illegal handling: a referenced-only title missing from the
    # dataset is discarded outright, never flagged), so flaggedMediaDict is already a subset of the
    # step-5-restricted newlyAddedMediaDict and is bounded by the same per-run budget as everything else.
    flaggedMediaDict = {k: v for k, v in newlyAddedMediaDict.items() if v.needsOnlineFallback}
    if len(flaggedMediaDict) > 0:
        scrapeimdbonline.fillMissingBasics(flaggedMediaDict)

        # an episode whose own IMDb page has no release year either (fillMissingBasics tolerates
        # this, see its docstring) still needs *something* written -- media.start_year is NOT NULL --
        # so it's approximated from the offline dataset instead (closest earlier sibling episode,
        # else the series' own start_year; see approximateEpisodeStartYear)
        for x in flaggedMediaDict.values():
            if x.series_imdb_id is not None and x.start_year is None:
                approxYear = scrapeimdboffline.approximateEpisodeStartYear(x.series_imdb_id, x.season_number, x.episode_number)
                printAlways("WARNING: no release year found anywhere for episode " + str(x.original_title) + " (" + x.getIDString() +
                            ") -- approximating start_year as " + str(approxYear))
                x.start_year = approxYear

    # 13. finalize and write newly-added media (plus this run's new credits/people) to the DB
    if newlyAddedMediaDict:
        printStep(13, "finalizing and writing " + str(len(newlyAddedMediaDict)) + " newly-added title(s) to the DB")

    # - print newly-added media that isn't locally owned (referenced-only additions), for visibility
    for x in newlyAddedMediaDict.values():
        if x.subdir == None:
            printDetail("  adding referenced-only: " + x.original_title + " (" + str(x.start_year) + ")")

    # - strip any dangling connection edges before writing. A referenced episode dropped above because
    # its series is ignored (step 11) is the known case: other kept items' mediaConnections can still
    # point at it, and since media_connections.foreign_imdb_id has an FK back to media.imdb_id,
    # inserting such an edge would crash addMultipleMedia. Only prune targets that are neither being
    # added this run nor already in the DB -- an already-existing target's row satisfies the FK
    # regardless of whether this run touches it.
    referencedIDs = {y.foreign_imdb_id for x in newlyAddedMediaDict.values() for y in x.mediaConnections}
    missingIDs = referencedIDs - set(newlyAddedMediaDict.keys())
    if missingIDs:
        existingIDs = {row[0] for row in db.getAllMediaIDs()}
        danglingIDs = missingIDs - existingIDs
        if danglingIDs:
            for x in newlyAddedMediaDict.values():
                x.mediaConnections = [y for y in x.mediaConnections if y.foreign_imdb_id not in danglingIDs]

    # steps 13/14's writes (new people/interests/languages/countries/ignored chips, the newly-added
    # media batch itself, and step 14's episode-catalog-completion stubs) are batched into
    # one atomic commit-or-rollback unit here, rather than each committing independently as
    # soon as it's written -- this closes the exact risk the comments below used to describe
    # as only "minimized": an aborted sync used to be able to leave e.g. a new person
    # registered with no credit ever referencing them, or step 13's write committed with
    # step 14 never completing it and (since the underlying episode is no longer "new" on a
    # later sync) never getting a second chance to. Now either this whole batch commits
    # together, or none of it does -- a rolled-back run is fully retriable next time, same as
    # any other exception elsewhere in this pipeline.
    with db.transaction():
        # - persist newly-discovered people now, right alongside the media whose credits (step 9)
        # reference them -- people rows must exist before addMultipleMedia's credits inserts below (FK).
        # Same reasoning as the interest/ignored-chip registrations right below.
        for person in newPeopleDict.values():
            printPerson("  new person added: " + str(person.name) + " (" + person.getIDString() + ")")
            db._ensurePersonExistsNoCommit(person)

        # - persist newly-discovered interests/ignored chips now, right alongside the media that
        # triggered them -- interest_enum rows must exist before addMultipleMedia's media_interests
        # inserts below (FK). iso_language_enum/iso_country_enum need no equivalent -- both are
        # pre-seeded and complete, see DBControl.createMediaDB.
        for imdb_interest_id, name, description, parent_imdb_interest_id in newInterestRegistrations:
            if parent_imdb_interest_id is None:
                printDetail("  new genre added to interest enum: " + name + " (" + str(imdb_interest_id) + ")")
            else:
                printDetail("  new subgenre added to interest enum: " + name + " (" + str(imdb_interest_id) + "), parent: " + str(parent_imdb_interest_id))
            db._ensureInterestExistsNoCommit(imdb_interest_id, name, description, parent_imdb_interest_id)
        for imdb_interest_id, name, interestType in newIgnoredRegistrations:
            printDetail("  new " + interestType.lower() + " interest ignored: " + name + " (" + str(imdb_interest_id) + ")")
            db._ensureIgnoredInterestExistsNoCommit(imdb_interest_id)

        # - the write itself
        db._addMultipleMediaNoCommit(newlyAddedMediaDict)

        # 14. for every series that had something new happen to it this run (the series itself newly
        # added, or at least one of its locally-resolved episodes newly added -- checked against
        # newlyAddedMediaDict, the FINAL set actually written by step 13 just above, not
        # newlyAddedMediaDictOriginal's wider pre-budget snapshot from step 4: a locally-scanned
        # episode that the scrape budget deferred to a later sync hasn't actually changed anything
        # for its series yet, so it shouldn't trigger this early either -- it'll correctly trigger
        # catalog completion once it's actually written, on whichever sync that ends up being),
        # make sure its FULL episode catalog (per title.episode.tsv) is represented in the DB
        # now -- not just the locally-owned episodes resolved in step 2. Every other episode of these
        # series gets a referenced-only stub instead, so the DB always reflects which episodes exist for
        # a partially-owned series and which of those are actually owned, without waiting for a
        # --refresh. Skipping series with nothing new matters: without it, a series with e.g. an unaired
        # special or an announced-but-unscheduled episode (missing/incomplete data, discarded rather
        # than added -- see __insertTitleBasics's "\N" handling) would re-derive and re-attempt that
        # same discard, including its online isInDevelopment() check, on every single sync that happens
        # to touch the series at all, even when nothing actually changed. Purely offline-dataset-driven
        # otherwise, like refreshTitleData's equivalent completeness check -- these stubs never go
        # through scrapeMainPages/parseMediaConnections/scrapeFullCredits, so a large series doesn't turn
        # into a large scraping bill just because a few of its episodes were added locally. This has to
        # run down here, strictly after step 13's write: a series' own row must already exist before any
        # of its episode stubs can satisfy the series_imdb_id FK, so readySeries below checks the DB
        # directly for genuine local ownership (subdir NOT NULL) rather than assuming every touched
        # series made it in as owned -- it might not have (e.g. excluded by the scrape budget in step
        # 5), and whichever series didn't just gets this treatment on a later sync instead, once it's
        # actually locally owned. Merely having *a* row isn't enough of a test here: a series referenced
        # by a connection from some other budget-surviving medium can end up with a bare referenced-only
        # stub row of its own mid-sync (see step 10's connection-target fallback) despite being locally
        # owned -- that stub must not be mistaken for "ready", or this series' full episode catalog
        # would get completed a sync early, while its own row still (temporarily) claims it's unowned.
        if localSeries:
            localEpisodeIDsBySeriesID = {}
            for m in mediaDictOriginal.values():
                if m.series_imdb_id is not None:
                    localEpisodeIDsBySeriesID.setdefault(m.series_imdb_id, []).append(m.imdb_id)
            touchedSeries = [series for series in localSeries
                              if series.imdb_id in newlyAddedMediaDict
                              or any(ep_id in newlyAddedMediaDict for ep_id in localEpisodeIDsBySeriesID.get(series.imdb_id, []))]

            existingIDs = {row[0] for row in db._getAllMediaIDsNoCommit()}
            locallyOwnedIDs = {row[0] for row in db._getAllLocallyOwnedMediaIDsNoCommit()}
            readySeries = [series for series in touchedSeries if series.imdb_id in locallyOwnedIDs]
            if readySeries:
                printStep(14, "completing episode catalogs for " + str(len(readySeries)) + " series touched this run")
                offlineForCompleteness = ScrapeIMDbOffline(scrapeimdbonline, config.IMDB_HELPER_DB_PATH)
                fullEpisodeLists = offlineForCompleteness.getFullEpisodeListForSeries({series.imdb_id for series in readySeries})
                newEpisodeStubs = {}
                for series in readySeries:
                    for season, episode, episode_imdb_id in fullEpisodeLists[series.imdb_id]:
                        if episode_imdb_id in ignoredIDs:
                            continue
                        if episode_imdb_id not in newlyAddedMediaDict and episode_imdb_id not in existingIDs and episode_imdb_id not in newEpisodeStubs:
                            stub = Media(None, None, episode_imdb_id)
                            stub.series_imdb_id = series.imdb_id
                            stub.season_number = season
                            stub.episode_number = episode
                            newEpisodeStubs[episode_imdb_id] = stub
                if newEpisodeStubs:
                    newEpisodeStubs = offlineForCompleteness.parseTitleFields(newEpisodeStubs)
                    seriesTitlesByID = {series.imdb_id: series.original_title for series in readySeries}
                    for episode_imdb_id, stub in newEpisodeStubs.items():
                        # verbosity level 2, not 1: this can print dozens of lines per series for a
                        # large catalog completion, same reasoning as printPerson. Deliberately
                        # never mentions the episode's own title -- only the parent series and its
                        # season/episode position (or, for an unnumbered episode, its id, since
                        # there's no season/episode position to show instead)
                        episodeLabel = ("S" + str(stub.season_number).zfill(2) + "E" + str(stub.episode_number).zfill(2)
                                        if stub.season_number is not None else stub.getIDString())
                        printVerbose("  cataloging episode " + episodeLabel + " of " + str(seriesTitlesByID.get(stub.series_imdb_id, stub.series_imdb_id)))
                    db._addMultipleMediaNoCommit(newEpisodeStubs)

    # 15. recover covers missing for any currently-owned movie (e.g. deleted between syncs), then generate
    # thumbnails. Series covers are deliberately never fetched automatically -- IMDb only offers the latest
    # season's cover as a series' "main" image, which isn't what should represent the whole series locally;
    # a missing series cover is instead flagged below, for the user to source and place manually. A movie's
    # cover is only ever fetched automatically if it has a primary language (the first language listed on
    # IMDb) AND that language is English -- movies with any other primary language, or none listed at all,
    # get the same manual-only treatment as series (see ScrapeIMDbOnline.scrapeMainPages).
    # Both the sweep below and the warning loop after it query the DB directly for their categories
    # (getLocallyOwnedMovieIDsWithEnglishPrimaryLanguage / ...WithoutEnglishPrimaryLanguage /
    # getLocallyOwnedSeriesIDs) rather than trusting a freshly-rescanned Media object's in-memory state,
    # which only knows a title's type/languages for something newly processed this run. That matters for
    # a title merely discovered on disk this run but never actually added (e.g. excluded by the scrape
    # budget, or failed MediaInfo): it has had no language scraped yet, so the sweep can't know it's
    # English and leaves it alone -- its cover comes from step 7 once it's actually scraped, not before.
    # And the warning loop would otherwise, on a first sync of a large library, warn about covers for
    # thousands of titles not even in the DB yet, repeating every subsequent sync until each one is
    # finally processed.
    englishPrimaryMovieIDs = db.getLocallyOwnedMovieIDsWithEnglishPrimaryLanguage()
    noEnglishPrimaryMovieIDs = db.getLocallyOwnedMovieIDsWithoutEnglishPrimaryLanguage()
    if config.SCRAPE_RECOVER_MISSING_COVERS:
        moviesOnlyDict = {k: v for k, v in mediaDictOriginal.items() if k in englishPrimaryMovieIDs}
        scrapeimdbonline.downloadCovers(moviesOnlyDict)
    scrapeimdbonline.generateThumbnails()

    locallyOwnedSeriesIDs = db.getLocallyOwnedSeriesIDs()
    for v in mediaDictOriginal.values():
        if v.series_imdb_id is None and (v.imdb_id in locallyOwnedSeriesIDs or v.imdb_id in noEnglishPrimaryMovieIDs):
            coverPath = os.path.join(coverDir, v.getIDString() + ".jpg")
            if not os.path.isfile(coverPath):
                kind = "series" if v.imdb_id in locallyOwnedSeriesIDs else "movie without an English primary language"
                printAlways("WARNING: no cover found for locally-owned " + kind + " " + str(v.original_title) + " (" + v.getIDString() + ") -- covers for series and for movies without an English primary language must be added manually")

    scrapeimdbonline.close()

    # 16. reconcile custom_connections.txt -- see customconnections.py and reconcileCustomConnections's
    # own docstring. Its own transaction, run last, so it always sees the fully up-to-date post-sync
    # state (including any stubs/removals from everything above).
    reconcileCustomConnections(db, scrapeimdboffline, ignoredIDs)

    referencedOnlyMedia = db.getReferencedOnlyMedia()
    printAlways("\nSync complete. To-be-added media: " + str(len(referencedOnlyMedia)) + " total (was " + str(referencedInitial) + " before this run).")

def reconcileCustomConnections(db, scrapeimdboffline, ignoredIDs):
    """Reconciles config.CUSTOM_CONNECTIONS_PATH (see customconnections.py) against the DB: removes
    any is_custom=1 media_connections row that's no longer declared in the file or no longer valid,
    then adds whatever newly-valid facts are eligible this run (source locally owned), creating
    referenced-only stubs for not-yet-known targets via the same offline-resolution pipeline steps
    10/11 use. Never touches an is_custom=0 (IMDb-sourced) row.

    Every problem with an individual fact -- a malformed line, an ignored target, a contradiction --
    is a warning, never a raise: the file is fully re-read and re-expanded fresh every run, so a
    fixed line (or a fact that becomes valid/invalid purely because of unrelated IMDb changes) is
    simply picked up correctly next time regardless. This also means every currently-stored custom
    connection gets explicitly re-validated every run, not just ones the file itself still mentions
    unchanged -- closing the gap where an unrelated IMDb change could otherwise silently leave a
    stale custom fact in place."""

    def warn(message):
        printAlways("WARNING: custom connection " + message)

    def label(imdb_id, foreign_imdb_id, connection_type_name):
        return "tt" + str(imdb_id).zfill(7) + " " + connection_type_name + " tt" + str(foreign_imdb_id).zfill(7)

    facts = customconnections.parseFile(config.CUSTOM_CONNECTIONS_PATH, warn)

    with db.transaction():
        existingCustom = db._getAllCustomConnectionFactsNoCommit()
        if not facts and not existingCustom:
            return
        printStep(16, "reconciling custom connections")

        # validation graphs, seeded from everything currently on record (real + custom alike) --
        # accept() below grows them in place as this pass accepts more facts, so a later fact in the
        # same pass is checked against everything accepted so far too
        followsGraph = customconnections.buildFollowsGraph(db._getConnectionEdgesByTypeNoCommit(["follows", "followed_by"]))
        pairEdges = {family: db._getConnectionEdgesByTypeNoCommit(list(family)) for family in customconnections.PAIR_FAMILIES}

        def pairFamilyFor(connection_type_name):
            for family in customconnections.PAIR_FAMILIES:
                if connection_type_name in family:
                    return family
            return None

        def isStillValid(imdb_id, foreign_imdb_id, connection_type_name):
            if imdb_id in ignoredIDs or foreign_imdb_id in ignoredIDs:
                warn(label(imdb_id, foreign_imdb_id, connection_type_name) + ": one side is on the ignored list")
                return False
            if connection_type_name in customconnections.CHAIN_TYPES:
                earlier, later = customconnections.normalizeFollowsEdge(imdb_id, foreign_imdb_id, connection_type_name)
                if customconnections.wouldCreateFollowsCycle(followsGraph, earlier, later):
                    warn(label(imdb_id, foreign_imdb_id, connection_type_name) + ": contradicts an already-established chronological order")
                    return False
            else:
                family = pairFamilyFor(connection_type_name)
                if family is not None and customconnections.wouldContradictPairEdge(pairEdges[family], imdb_id, foreign_imdb_id, connection_type_name):
                    warn(label(imdb_id, foreign_imdb_id, connection_type_name) + ": contradicts an already-established " + connection_type_name + " direction")
                    return False
            return True

        def accept(imdb_id, foreign_imdb_id, connection_type_name):
            if connection_type_name in customconnections.CHAIN_TYPES:
                earlier, later = customconnections.normalizeFollowsEdge(imdb_id, foreign_imdb_id, connection_type_name)
                customconnections.addFollowsEdge(followsGraph, earlier, later)
            else:
                family = pairFamilyFor(connection_type_name)
                if family is not None:
                    pairEdges[family].add((imdb_id, foreign_imdb_id, connection_type_name))

        # 1. re-validate every currently-stored custom connection; remove whatever is no longer
        # declared in the file, or no longer valid (see the docstring above for why this always runs,
        # not just when the file itself changed)
        for imdb_id, foreign_imdb_id, connection_type_name in existingCustom:
            stillDeclared = (imdb_id, foreign_imdb_id, connection_type_name) in facts
            if stillDeclared and isStillValid(imdb_id, foreign_imdb_id, connection_type_name):
                accept(imdb_id, foreign_imdb_id, connection_type_name)
                continue
            if not stillDeclared:
                printDetail("  removing custom connection " + label(imdb_id, foreign_imdb_id, connection_type_name) +
                            " (no longer in " + config.CUSTOM_CONNECTIONS_PATH + ")")
            db._removeCustomConnectionNoCommit(imdb_id, foreign_imdb_id, connection_type_name)

        # 2. determine which not-yet-stored facts are eligible this run -- source locally owned
        # (the activation rule: each directional row activates independently), not already present as
        # real IMDb data, and valid
        eligible = []
        for imdb_id, foreign_imdb_id, connection_type_name in facts:
            if (imdb_id, foreign_imdb_id, connection_type_name) in existingCustom:
                continue # handled in step 1
            if not db._isLocallyOwnedNoCommit(imdb_id):
                continue # not yet relevant -- retried next run
            if db._connectionExistsNoCommit(imdb_id, foreign_imdb_id, connection_type_name):
                warn(label(imdb_id, foreign_imdb_id, connection_type_name) + ": already exists as real IMDb data")
                continue
            if not isStillValid(imdb_id, foreign_imdb_id, connection_type_name):
                continue
            eligible.append((imdb_id, foreign_imdb_id, connection_type_name))
            accept(imdb_id, foreign_imdb_id, connection_type_name) # so a later fact this same pass sees it too

        # 3. resolve referenced-only stubs for any eligible fact's not-yet-existing target -- the
        # exact same offline-resolution sequence as main.py's own step 10/11 (parseTitleEpisode's
        # series resolution, then parseTitleFields with its illegal-discard cascade -- see
        # scrapeimdboffline.py's __applyTitles for why a discarded target's dependent facts simply
        # never reach step 4 below, rather than needing special handling here)
        newStubsDict = {}
        for imdb_id, foreign_imdb_id, connection_type_name in eligible:
            if not db._mediaExistsNoCommit(foreign_imdb_id) and foreign_imdb_id not in newStubsDict:
                newStubsDict[foreign_imdb_id] = Media(None, None, foreign_imdb_id)

        if newStubsDict:
            scrapeimdboffline.parseTitleEpisode(newStubsDict)
            existingIDs = {row[0] for row in db._getAllMediaIDsNoCommit()}
            for imdb_id, x in list(newStubsDict.items()):
                if x.series_imdb_id is None:
                    continue
                if x.series_imdb_id in ignoredIDs:
                    del newStubsDict[imdb_id]
                elif x.series_imdb_id not in newStubsDict and x.series_imdb_id not in existingIDs:
                    newStubsDict[x.series_imdb_id] = Media(None, None, x.series_imdb_id)
            newStubsDict = scrapeimdboffline.parseTitleFields(newStubsDict)
            for imdb_id, stub in newStubsDict.items():
                printDetail("  new referenced-only title from custom connection: " + str(stub.primary_title) + " (" + stub.getIDString() + ")")
            db._addMultipleMediaNoCommit(newStubsDict)

        # 4. finally add the custom connection rows themselves -- only for facts whose target now
        # actually exists (pre-existing, or just resolved above; one discarded as illegal, or whose
        # series was ignored, simply stays not-yet-relevant and is retried next run)
        for imdb_id, foreign_imdb_id, connection_type_name in eligible:
            if not db._mediaExistsNoCommit(foreign_imdb_id):
                continue
            printDetail("  adding custom connection " + label(imdb_id, foreign_imdb_id, connection_type_name))
            db._addCustomConnectionNoCommit(imdb_id, foreign_imdb_id, connection_type_name)

def refreshTitleData():
    # fail fast, before any real work starts. requireMainDBExists() raises FileNotFoundError -- a
    # caller may want to treat that case as an expected, silently-skippable no-op instead of letting
    # it propagate, see -u's auto-refresh call site, which does exactly that (a missing main DB just
    # means there's nothing local to refresh yet, not a usage error -- unlike a direct -r, which is
    # always loud here).
    requireMainDBExists()
    if not os.path.isfile(config.IMDB_HELPER_DB_PATH):
        raise OfflineDatasetError("IMDb offline dataset helper DB not found at " + config.IMDB_HELPER_DB_PATH +
                                   " -- run 'python main.py -u' (or --update) to build it first")

    printAlways("Refreshing data...")
    db = DBControl(config.DB_PATH)
    ignoredIDs = readIDList(config.IGNORED_IDS_PATH)

    mediaDict = db.getAllMovieObjects()

    offline = ScrapeIMDbOffline(ScrapeIMDbOnline(config.COVERS_DIR, config.COVERS_SMALL_DIR, config.SCRAPE_DELAY, config.SCRAPE_MAX_COUNT, config.CHROME_PROFILE_DIR, config.SCRAPE_HEADLESS, config.SCRAPE_PAGE_LOAD_WAIT, config.SCRAPE_PAGE_LOAD_TIMEOUT, config.SCRAPE_NETWORK_RETRY_MAX_WAIT, config.SCRAPE_NETWORK_RETRY_DELAY), config.IMDB_HELPER_DB_PATH)
    mediaDict = offline.refreshTitleFields(mediaDict)

    db.refreshRatings(mediaDict)
    db.refreshTitleBasics(mediaDict)

    peopleDict = db.getAllPersonObjects()
    peopleDict = offline.refreshPeople(peopleDict)
    db.refreshPeople(peopleDict)

    # discover new episodes / detect vanished ones for every currently-owned series. New episodes
    # are added as referenced-only stubs, purely offline-dataset driven -- except for one conditional
    # online check: a new episode with no vote count yet in the offline ratings dataset triggers a
    # live isInDevelopment() check (via parseTitleFields) to tell a real upcoming episode apart from
    # an IMDb placeholder, same as the equivalent sync-side check documented at step 14 above. A
    # vanished, locally-owned episode is an error (see removeVanishedEpisode's docstring for the
    # referenced-only case).
    ownedSeries = [m for m in mediaDict.values() if m.subdir is not None and m.titleType in Media.seriesTitleTypes]
    if ownedSeries:
        fullEpisodeLists = offline.getFullEpisodeListForSeries({s.imdb_id for s in ownedSeries})

        newEpisodeStubs = {}
        for series in ownedSeries:
            for season, episode, episode_imdb_id in fullEpisodeLists[series.imdb_id]:
                if episode_imdb_id in ignoredIDs:
                    continue
                if episode_imdb_id not in mediaDict and episode_imdb_id not in newEpisodeStubs:
                    stub = Media(None, None, episode_imdb_id)
                    stub.series_imdb_id = series.imdb_id
                    stub.season_number = season
                    stub.episode_number = episode
                    newEpisodeStubs[episode_imdb_id] = stub
        if newEpisodeStubs:
            offline.parseTitleFields(newEpisodeStubs)
            for episode_imdb_id, stub in newEpisodeStubs.items():
                printDetail("New episode discovered: " + str(stub.original_title) + " (" + stub.getIDString() + ") of " + str(mediaDict[stub.series_imdb_id].original_title if stub.series_imdb_id in mediaDict else stub.series_imdb_id))
            db.addMultipleMedia(newEpisodeStubs)
            mediaDict.update(newEpisodeStubs)

        for series in ownedSeries:
            currentEpisodeIDs = {m.imdb_id for m in mediaDict.values() if m.series_imdb_id == series.imdb_id}
            freshPositionByID = {episode_imdb_id: (season, episode) for (season, episode, episode_imdb_id) in fullEpisodeLists[series.imdb_id]}
            freshEpisodeIDs = set(freshPositionByID)

            for vanished_id in currentEpisodeIDs - freshEpisodeIDs:
                episodeMedia = mediaDict[vanished_id]
                if episodeMedia.subdir is not None:
                    raise OfflineDatasetError("locally-owned episode " + episodeMedia.getIDString() + " of " +
                                               str(series.original_title) + " is no longer listed in title.episode.tsv")
                db.removeVanishedEpisode(episodeMedia)

            # a still-listed episode's season/episode can still have changed (IMDb renumbering/
            # correction) -- update it here rather than leaving it stale indefinitely, since nothing
            # else ever revisits an already-known episode's position (see getFullEpisodeListForSeries's
            # docstring). A referenced-only stub is pure display data, so it's corrected outright. A
            # locally-owned episode's physical file is named after the OLD position and never renamed
            # automatically -- its stored position is deliberately left AS-IS (only warned about, not
            # corrected) so it keeps disagreeing with the local file's parsed position until the file
            # is actually renamed; that staleness is what lets main.py step 2's own check (see
            # DBControl.getLocallyOwnedEpisodeAtPosition) catch a future sync silently reattaching the
            # unrenamed file to whatever now claims the old slot instead -- "correcting" it here would
            # erase that tripwire before step 2 ever got a chance to use it.
            renumberedEpisodes = {}
            for stillPresentID in currentEpisodeIDs & freshEpisodeIDs:
                episodeMedia = mediaDict[stillPresentID]
                freshSeason, freshEpisode = freshPositionByID[stillPresentID]
                if (episodeMedia.season_number, episodeMedia.episode_number) == (freshSeason, freshEpisode):
                    continue

                oldLabel = ("S" + str(episodeMedia.season_number).zfill(2) + "E" + str(episodeMedia.episode_number).zfill(2)
                            if episodeMedia.season_number is not None else episodeMedia.getIDString())
                newLabel = ("S" + str(freshSeason).zfill(2) + "E" + str(freshEpisode).zfill(2)
                            if freshSeason is not None else episodeMedia.getIDString())
                if episodeMedia.subdir is not None:
                    printAlways("WARNING: locally-owned episode " + episodeMedia.getIDString() + " of " + str(series.original_title) +
                                " moved from " + oldLabel + " to " + newLabel + " per the latest offline dataset -- " +
                                "rename the local file in " + str(episodeMedia.subdir) + " to match, or a future sync " +
                                "may misattribute it to whatever now claims " + oldLabel)
                    continue # deliberately not updated -- see comment above

                printDetail("  episode " + episodeMedia.getIDString() + " of " + str(series.original_title) +
                            " renumbered from " + oldLabel + " to " + newLabel)
                episodeMedia.season_number = freshSeason
                episodeMedia.episode_number = freshEpisode
                renumberedEpisodes[stillPresentID] = episodeMedia

            if renumberedEpisodes:
                db.refreshEpisodeNumbering(renumberedEpisodes)

def ensureHelperDBFresh(runAutoRefresh):
    """If config.HELPER_DB_AUTO_UPDATE_ENABLED and the IMDb offline dataset helper DB is either
    missing or older than config.HELPER_DB_UPDATE_FREQUENCY_DAYS, rebuilds it automatically before
    the caller's sync/refresh proceeds. When auto-update is disabled, this is a complete no-op --
    a missing helper DB still surfaces via syncLocal's own fail-fast check (or whatever
    ScrapeIMDbOffline itself raises, for -r), and an existing-but-stale one is silently tolerated,
    exactly as today.

    Any failure during the update itself is printed as a warning and swallowed, same reasoning as
    DBBackup.ensureBackup: a failed download isn't a correctness problem for this run -- if the
    helper DB was merely stale, the run proceeds with what's already there, same as it would with
    auto-update disabled entirely; if it was missing, the caller's own existing fail-fast handling
    still catches that afterward with its normal, clearer message.

    If the update actually ran and config.HELPER_DB_AUTO_REFRESH_ENABLED, also runs
    refreshTitleData() -- unless runAutoRefresh is False, which the -r caller passes since it's
    about to run its own refresh right after regardless, making a second one here pure waste.
    Unlike the update itself, a refresh triggered here is NOT wrapped in a try/except: it's capable
    of raising a genuine data-consistency finding (e.g. a locally-owned episode vanishing from
    title.episode.tsv), not just an infrastructure hiccup, so it propagates and aborts the run
    exactly like a manually-invoked -r always does."""
    if not config.HELPER_DB_AUTO_UPDATE_ENABLED:
        return

    exists = os.path.isfile(config.IMDB_HELPER_DB_PATH)
    if exists:
        ageDays = (time.time() - os.path.getmtime(config.IMDB_HELPER_DB_PATH)) / 86400
        due = ageDays >= config.HELPER_DB_UPDATE_FREQUENCY_DAYS
    else:
        due = True
    if not due:
        return

    try:
        printAlways("IMDb offline dataset helper DB is " +
              ("missing" if not exists else "over " + str(config.HELPER_DB_UPDATE_FREQUENCY_DAYS) + " days old") +
              " -- rebuilding automatically...")
        ScrapeIMDbOffline(ScrapeIMDbOnline(config.COVERS_DIR, config.COVERS_SMALL_DIR, config.SCRAPE_DELAY, config.SCRAPE_MAX_COUNT, config.CHROME_PROFILE_DIR, config.SCRAPE_HEADLESS, config.SCRAPE_PAGE_LOAD_WAIT, config.SCRAPE_PAGE_LOAD_TIMEOUT, config.SCRAPE_NETWORK_RETRY_MAX_WAIT, config.SCRAPE_NETWORK_RETRY_DELAY), config.IMDB_HELPER_DB_PATH).updateIMDbOfflineDB()
    except Exception as e:
        printAlways("WARNING: automatic helper DB update failed: " + str(e))
        return

    if runAutoRefresh and config.HELPER_DB_AUTO_REFRESH_ENABLED:
        printAlways("Auto-refresh enabled -- refreshing all known media against the freshly-updated helper DB...")
        refreshTitleData()

args = sys.argv[1:]
options = "hcsturbm:"
long_options = ["help", "createdb", "sync", "stats", "update", "refresh", "backup", "max-count="]

try:
    arguments, values = getopt.getopt(args, options, long_options)

    # -m/--max-count overrides config.ini's [scraping] max_count for this run only, so it has to be
    # applied before any of the flags below run -- a separate pass first, rather than handling it
    # inline in the dispatch loop, so it takes effect regardless of where on the command line it's
    # given relative to -s/-u/-r (e.g. "-m 5 -s" and "-s -m 5" behave identically). config.SCRAPE_MAX_COUNT
    # is simply reassigned on the module -- every function below already reads it that way (there's
    # no config object passed around), so nothing else needs to change to pick this up.
    for currentArg, currentVal in arguments:
        if currentArg in ("-m", "--max-count"):
            try:
                maxCountOverride = int(currentVal)
            except ValueError:
                raise getopt.error("--max-count requires an integer, got " + repr(currentVal))
            if maxCountOverride < 0:
                raise getopt.error("--max-count must not be negative, got " + str(maxCountOverride))
            config.SCRAPE_MAX_COUNT = maxCountOverride

    for currentArg, currentVal in arguments:
        if currentArg in ("-h", "--help"):
            print("Usage:\n-h | --help: Show this help.\n-c | --createdb: Create a new, empty database at the configured db_path.\n-s | --sync: Perform a sync between media folder and database.\n-t | --stats: Show statistics about media collection.\n-u | --update: Rebuild the IMDb offline dataset helper DB.\n-r | --refresh: Refresh ratings, basic title data, each owned series' episode list, and known people, for all known media from the IMDb offline dataset helper DB.\n-b | --backup: Immediately create a DB backup, regardless of how recent the last one is (-s and -r also create one automatically once the last backup is old enough -- see config.ini's [backup] section, auto_backup).\n-m N | --max-count N: Override config.ini's [scraping] max_count for this run only (0 = unlimited). Only -s's per-run scrape budget and cover-backfill sweep actually consult it today; harmless to pass alongside -u/-r as well.")
        elif currentArg in ("-m", "--max-count"):
            pass # already applied above, before this loop started
        elif currentArg in ("-c", "--createdb"):
            DBControl(config.DB_PATH).createMediaDB()
        elif currentArg in ("-s", "--sync"):
            requireMainDBExists() # before anything else -- no point running ensureHelperDBFresh's
                                   # potentially slow rebuild only to fail on this afterwards
            if config.BACKUP_AUTO_ENABLED:
                DBBackup(config.DB_PATH, config.BACKUP_DIR, config.BACKUP_MAX_COUNT).ensureBackup(config.BACKUP_FREQUENCY_DAYS)
            ensureHelperDBFresh(runAutoRefresh=True)
            syncLocal(config.MEDIA_DIR, config.COVERS_DIR, config.COVERS_SMALL_DIR)
        elif currentArg in ("-t", "--stats"):
            requireMainDBExists()
            stat = Statistics(DBControl(config.DB_PATH))
            stat.printYearlyAverages()
            stat.analyzeMediaConnections()
        elif currentArg in ("-u", "--update"):
            ScrapeIMDbOffline(ScrapeIMDbOnline(config.COVERS_DIR, config.COVERS_SMALL_DIR, config.SCRAPE_DELAY, config.SCRAPE_MAX_COUNT, config.CHROME_PROFILE_DIR, config.SCRAPE_HEADLESS, config.SCRAPE_PAGE_LOAD_WAIT, config.SCRAPE_PAGE_LOAD_TIMEOUT, config.SCRAPE_NETWORK_RETRY_MAX_WAIT, config.SCRAPE_NETWORK_RETRY_DELAY), config.IMDB_HELPER_DB_PATH).updateIMDbOfflineDB()
            if config.HELPER_DB_AUTO_REFRESH_ENABLED:
                try:
                    refreshTitleData()
                except FileNotFoundError:
                    # no main DB yet (e.g. -u run before ever running -c) -- -u's own job is done
                    # regardless, and auto-refresh is just an optional follow-on with nothing to do
                    # yet, not a usage error worth surfacing; unlike a direct -r, which always raises
                    # this loudly (see refreshTitleData's own check)
                    pass
        elif currentArg in ("-r", "--refresh"):
            requireMainDBExists() # before anything else -- same reasoning as -s above
            if config.BACKUP_AUTO_ENABLED:
                DBBackup(config.DB_PATH, config.BACKUP_DIR, config.BACKUP_MAX_COUNT).ensureBackup(config.BACKUP_FREQUENCY_DAYS)
            ensureHelperDBFresh(runAutoRefresh=False)
            refreshTitleData()
        elif currentArg in ("-b", "--backup"):
            DBBackup(config.DB_PATH, config.BACKUP_DIR, config.BACKUP_MAX_COUNT).forceBackup()
except getopt.error as err:
    print(str(err))
except KeyboardInterrupt:
    # clean message instead of a raw traceback -- actual cleanup (closing any still-open browser)
    # happens regardless, via ScrapeIMDbOnline's atexit-registered safety net, not anything here
    print("\nInterrupted.")
    sys.exit(130)