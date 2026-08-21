from media import Media
from dbcontrol import DBControl
from scrapelocal import ScrapeLocal
from scrapeimdboffline import ScrapeIMDbOffline
from scrapeimdbonline import ScrapeIMDbOnline
from statistics import Statistics
import config
import getopt, sys

def syncLocal(mediaDir, coverDir, thumbnailDir, webdriverPath):
    db = DBControl(config.DB_PATH)

    referencedInitial = len(db.getReferencedOnlyMedia())

    # 1. scan local media library
    scrape = ScrapeLocal(mediaDir)
    mediaDictOriginal = scrape.scrapeLocalComplete()

    # 2. determine newly added media
    newlyAddedMediaDict = db.determineNewlyAddedMedia(mediaDictOriginal)
    newlyAddedMediaDictOriginal = newlyAddedMediaDict.copy()

    scrapeimdbonline = ScrapeIMDbOnline(coverDir, thumbnailDir, webdriverPath, config.SCRAPE_DELAY, config.SCRAPE_MAX_COUNT)

    # 3. scrape main pages of newly added media: download covers if missing, scrape interests/language
    knownInterestIDs = db.getAllKnownInterestIDs()
    knownLanguageIDs = db.getAllKnownLanguageIDs()
    newInterestRegistrations, newLanguageRegistrations = scrapeimdbonline.scrapeMainPages(newlyAddedMediaDict, knownInterestIDs, knownLanguageIDs)
    for imdb_interest_id, name, description, parent_imdb_interest_id in newInterestRegistrations:
        if parent_imdb_interest_id is None:
            print("New genre added to interest enum: " + name + " (" + imdb_interest_id + ")")
        else:
            print("New subgenre added to interest enum: " + name + " (" + imdb_interest_id + "), parent: " + parent_imdb_interest_id)
        db.ensureInterestExists(imdb_interest_id, name, description, parent_imdb_interest_id)
    for imdb_interest_id, name, description in newLanguageRegistrations:
        print("New language added to language enum: " + name + " (" + imdb_interest_id + ")")
        db.ensureLanguageExists(imdb_interest_id, name, description)

    # 4. parse media connections
    newlyAddedMediaDict = scrapeimdbonline.parseMediaConnections(newlyAddedMediaDict)

    # 5. add media to dict that are not in local library, but are referenced by local media (per IMDb connection)
    newlyAddedMediaDictCopy = newlyAddedMediaDict.copy()
    for x in newlyAddedMediaDictCopy.values():
        for y in x.mediaConnections:
            if y.foreignIMDbID not in mediaDictOriginal or (y.foreignIMDbID in newlyAddedMediaDictOriginal and y.foreignIMDbID not in newlyAddedMediaDictCopy):
                newlyAddedMediaDict[y.foreignIMDbID] = Media(None, None, y.foreignIMDbID)

    # 6. offline parsing; flags locally-owned titles missing from the dataset for online fallback (step 7),
    # discards referenced-only titles missing from the dataset
    scrapeimdboffline = ScrapeIMDbOffline(scrapeimdbonline, config.IMDB_DATASETS_DIR)
    newlyAddedMediaDict = scrapeimdboffline.parseTitleRatings(newlyAddedMediaDict)
    newlyAddedMediaDict = scrapeimdboffline.parseTitleBasics(newlyAddedMediaDict)

    # 7. online fallback for locally-owned titles missing from the offline dataset (should happen very infrequently)
    flaggedMediaDict = {k: v for k, v in newlyAddedMediaDict.items() if v.needsOnlineFallback}
    if len(flaggedMediaDict) > 0:
        scrapeimdbonline.fillMissingBasics(flaggedMediaDict)

    removedDict = db.determineLocallyRemovedMedia(mediaDictOriginal)
    db.removeMultipleMedia(removedDict)

    for x in newlyAddedMediaDict.values():
        if x.subdir == None:
            print(x.originalTitle + " " + str(x.startYear))

    db.addMultipleMedia(newlyAddedMediaDict)

    # 8. recover covers missing for any currently-owned medium (e.g. deleted between syncs), then generate thumbnails
    scrapeimdbonline.downloadCovers(mediaDictOriginal)
    scrapeimdbonline.generateThumbnails()

    del scrapeimdbonline

    referencedOnlyMedia = db.getReferencedOnlyMedia()
    print("Referenced-only media:")
    print("# total: " + str(len(referencedOnlyMedia)) + " (before: " + str(referencedInitial) + ")")

def refreshTitleRatings():
    print("Refreshing ratings...")
    db = DBControl(config.DB_PATH)

    imdbOnlyDict = db.getDictWithImdbIDs()
    imdbOnlyDict = ScrapeIMDbOffline(ScrapeIMDbOnline(config.COVERS_DIR, config.COVERS_SMALL_DIR, config.WEBDRIVER_PATH, config.SCRAPE_DELAY, config.SCRAPE_MAX_COUNT), config.IMDB_DATASETS_DIR).refreshTitleRatings(imdbOnlyDict)

    db.refreshRatings(imdbOnlyDict)

args = sys.argv[1:]
options = "hcstur"
long_options = ["help", "createdb", "sync", "stats", "update", "refresh"]

try:
    arguments, values = getopt.getopt(args, options, long_options)
    for currentArg, currentVal in arguments:
        if currentArg in ("-h", "--help"):
            print("Usage:\n-h | --help: Show this help.\n-c | --createdb: Create a new, empty database at the configured db_path.\n-s | --sync: Perform a sync between media folder and database.\n-t | --stats: Show statistics about media collection.\n-u | --update: Update IMDb offline datasets.")
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
            refreshTitleRatings()
except getopt.error as err:
    print(str(err))