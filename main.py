from media import Media
from dbcontrol import DBControl
from scrapelocal import ScrapeLocal
from scrapeimdboffline import ScrapeIMDbOffline
from scrapeimdbonline import ScrapeIMDbOnline
from statistics import Statistics
from exceptions import LocalLibraryError, OfflineDatasetError
import config
import getopt, os, sys

def readIDList(path):
    """Reads a user-maintained list of imdb ids, one 'tt#######' per line (blank lines ignored).
    A missing file is treated as an empty list, since these lists are optional."""
    if not os.path.exists(path):
        return set()
    with open(path, "r") as f:
        return {int(line.strip()[2:]) for line in f if line.strip()}

def syncLocal(mediaDir, coverDir, thumbnailDir, webdriverPath):
    db = DBControl(config.DB_PATH)

    db.syncWebProvidersFromConfig(config.WEB_PROVIDERS)

    ignoredIDs = readIDList(config.IGNORED_IDS_PATH)
    wontaddIDs = readIDList(config.WONTADD_IDS_PATH)
    db.syncIgnoredAndWontaddIDs(ignoredIDs, wontaddIDs)
    db.enforceIgnoredAndWontaddIDs()

    referencedInitial = len(db.getReferencedOnlyMedia())

    # 1. scan local media library
    scrape = ScrapeLocal(mediaDir)
    mediaDictOriginal = scrape.scrapeLocalComplete()

    # 1b. resolve locally-found episodes (season/episode number, from each series' raw .episodes)
    # to their real IMDb episode ids, via the offline title.episode.tsv dataset -- purely local, so
    # this belongs before any scraping too, same as the checks below. Resolved episodes become
    # ordinary top-level entries in mediaDictOriginal, just like movies/series, so every check and
    # sync step from here on already applies to them with no further special-casing.
    localSeries = [m for m in mediaDictOriginal.values() if m.episodes]
    if localSeries:
        offlineForEpisodes = ScrapeIMDbOffline(None, config.IMDB_DATASETS_DIR)
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
                                                 " in " + localEpisode.subdir + " is not an unnumbered episode of " + series.originalTitle + " per title.episode.tsv")
                    episode_imdb_id = localEpisode.imdb_id
                else:
                    key = (localEpisode.season_number, localEpisode.episode_number)
                    if key not in seriesEpisodes:
                        raise LocalLibraryError("locally-found episode S" + str(localEpisode.season_number) + "E" + str(localEpisode.episode_number) +
                                                 " of " + series.originalTitle + " not found in title.episode.tsv")
                    episode_imdb_id = seriesEpisodes[key]
                episodeMedia = Media(None, None, episode_imdb_id)
                episodeMedia.subdir = localEpisode.subdir
                episodeMedia.season_number = localEpisode.season_number
                episodeMedia.episode_number = localEpisode.episode_number
                episodeMedia.series_imdb_id = series.imdb_id
                episodeMedia.mediaVersions = localEpisode.mediaVersions
                episodeMedia.intended_order = localEpisode.intended_order
                # temporary placeholder, same role as a movie/series' locally-parsed originalTitle:
                # used for progress printing before offline parsing (step 6) unconditionally
                # overwrites it with the real title from title.basics
                episodeMedia.originalTitle = (series.originalTitle + " S" + str(episodeMedia.season_number).zfill(2) + "E" + str(episodeMedia.episode_number).zfill(2)
                                               if episodeMedia.season_number is not None else series.originalTitle + " " + episodeMedia.getIDString())
                mediaDictOriginal[episode_imdb_id] = episodeMedia
            series.episodes = [] # consumed -- resolved episodes now live as their own top-level entries

    # fail fast if any locally-owned title is on the ignored/wontadd list, before any scraping happens
    violating = [m for m in mediaDictOriginal.values() if m.imdb_id in ignoredIDs or m.imdb_id in wontaddIDs]
    if violating:
        raise LocalLibraryError("locally-owned media found on the ignored/wontadd list(s): " +
                                 ", ".join(m.originalTitle + " (" + m.getIDString() + ")" for m in violating))

    # fail fast if any locally-owned source references an unknown web provider, before any scraping happens
    db.checkWebProvidersKnown(mediaDictOriginal)

    # 2. determine newly added media
    newlyAddedMediaDict = db.determineNewlyAddedMedia(mediaDictOriginal)
    newlyAddedMediaDictOriginal = newlyAddedMediaDict.copy()

    scrapeimdbonline = ScrapeIMDbOnline(coverDir, thumbnailDir, webdriverPath, config.SCRAPE_DELAY, config.SCRAPE_MAX_COUNT)

    # 2b. restrict to the configured per-run budget before any scraping starts, bounding both how many
    # new movies/series get added this run and the online main-page/connections scraping below (steps
    # 3+4) that goes with them. A series (together with all of its resolved episodes) counts as a single
    # unit against the cap, so a sync run is never cut off midway through a series -- see
    # restrictToScrapeBudget. Referenced-only stub media (step 5, discovered from these items'
    # connections) fall outside this budget entirely -- they're cheap, offline-dataset-only additions:
    # a stub missing from the offline dataset is discarded outright rather than ever being scraped
    # online (see scrapeimdboffline.py's dataset-illegal handling), so they can never reach step 7's
    # online fallback either. Anything excluded here is simply not "newly added" yet as far as the rest
    # of this run is concerned; it's still missing from the DB afterwards, so it's picked up again on
    # the next sync.
    newlyAddedMediaDict = scrapeimdbonline.restrictToScrapeBudget(newlyAddedMediaDict)

    # 3. scrape main pages of newly added media: download covers if missing, scrape interests/language.
    # episodes (identified here by series_imdb_id already being set, from step 1b) are excluded --
    # they get none of this: no cover, no interests, no language, no plot summary. Series do get
    # interests/language/plot summary here, but scrapeMainPages itself skips the cover download for
    # them -- see its docstring
    moviesAndSeriesDict = {k: v for k, v in newlyAddedMediaDict.items() if v.series_imdb_id is None}
    knownInterestIDs = db.getAllKnownInterestIDs()
    knownLanguageIDs = db.getAllKnownLanguageIDs()
    knownPseudoGenreIDs = db.getAllKnownPseudoGenreIDs()
    knownFranchiseIDs = db.getAllKnownFranchiseIDs()
    # newly-discovered interests/languages/franchises are NOT persisted here -- ensureInterestExists
    # etc. are deferred until just before addMultipleMedia (see below), so an aborted sync can never
    # leave a subgenre/language registered in the DB without the title that triggered it actually
    # being added. knownInterestIDs/knownLanguageIDs/knownPseudoGenreIDs/knownFranchiseIDs are mutated
    # in place regardless, so this deferral costs nothing within this run -- a title later in the same
    # loop that hits the same new interest still recognizes it as already known.
    newInterestRegistrations, newLanguageRegistrations, newFranchiseRegistrations = scrapeimdbonline.scrapeMainPages(moviesAndSeriesDict, knownInterestIDs, knownLanguageIDs, knownPseudoGenreIDs, knownFranchiseIDs)

    # 4. parse media connections
    newlyAddedMediaDict = scrapeimdbonline.parseMediaConnections(newlyAddedMediaDict)

    # 5. add media to dict that are not in local library, but are referenced by local media (per IMDb connection)
    newlyAddedMediaDictCopy = newlyAddedMediaDict.copy()
    for x in newlyAddedMediaDictCopy.values():
        for y in x.mediaConnections:
            if y.foreignIMDbID in ignoredIDs:
                continue
            if y.foreignIMDbID not in mediaDictOriginal or (y.foreignIMDbID in newlyAddedMediaDictOriginal and y.foreignIMDbID not in newlyAddedMediaDictCopy):
                newlyAddedMediaDict[y.foreignIMDbID] = Media(None, None, y.foreignIMDbID)

    # 6. offline parsing; flags locally-owned titles missing from the dataset for online fallback (step 7),
    # discards referenced-only titles missing from the dataset
    scrapeimdboffline = ScrapeIMDbOffline(scrapeimdbonline, config.IMDB_DATASETS_DIR)

    # a referenced connection target might be an episode rather than a movie/series -- resolve any
    # such id's season/episode/parent series (must run before parseTitleBasics, see
    # parseTitleEpisode), then add the parent series too if not already known: series_imdb_id's FK
    # requires the series row to exist, not just nice for display. If the series is itself ignored,
    # drop the episode instead (it can't be added without its series; a locally-owned series being
    # ignored would already have failed the earlier local-scan check, so this can only happen for a
    # referenced-only episode)
    scrapeimdboffline.parseTitleEpisode(newlyAddedMediaDict)
    for imdb_id, x in list(newlyAddedMediaDict.items()):
        if x.series_imdb_id is None:
            continue
        if x.series_imdb_id in ignoredIDs:
            del newlyAddedMediaDict[imdb_id]
        elif x.series_imdb_id not in newlyAddedMediaDict:
            newlyAddedMediaDict[x.series_imdb_id] = Media(None, None, x.series_imdb_id)

    newlyAddedMediaDict = scrapeimdboffline.parseTitleRatings(newlyAddedMediaDict)
    newlyAddedMediaDict = scrapeimdboffline.parseTitleBasics(newlyAddedMediaDict)

    # 7. online fallback for locally-owned titles missing from the offline dataset (should happen very
    # infrequently). No cap of its own -- needsOnlineFallback is only ever set for locally-owned media
    # (see ScrapeIMDbOffline's dataset-illegal handling: a referenced-only title missing from the
    # dataset is discarded outright, never flagged), so flaggedMediaDict is already a subset of the
    # step-2b-restricted newlyAddedMediaDict and is bounded by the same per-run budget as everything else.
    flaggedMediaDict = {k: v for k, v in newlyAddedMediaDict.items() if v.needsOnlineFallback}
    if len(flaggedMediaDict) > 0:
        scrapeimdbonline.fillMissingBasics(flaggedMediaDict)

    # removals are entirely unaffected by the scrape budget -- they're driven by mediaDictOriginal (the
    # full local scan), not newlyAddedMediaDict, and never involve online scraping in the first place
    removedDict = db.determineLocallyRemovedMedia(mediaDictOriginal)
    db.removeMultipleMedia(removedDict)

    for x in newlyAddedMediaDict.values():
        if x.subdir == None:
            print(x.originalTitle + " " + str(x.startYear))

    # persist newly-discovered interests/languages/franchises now, right alongside the media that
    # triggered them -- interest_enum rows must exist before addMultipleMedia's media_interests
    # inserts below (FK), and keeping this adjacent to that call minimizes the window in which an
    # aborted sync could leave one registered without the corresponding title ever being added
    for imdb_interest_id, name, description, parent_imdb_interest_id in newInterestRegistrations:
        if imdb_interest_id < 0:
            print("New pseudo-genre added to interest enum: " + name + " (" + str(imdb_interest_id) + ")")
        elif parent_imdb_interest_id is None:
            print("New genre added to interest enum: " + name + " (" + str(imdb_interest_id) + ")")
        else:
            print("New subgenre added to interest enum: " + name + " (" + str(imdb_interest_id) + "), parent: " + str(parent_imdb_interest_id))
        db.ensureInterestExists(imdb_interest_id, name, description, parent_imdb_interest_id)
    for imdb_interest_id, name, description in newLanguageRegistrations:
        print("New language added to language enum: " + name + " (" + str(imdb_interest_id) + ")")
        db.ensureLanguageExists(imdb_interest_id, name, description)
    for imdb_interest_id, name in newFranchiseRegistrations:
        print("New franchise interest ignored: " + name + " (" + str(imdb_interest_id) + ")")
        db.ensureFranchiseInterestExists(imdb_interest_id)

    db.addMultipleMedia(newlyAddedMediaDict)

    # 8. recover covers missing for any currently-owned movie (e.g. deleted between syncs), then generate
    # thumbnails. Series covers are deliberately never fetched automatically -- IMDb only offers the latest
    # season's cover as a series' "main" image, which isn't what should represent the whole series locally;
    # a missing series cover is instead flagged below, for the user to source and place manually. A series
    # not yet resolved by title.basics this run still carries its "localSeries" local-scrape placeholder.
    seriesTitleTypesLocal = ["localSeries"] + Media.seriesTitleTypes
    moviesOnlyDict = {k: v for k, v in mediaDictOriginal.items() if v.series_imdb_id is None and v.titleType not in seriesTitleTypesLocal}
    scrapeimdbonline.downloadCovers(moviesOnlyDict)
    scrapeimdbonline.generateThumbnails()

    for v in mediaDictOriginal.values():
        if v.series_imdb_id is None and v.titleType in seriesTitleTypesLocal:
            coverPath = os.path.join(coverDir, v.getIDString() + ".jpg")
            if not os.path.isfile(coverPath):
                print("WARNING: no cover found for locally-owned series " + str(v.originalTitle) + " (" + v.getIDString() + ") -- series covers must be added manually")

    del scrapeimdbonline

    referencedOnlyMedia = db.getReferencedOnlyMedia()
    print("Referenced-only media:")
    print("# total: " + str(len(referencedOnlyMedia)) + " (before: " + str(referencedInitial) + ")")

def refreshTitleData():
    print("Refreshing data...")
    db = DBControl(config.DB_PATH)

    mediaDict = db.getAllMovieObjects()

    offline = ScrapeIMDbOffline(ScrapeIMDbOnline(config.COVERS_DIR, config.COVERS_SMALL_DIR, config.WEBDRIVER_PATH, config.SCRAPE_DELAY, config.SCRAPE_MAX_COUNT), config.IMDB_DATASETS_DIR)
    mediaDict = offline.refreshTitleRatings(mediaDict)
    mediaDict = offline.refreshTitleBasics(mediaDict)

    db.refreshRatings(mediaDict)
    db.refreshTitleBasics(mediaDict)

    # discover new episodes / detect vanished ones for every currently-owned series. New episodes
    # are added as referenced-only stubs (not scraped online -- refresh is purely offline-dataset
    # driven); a vanished, locally-owned episode is an error (see removeVanishedEpisode's docstring
    # for the referenced-only case).
    ownedSeries = [m for m in mediaDict.values() if m.subdir is not None and m.titleType in Media.seriesTitleTypes]
    if ownedSeries:
        fullEpisodeLists = offline.getFullEpisodeListForSeries({s.imdb_id for s in ownedSeries})

        newEpisodeStubs = {}
        for series in ownedSeries:
            for season, episode, episode_imdb_id in fullEpisodeLists[series.imdb_id]:
                if episode_imdb_id not in mediaDict and episode_imdb_id not in newEpisodeStubs:
                    stub = Media(None, None, episode_imdb_id)
                    stub.series_imdb_id = series.imdb_id
                    stub.season_number = season
                    stub.episode_number = episode
                    newEpisodeStubs[episode_imdb_id] = stub
        if newEpisodeStubs:
            offline.parseTitleRatings(newEpisodeStubs)
            offline.parseTitleBasics(newEpisodeStubs)
            for episode_imdb_id, stub in newEpisodeStubs.items():
                print("New episode discovered: " + str(stub.originalTitle) + " (" + stub.getIDString() + ") of " + str(mediaDict[stub.series_imdb_id].originalTitle if stub.series_imdb_id in mediaDict else stub.series_imdb_id))
            db.addMultipleMedia(newEpisodeStubs)
            mediaDict.update(newEpisodeStubs)

        for series in ownedSeries:
            currentEpisodeIDs = {m.imdb_id for m in mediaDict.values() if m.series_imdb_id == series.imdb_id}
            freshEpisodeIDs = {episode_imdb_id for (_, _, episode_imdb_id) in fullEpisodeLists[series.imdb_id]}
            for vanished_id in currentEpisodeIDs - freshEpisodeIDs:
                episodeMedia = mediaDict[vanished_id]
                if episodeMedia.subdir is not None:
                    raise OfflineDatasetError("locally-owned episode " + episodeMedia.getIDString() + " of " +
                                               str(series.originalTitle) + " is no longer listed in title.episode.tsv")
                db.removeVanishedEpisode(episodeMedia)

args = sys.argv[1:]
options = "hcstur"
long_options = ["help", "createdb", "sync", "stats", "update", "refresh"]

try:
    arguments, values = getopt.getopt(args, options, long_options)
    for currentArg, currentVal in arguments:
        if currentArg in ("-h", "--help"):
            print("Usage:\n-h | --help: Show this help.\n-c | --createdb: Create a new, empty database at the configured db_path.\n-s | --sync: Perform a sync between media folder and database.\n-t | --stats: Show statistics about media collection.\n-u | --update: Update IMDb offline datasets.\n-r | --refresh: Refresh ratings, basic title data, and each owned series' episode list for all known media from the offline datasets.")
        elif currentArg in ("-c", "--createdb"):
            DBControl(config.DB_PATH).createMediaDB()
        elif currentArg in ("-s", "--sync"):
            syncLocal(config.MEDIA_DIR, config.COVERS_DIR, config.COVERS_SMALL_DIR, config.WEBDRIVER_PATH)
        elif currentArg in ("-t", "--stats"):
            stat = Statistics(DBControl(config.DB_PATH))
            stat.printYearlyAverages()
            stat.analyzeMediaConnections()
        elif currentArg in ("-u", "--update"):
            ScrapeIMDbOffline(ScrapeIMDbOnline(config.COVERS_DIR, config.COVERS_SMALL_DIR, config.WEBDRIVER_PATH, config.SCRAPE_DELAY, config.SCRAPE_MAX_COUNT), config.IMDB_DATASETS_DIR).updateDatasets()
        elif currentArg in ("-r", "--refresh"):
            refreshTitleData()
except getopt.error as err:
    print(str(err))