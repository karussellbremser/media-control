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

    scrape = ScrapeLocal(mediaDir)
    mediaDictOriginal = scrape.scrapeLocalComplete()

    newlyAddedMediaDict = db.determineNewlyAddedMedia(mediaDictOriginal)
    newlyAddedMediaDictOriginal = newlyAddedMediaDict.copy()

    scrapeimdbonline = ScrapeIMDbOnline(coverDir, thumbnailDir, webdriverPath, config.SCRAPE_DELAY, config.SCRAPE_MAX_COUNT)
    scrapeimdbonline.downloadCovers(mediaDictOriginal) # download all missing covers, regardless of whether they are newly added
    scrapeimdbonline.generateThumbnails()
    newlyAddedMediaDict = scrapeimdbonline.parseMediaConnections(newlyAddedMediaDict)

    # add media to dict that are not in local library, but are referenced by local media (per IMDb connection)
    newlyAddedMediaDictCopy = newlyAddedMediaDict.copy()
    for x in newlyAddedMediaDictCopy.values():
        for y in x.mediaConnections:
            if y.foreignIMDbID not in mediaDictOriginal or (y.foreignIMDbID in newlyAddedMediaDictOriginal and y.foreignIMDbID not in newlyAddedMediaDictCopy):
                newlyAddedMediaDict[y.foreignIMDbID] = Media(None, None, y.foreignIMDbID)

    scrapeimdboffline = ScrapeIMDbOffline(scrapeimdbonline, config.IMDB_DATASETS_DIR)
    newlyAddedMediaDict = scrapeimdboffline.parseTitleRatings(newlyAddedMediaDict)
    newlyAddedMediaDict = scrapeimdboffline.parseTitleBasics(newlyAddedMediaDict)
    del scrapeimdbonline

    removedDict = db.determineLocallyRemovedMedia(mediaDictOriginal)
    db.removeMultipleMedia(removedDict)

    for x in newlyAddedMediaDict.values():
        if x.subdir == None:
            print(x.originalTitle + " " + str(x.startYear))

    db.addMultipleMedia(newlyAddedMediaDict)
    
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
options = "hstur"
long_options = ["help", "sync", "stats", "update", "refresh"]

try:
    arguments, values = getopt.getopt(args, options, long_options)
    for currentArg, currentVal in arguments:
        if currentArg in ("-h", "--help"):
            print("Usage:\n-h | --help: Show this help.\n-s | --sync: Perform a sync between media folder and database.\n-t | --stats: Show statistics about media collection.\n-u | --update: Update IMDb offline datasets.")
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