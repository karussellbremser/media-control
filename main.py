from media import Media
from dbcontrol import DBControl
from dbbackup import DBBackup
from scrapelocal import ScrapeLocal
from scrapeimdboffline import ScrapeIMDbOffline
from scrapeimdbonline import ScrapeIMDbOnline
from scrapemediainfo import ScrapeMediaInfo
from statistics import Statistics
from exceptions import LocalLibraryError, OfflineDatasetError
from verbosity import printAlways, printDetail, printPerson
import config
import getopt, os, sys, time

def readIDList(path):
    """Reads a user-maintained list of imdb ids, one 'tt#######' per line (blank lines ignored).
    A missing file is treated as an empty list, since these lists are optional."""
    if not os.path.exists(path):
        return set()
    with open(path, "r") as f:
        return {int(line.strip()[2:]) for line in f if line.strip()}

def printStep(number, description):
    """Prints a step-header line for syncLocal's console output, matching the step numbering in
    syncLocal's own comments. Only ever called once a step is already known to have something to
    do this run -- a run that finds nothing new stays short instead of listing all 15 steps
    unconditionally. Steps 7/8/9/12/15 print their own matching header instead (see
    ScrapeIMDbOnline.__printStepHeader), since each of those is owned by a single method there.
    The fail-fast validation right after step 2 has no number of its own -- it never has anything
    to print on success, only ever an exception on failure, so a step number for it would never
    correspond to anything appearing in this output. Always printed, regardless of
    config.VERBOSITY -- see verbosity.printAlways."""
    printAlways("\nStep " + str(number) + ": " + description)

def syncLocal(mediaDir, coverDir, thumbnailDir):
    printAlways("Starting sync...")

    # fail fast, before any real work starts, if the offline dataset helper DB hasn't been built
    # yet -- otherwise this would only surface much later (and far less clearly) the first time
    # something actually queries it, e.g. as a sqlite "no such table" error, sqlite3.connect()
    # having silently created an empty file at this path in the meantime (see
    # ScrapeIMDbOffline.__getCursor)
    if not os.path.isfile(config.IMDB_HELPER_DB_PATH):
        raise OfflineDatasetError("IMDb offline dataset helper DB not found at " + config.IMDB_HELPER_DB_PATH +
                                   " -- run 'python main.py -u' (or --update) to build it first")

    db = DBControl(config.DB_PATH)

    db.syncWebProvidersFromConfig(config.WEB_PROVIDERS)

    ignoredIDs = readIDList(config.IGNORED_IDS_PATH)
    wontaddIDs = readIDList(config.WONTADD_IDS_PATH)
    db.syncIgnoredAndWontaddIDs(ignoredIDs, wontaddIDs)
    db.enforceIgnoredAndWontaddIDs()

    referencedInitial = len(db.getReferencedOnlyMedia())

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
                # used for progress printing before offline parsing (step 11) unconditionally
                # overwrites it with the real title from title.basics
                episodeMedia.originalTitle = (series.originalTitle + " S" + str(episodeMedia.season_number).zfill(2) + "E" + str(episodeMedia.episode_number).zfill(2)
                                               if episodeMedia.season_number is not None else series.originalTitle + " " + episodeMedia.getIDString())
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
                                 ", ".join(m.originalTitle + " (" + m.getIDString() + ")" for m in violating))

    # - any locally-owned source referencing an unknown web provider is also a configuration error
    db.checkWebProvidersKnown(mediaDictOriginal)

    # 3. apply local removals, as early as possible -- right after the local scan (and its fail-fast
    # validation) establish the ground truth of what's still locally owned, and before anything else
    # queries the DB for "does X currently exist / is X locally owned". Removals are self-contained
    # (a removed item's connection edges, and any now-orphaned interests/languages/people, are
    # cleaned up within removeSingleMedia itself), so this doesn't need to wait for the rest of the
    # sync to succeed -- "removals applied, nothing added yet" is a perfectly safe, retriable state,
    # same as any other partially-progressed sync. Running it this early instead closes off a whole
    # class of stale-DB-state bugs further down: e.g. without this, a series about to be removed
    # here would still look "already exists" to step 11's parent-series-stub check, which could then
    # skip creating a stub for it -- if that series then legitimately gets removed while a brand-new
    # referenced episode (discovered elsewhere this same run) still points at it, the write in step
    # 13 would hit a foreign-key violation over a series row that no longer exists.
    removedDict = db.determineLocallyRemovedMedia(mediaDictOriginal)
    if removedDict:
        printStep(3, "removing " + str(len(removedDict)) + " title(s) no longer locally owned")
    db.removeMultipleMedia(removedDict)

    # 4. determine newly added media
    newlyAddedMediaDict = db.determineNewlyAddedMedia(mediaDictOriginal)
    newlyAddedMediaDictOriginal = newlyAddedMediaDict.copy()
    printStep(4, str(len(newlyAddedMediaDict)) + " newly-added title(s) found")

    scrapeimdbonline = ScrapeIMDbOnline(coverDir, thumbnailDir, config.SCRAPE_DELAY, config.SCRAPE_MAX_COUNT, config.CHROME_PROFILE_DIR, config.SCRAPE_HEADLESS, config.SCRAPE_PAGE_LOAD_WAIT)

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

    # 6. run MediaInfo analysis on every file belonging to a title that's both newly added and
    # survived the scrape budget above -- movies' own mediaVersions, plus already-resolved episodes'
    # (from step 2); series themselves and any later-discovered referenced-only stub media have no
    # mediaVersions at all, so nothing extra needs excluding here. A missing file is a
    # LocalLibraryError, malformed/unexpected MediaInfo output is a MediaInfoError -- both propagate
    # and abort the sync, same fail-loud treatment as everything else that doesn't match expectations.
    # Kaleidescape-sourced versions are skipped entirely -- there's no local file to analyze, just an
    # empty .kscape placeholder (see MediaVersion.isKaleidescapeOnly); duration/mediainfo_version/
    # format/width/height etc. stay None until a future online Kaleidescape scraper fills them in.
    # The size check below guards the one dangerous mismatch: a real, non-empty file whose source was
    # mistakenly declared as kscape would otherwise have its analysis silently skipped rather than
    # erroring (the reverse mismatch -- a .kscape-extension file with a non-kscape source -- already
    # can't happen, since ScrapeLocal requires every .kscape file to be empty regardless of source).
    if any(m.mediaVersions for m in newlyAddedMediaDict.values()):
        printStep(6, "analyzing local media files with MediaInfo")
    scrapeMediaInfo = ScrapeMediaInfo(config.MEDIAINFO_PATH)
    for currentMedia in newlyAddedMediaDict.values():
        for mediaVersion in currentMedia.mediaVersions:
            if mediaVersion.isKaleidescapeOnly():
                filepath = os.path.join(mediaDir, currentMedia.subdir, mediaVersion.filename)
                if os.path.isfile(filepath) and os.path.getsize(filepath) > 0:
                    raise LocalLibraryError("Kaleidescape-sourced file is not empty: " + filepath)
                printDetail("  skipping Kaleidescape-owned file (no local file to analyze): " + filepath)
                continue
            scrapeMediaInfo.analyzeMediaVersion(mediaDir, currentMedia.subdir, mediaVersion)

    # 7. scrape main pages of newly added media: download covers if missing, scrape interests/language.
    # episodes (identified here by series_imdb_id already being set, from step 2) are excluded --
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
            if y.foreignIMDbID in ignoredIDs:
                continue
            if y.foreignIMDbID not in mediaDictOriginal or (y.foreignIMDbID in newlyAddedMediaDictOriginal and y.foreignIMDbID not in newlyAddedMediaDictCopy):
                newlyAddedMediaDict[y.foreignIMDbID] = Media(None, None, y.foreignIMDbID)
    if len(newlyAddedMediaDict) > beforeReferencedCount:
        printStep(10, str(len(newlyAddedMediaDict) - beforeReferencedCount) + " referenced-only title(s) added from connections")

    # 11. offline parsing; flags locally-owned titles missing from the dataset for online fallback (step 12),
    # discards referenced-only titles missing from the dataset. Also resolves name/birth_year/death_year
    # for every person newly discovered in step 9's credits scrape (see ScrapeIMDbOffline.parsePeople).
    if newlyAddedMediaDict:
        printStep(11, "querying the offline dataset helper DB (ratings, basics, episode resolution, new people)")
    scrapeimdboffline = ScrapeIMDbOffline(scrapeimdbonline, config.IMDB_HELPER_DB_PATH)

    newPeopleDict = {p.imdb_id: p for p in newPersonRegistrations}
    newPeopleDict = scrapeimdboffline.parsePeople(newPeopleDict)

    # a referenced connection target might be an episode rather than a movie/series -- resolve any
    # such id's season/episode/parent series (must run before parseTitleBasics, see
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

    newlyAddedMediaDict = scrapeimdboffline.parseTitleRatings(newlyAddedMediaDict)
    newlyAddedMediaDict = scrapeimdboffline.parseTitleBasics(newlyAddedMediaDict)

    # 12. online fallback for locally-owned titles missing from the offline dataset (should happen very
    # infrequently). No cap of its own -- needsOnlineFallback is only ever set for locally-owned media
    # (see ScrapeIMDbOffline's dataset-illegal handling: a referenced-only title missing from the
    # dataset is discarded outright, never flagged), so flaggedMediaDict is already a subset of the
    # step-5-restricted newlyAddedMediaDict and is bounded by the same per-run budget as everything else.
    flaggedMediaDict = {k: v for k, v in newlyAddedMediaDict.items() if v.needsOnlineFallback}
    if len(flaggedMediaDict) > 0:
        scrapeimdbonline.fillMissingBasics(flaggedMediaDict)

    # 13. finalize and write newly-added media (plus this run's new credits/people) to the DB
    if newlyAddedMediaDict:
        printStep(13, "finalizing and writing " + str(len(newlyAddedMediaDict)) + " newly-added title(s) to the DB")

    # - print newly-added media that isn't locally owned (referenced-only additions), for visibility
    for x in newlyAddedMediaDict.values():
        if x.subdir == None:
            printDetail("  adding referenced-only: " + x.originalTitle + " (" + str(x.startYear) + ")")

    # - strip any dangling connection edges before writing. A referenced episode dropped above because
    # its series is ignored (step 11) is the known case: other kept items' mediaConnections can still
    # point at it, and since media_connections.foreign_imdb_id has an FK back to media.imdb_id,
    # inserting such an edge would crash addMultipleMedia. Only prune targets that are neither being
    # added this run nor already in the DB -- an already-existing target's row satisfies the FK
    # regardless of whether this run touches it.
    referencedIDs = {y.foreignIMDbID for x in newlyAddedMediaDict.values() for y in x.mediaConnections}
    missingIDs = referencedIDs - set(newlyAddedMediaDict.keys())
    if missingIDs:
        existingIDs = {row[0] for row in db.getAllMediaIDs()}
        danglingIDs = missingIDs - existingIDs
        if danglingIDs:
            for x in newlyAddedMediaDict.values():
                x.mediaConnections = [y for y in x.mediaConnections if y.foreignIMDbID not in danglingIDs]

    # steps 13/14's writes (new people/interests/languages/franchises, the newly-added
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
        # Same reasoning as the interest/language/franchise registrations right below.
        for person in newPeopleDict.values():
            printPerson("  new person added: " + str(person.name) + " (" + person.getIDString() + ")")
            db._ensurePersonExistsNoCommit(person)

        # - persist newly-discovered interests/languages/franchises now, right alongside the media that
        # triggered them -- interest_enum rows must exist before addMultipleMedia's media_interests
        # inserts below (FK)
        for imdb_interest_id, name, description, parent_imdb_interest_id in newInterestRegistrations:
            if imdb_interest_id < 0:
                printDetail("  new pseudo-genre added to interest enum: " + name + " (" + str(imdb_interest_id) + ")")
            elif parent_imdb_interest_id is None:
                printDetail("  new genre added to interest enum: " + name + " (" + str(imdb_interest_id) + ")")
            else:
                printDetail("  new subgenre added to interest enum: " + name + " (" + str(imdb_interest_id) + "), parent: " + str(parent_imdb_interest_id))
            db._ensureInterestExistsNoCommit(imdb_interest_id, name, description, parent_imdb_interest_id)
        for imdb_interest_id, name, description in newLanguageRegistrations:
            printDetail("  new language added to language enum: " + name + " (" + str(imdb_interest_id) + ")")
            db._ensureLanguageExistsNoCommit(imdb_interest_id, name, description)
        for imdb_interest_id, name in newFranchiseRegistrations:
            printDetail("  new franchise interest ignored: " + name + " (" + str(imdb_interest_id) + ")")
            db._ensureFranchiseInterestExistsNoCommit(imdb_interest_id)

        # - the write itself
        db._addMultipleMediaNoCommit(newlyAddedMediaDict)

        # 14. for every series that had something new happen to it this run (the series itself newly
        # added, or at least one of its locally-resolved episodes newly added -- checked against
        # newlyAddedMediaDictOriginal, the snapshot of what was missing from the DB at the start of this
        # sync), make sure its FULL episode catalog (per title.episode.tsv) is represented in the DB
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
                              if series.imdb_id in newlyAddedMediaDictOriginal
                              or any(ep_id in newlyAddedMediaDictOriginal for ep_id in localEpisodeIDsBySeriesID.get(series.imdb_id, []))]

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
                        if episode_imdb_id not in mediaDictOriginal and episode_imdb_id not in existingIDs and episode_imdb_id not in newEpisodeStubs:
                            stub = Media(None, None, episode_imdb_id)
                            stub.series_imdb_id = series.imdb_id
                            stub.season_number = season
                            stub.episode_number = episode
                            newEpisodeStubs[episode_imdb_id] = stub
                if newEpisodeStubs:
                    newEpisodeStubs = offlineForCompleteness.parseTitleRatings(newEpisodeStubs)
                    newEpisodeStubs = offlineForCompleteness.parseTitleBasics(newEpisodeStubs)
                    seriesTitlesByID = {series.imdb_id: series.originalTitle for series in readySeries}
                    for episode_imdb_id, stub in newEpisodeStubs.items():
                        printDetail("  cataloging episode " + str(stub.originalTitle) + " (" + stub.getIDString() + ") of " + str(seriesTitlesByID.get(stub.series_imdb_id, stub.series_imdb_id)))
                    db._addMultipleMediaNoCommit(newEpisodeStubs)

    # 15. recover covers missing for any currently-owned movie (e.g. deleted between syncs), then generate
    # thumbnails. Series covers are deliberately never fetched automatically -- IMDb only offers the latest
    # season's cover as a series' "main" image, which isn't what should represent the whole series locally;
    # a missing series cover is instead flagged below, for the user to source and place manually. A series
    # not yet resolved by title.basics this run still carries its "localSeries" local-scrape placeholder.
    # Non-English movies get the same manual-only treatment (see ScrapeIMDbOnline.scrapeMainPages) --
    # queried directly from the DB rather than trusted from mediaDictOriginal, since a freshly-rescanned
    # Media object's in-memory language_id defaults to English for any title not newly scraped this run.
    seriesTitleTypesLocal = ["localSeries"] + Media.seriesTitleTypes
    nonEnglishMovieIDs = db.getNonEnglishLocallyOwnedMovieIDs()
    moviesOnlyDict = {k: v for k, v in mediaDictOriginal.items() if v.series_imdb_id is None and v.titleType not in seriesTitleTypesLocal and k not in nonEnglishMovieIDs}
    scrapeimdbonline.downloadCovers(moviesOnlyDict)
    scrapeimdbonline.generateThumbnails()

    for v in mediaDictOriginal.values():
        if v.series_imdb_id is None and (v.titleType in seriesTitleTypesLocal or v.imdb_id in nonEnglishMovieIDs):
            coverPath = os.path.join(coverDir, v.getIDString() + ".jpg")
            if not os.path.isfile(coverPath):
                kind = "series" if v.titleType in seriesTitleTypesLocal else "non-English movie"
                printAlways("WARNING: no cover found for locally-owned " + kind + " " + str(v.originalTitle) + " (" + v.getIDString() + ") -- covers for series and non-English movies must be added manually")

    del scrapeimdbonline

    referencedOnlyMedia = db.getReferencedOnlyMedia()
    printAlways("\nSync complete. Referenced-only media: " + str(len(referencedOnlyMedia)) + " total (was " + str(referencedInitial) + " before this run).")

def refreshTitleData():
    printAlways("Refreshing data...")
    db = DBControl(config.DB_PATH)

    mediaDict = db.getAllMovieObjects()

    offline = ScrapeIMDbOffline(ScrapeIMDbOnline(config.COVERS_DIR, config.COVERS_SMALL_DIR, config.SCRAPE_DELAY, config.SCRAPE_MAX_COUNT, config.CHROME_PROFILE_DIR, config.SCRAPE_HEADLESS, config.SCRAPE_PAGE_LOAD_WAIT), config.IMDB_HELPER_DB_PATH)
    mediaDict = offline.refreshTitleRatings(mediaDict)
    mediaDict = offline.refreshTitleBasics(mediaDict)

    db.refreshRatings(mediaDict)
    db.refreshTitleBasics(mediaDict)

    peopleDict = db.getAllPersonObjects()
    peopleDict = offline.refreshPeople(peopleDict)
    db.refreshPeople(peopleDict)

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
                printDetail("New episode discovered: " + str(stub.originalTitle) + " (" + stub.getIDString() + ") of " + str(mediaDict[stub.series_imdb_id].originalTitle if stub.series_imdb_id in mediaDict else stub.series_imdb_id))
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
        ScrapeIMDbOffline(ScrapeIMDbOnline(config.COVERS_DIR, config.COVERS_SMALL_DIR, config.SCRAPE_DELAY, config.SCRAPE_MAX_COUNT, config.CHROME_PROFILE_DIR, config.SCRAPE_HEADLESS, config.SCRAPE_PAGE_LOAD_WAIT), config.IMDB_HELPER_DB_PATH).updateIMDbOfflineDB()
    except Exception as e:
        printAlways("WARNING: automatic helper DB update failed: " + str(e))
        return

    if runAutoRefresh and config.HELPER_DB_AUTO_REFRESH_ENABLED:
        printAlways("Auto-refresh enabled -- refreshing all known media against the freshly-updated helper DB...")
        refreshTitleData()

args = sys.argv[1:]
options = "hcsturb"
long_options = ["help", "createdb", "sync", "stats", "update", "refresh", "backup"]

try:
    arguments, values = getopt.getopt(args, options, long_options)
    for currentArg, currentVal in arguments:
        if currentArg in ("-h", "--help"):
            print("Usage:\n-h | --help: Show this help.\n-c | --createdb: Create a new, empty database at the configured db_path.\n-s | --sync: Perform a sync between media folder and database.\n-t | --stats: Show statistics about media collection.\n-u | --update: Rebuild the IMDb offline dataset helper DB.\n-r | --refresh: Refresh ratings, basic title data, each owned series' episode list, and known people, for all known media from the IMDb offline dataset helper DB.\n-b | --backup: Immediately create a DB backup, regardless of how recent the last one is (-s and -r also create one automatically once the last backup is old enough -- see config.ini's [backup] section, auto_backup).")
        elif currentArg in ("-c", "--createdb"):
            DBControl(config.DB_PATH).createMediaDB()
        elif currentArg in ("-s", "--sync"):
            if config.BACKUP_AUTO_ENABLED:
                DBBackup(config.DB_PATH, config.BACKUP_DIR, config.BACKUP_MAX_COUNT).ensureBackup(config.BACKUP_FREQUENCY_DAYS)
            ensureHelperDBFresh(runAutoRefresh=True)
            syncLocal(config.MEDIA_DIR, config.COVERS_DIR, config.COVERS_SMALL_DIR)
        elif currentArg in ("-t", "--stats"):
            stat = Statistics(DBControl(config.DB_PATH))
            stat.printYearlyAverages()
            stat.analyzeMediaConnections()
        elif currentArg in ("-u", "--update"):
            ScrapeIMDbOffline(ScrapeIMDbOnline(config.COVERS_DIR, config.COVERS_SMALL_DIR, config.SCRAPE_DELAY, config.SCRAPE_MAX_COUNT, config.CHROME_PROFILE_DIR, config.SCRAPE_HEADLESS, config.SCRAPE_PAGE_LOAD_WAIT), config.IMDB_HELPER_DB_PATH).updateIMDbOfflineDB()
            if config.HELPER_DB_AUTO_REFRESH_ENABLED:
                refreshTitleData()
        elif currentArg in ("-r", "--refresh"):
            if config.BACKUP_AUTO_ENABLED:
                DBBackup(config.DB_PATH, config.BACKUP_DIR, config.BACKUP_MAX_COUNT).ensureBackup(config.BACKUP_FREQUENCY_DAYS)
            ensureHelperDBFresh(runAutoRefresh=False)
            refreshTitleData()
        elif currentArg in ("-b", "--backup"):
            DBBackup(config.DB_PATH, config.BACKUP_DIR, config.BACKUP_MAX_COUNT).forceBackup()
except getopt.error as err:
    print(str(err))