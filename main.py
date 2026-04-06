from media import Media
from dbcontrol import DBControl
from scrapelocal import ScrapeLocal
from scrapeimdboffline import ScrapeIMDbOffline
from scrapeimdbonline import ScrapeIMDbOnline
from statistics import Statistics
import getopt, sys

def syncLocal(mediaDir, coverDir, thumbnailDir, webdriverPath):
    db = DBControl('myMovieDB.db')
    
    referencedInitial = len(db.getReferencedOnlyMedia())
    
    scrape = ScrapeLocal(mediaDir)
    mediaDictOriginal = scrape.scrapeLocalComplete()

    newlyAddedMediaDict = db.determineNewlyAddedMedia(mediaDictOriginal)
    newlyAddedMediaDictOriginal = newlyAddedMediaDict.copy()

    scrapeimdbonline = ScrapeIMDbOnline(coverDir, thumbnailDir, webdriverPath, 5, 50)
    scrapeimdbonline.downloadCovers(mediaDictOriginal) # download all missing covers, regardless of whether they are newly added
    scrapeimdbonline.generateThumbnails()
    newlyAddedMediaDict = scrapeimdbonline.parseMediaConnections(newlyAddedMediaDict)

    # add media to dict that are not in local library, but are referenced by local media (per IMDb connection)
    newlyAddedMediaDictCopy = newlyAddedMediaDict.copy()
    for x in newlyAddedMediaDictCopy.values():
        for y in x.mediaConnections:
            if y.foreignIMDbID not in mediaDictOriginal or (y.foreignIMDbID in newlyAddedMediaDictOriginal and y.foreignIMDbID not in newlyAddedMediaDictCopy):
                newlyAddedMediaDict[y.foreignIMDbID] = Media(None, None, y.foreignIMDbID)

    scrapeimdboffline = ScrapeIMDbOffline(scrapeimdbonline, r"C:\imdb_datasets")
    newlyAddedMediaDict = scrapeimdboffline.parseTitleRatings(newlyAddedMediaDict)
    newlyAddedMediaDict = scrapeimdboffline.parseTitleBasics(newlyAddedMediaDict)

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
    db = DBControl('myMovieDB.db')
    
    imdbOnlyDict = db.getDictWithImdbIDs()
    imdbOnlyDict = ScrapeIMDbOffline(ScrapeIMDbOnline(r"C:\Users\Sebastian\Desktop\scripting\media-control\covers", r"C:\Users\Sebastian\Desktop\scripting\media-control\covers_small", "C:\\Users\\Sebastian\\Desktop\\scripting\\media-control\\tools\\chromedriver-win32\\chromedriver.exe", 5, 50), r"C:\imdb_datasets").refreshTitleRatings(imdbOnlyDict)
    
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
            syncLocal(r"Y:", r"C:\Users\Sebastian\Desktop\scripting\media-control\covers", r"C:\Users\Sebastian\Desktop\scripting\media-control\covers_small", "C:\\Users\\Sebastian\\Desktop\\scripting\\media-control\\tools\\chromedriver-win32\\chromedriver.exe")
        elif currentArg in ("-t", "--stats"):
            stat = Statistics(DBControl('myMovieDB.db'))
            stat.printYearlyAverages()
            stat.analyzeMediaConnections()
        elif currentArg in ("-u", "--update"):
            ScrapeIMDbOffline(ScrapeIMDbOnline(r"C:\Users\Sebastian\Desktop\scripting\media-control\covers", r"C:\Users\Sebastian\Desktop\scripting\media-control\covers_small", "C:\\Users\\Sebastian\\Desktop\\scripting\\media-control\\tools\\chromedriver-win32\\chromedriver.exe", 5, 50), r"C:\imdb_datasets").updateDatasets()
        elif currentArg in ("-r", "--refresh"):
            refreshTitleRatings()
except getopt.error as err:
    print(str(err))