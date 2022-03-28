from media import Media
from dbcontrol import DBControl
from scrapelocal import ScrapeLocal
from scrapeimdboffline import ScrapeIMDbOffline
from scrapeimdbonline import ScrapeIMDbOnline
from statistics import Statistics

def syncLocal(mediaDir, db, coverDir):
    scrape = ScrapeLocal(mediaDir)
    mediaDictOriginal = scrape.scrapeLocalComplete()

    mediaDict = db.determineNewlyAddedMedia(mediaDictOriginal)

    scrapeimdbonline = ScrapeIMDbOnline(coverDir, 5)
    scrapeimdbonline.downloadCovers(mediaDict, 50)
    mediaDict = scrapeimdbonline.parseMediaConnections(mediaDict)

    # add media to dict that are not in local library, but are referenced by local media (per IMDb connection)
    mediaDictCopy = mediaDict.copy()
    for x in mediaDictCopy.values():
        for y in x.mediaConnections:
            if y.foreignIMDbID not in mediaDictOriginal:
                mediaDict[y.foreignIMDbID] = Media(None, None, y.foreignIMDbID)

    scrapeimdboffline = ScrapeIMDbOffline(scrapeimdbonline, r"C:\imdb_datasets")
    mediaDict = scrapeimdboffline.parseTitleRatings(mediaDict)
    mediaDict = scrapeimdboffline.parseTitleBasics(mediaDict)

    removedDict = db.determineLocallyRemovedMedia(mediaDictOriginal)
    db.removeMultipleMedia(removedDict)


    for x in mediaDict.values():
        if x.subdir == None:
            print(x.originalTitle + " " + str(x.startYear))
    #for x in mediaDict.values():
    #    for y in x.mediaConnections:
    #        print(str(x.imdb_id) + " " + str(y))


    #db.createMediaDB()

    db.addMultipleMedia(mediaDict)

db = DBControl('myMovieDB.db')
syncLocal(r"Y:", db, r"C:\Users\Sebastian\Desktop\scripting\media-control\covers")

#print(db.getLocalMediaByGenreAND(["Horror"]))

referencedOnlyMedia = db.getReferencedOnlyMedia()
print("Referenced-only media (" + str(len(referencedOnlyMedia)) + "):")
print(referencedOnlyMedia)

#print(db.getMediaByRatingRange(80, 100))
#print(db.getAllMediaSortedByNumVotes())

stat = Statistics(db)
stat.printYearlyAverages()


