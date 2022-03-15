from media import Media
from dbcontrol import DBControl
from scrapelocal import ScrapeLocal
from scrapeimdboffline import ScrapeIMDbOffline
from scrapeimdbonline import ScrapeIMDbOnline

scrape = ScrapeLocal(r"Y:")
mediaListOriginal = scrape.scrapeLocalComplete()

db = DBControl('myMovieDB.db')
newMediaList = db.determineNewlyAddedMedia(mediaListOriginal)

mediaDict = {}
for x in newMediaList:
    mediaDict[x.imdb_id] = x

scrapeimdbonline = ScrapeIMDbOnline(r"C:\Users\Sebastian\Desktop\scripting\media-control\covers", 5)
scrapeimdbonline.downloadCovers(mediaDict, 50)
mediaDict = scrapeimdbonline.parseMediaConnections(mediaDict)

# add media to dict that are not in local library, but are referenced by local media (per IMDb connection)
mediaDictOriginal = {}
for x in mediaListOriginal:
    mediaDictOriginal[x.imdb_id] = x
mediaDictCopy = mediaDict.copy()
for x in mediaDictCopy.values():
    for y in x.mediaConnections:
        if y.foreignIMDbID not in mediaDictOriginal:
            mediaDict[y.foreignIMDbID] = Media(None, None, y.foreignIMDbID)

scrapeimdboffline = ScrapeIMDbOffline(scrapeimdbonline, r"C:\imdb_datasets")
mediaDict = scrapeimdboffline.parseTitleRatings(mediaDict)
mediaDict = scrapeimdboffline.parseTitleBasics(mediaDict)

for x in mediaDict.values():
    if x.subdir == None:
        print(x.originalTitle + " " + str(x.startYear))
#for x in mediaDict.values():
#    for y in x.mediaConnections:
#        print(str(x.imdb_id) + " " + str(y))


#db.createMediaDB()

db.addMultipleMedia(mediaDict)

#print(db.getLocalMediaByGenreAND(["Action"]))

print(db.getReferencedOnlyMedia())

#print(db.getMediaByRatingRange(80, 100))
#print(db.getAllMediaSortedByNumVotes())


