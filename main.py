from media import Media
from dbcontrol import DBControl
from scrapelocal import ScrapeLocal
from scrapeimdboffline import ScrapeIMDbOffline
from scrapeimdbonline import ScrapeIMDbOnline
from statistics import Statistics

def syncLocal(mediaDir, db, coverDir):
    scrape = ScrapeLocal(mediaDir)
    mediaDictOriginal = scrape.scrapeLocalComplete()

    newlyAddedMediaDict = db.determineNewlyAddedMedia(mediaDictOriginal)
    newlyAddedMediaDictOriginal = newlyAddedMediaDict.copy()

    scrapeimdbonline = ScrapeIMDbOnline(coverDir, 5, 2)
    scrapeimdbonline.downloadCovers(newlyAddedMediaDict)
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

db = DBControl(':memory:')
db.createMediaDB()
referencedInitial = len(db.getReferencedOnlyMedia())
syncLocal(r"Y:", db, r"C:\Users\Sebastian\Desktop\scripting\media-control\covers")

#print(db.getLocalMediaByGenreAND(["Horror"]))

referencedOnlyMedia = db.getReferencedOnlyMedia()
print("Referenced-only media:")
print(referencedOnlyMedia)
print("# total: " + str(len(referencedOnlyMedia)) + " (before: " + str(referencedInitial) + ")")

#print(db.getMediaByRatingRange(80, 100))
#print(db.getAllMediaSortedByNumVotes())
#print(db.getAllMediaSortedByRating())

# stat = Statistics(db)
# stat.printYearlyAverages()
# stat.analyzeMediaConnections()


