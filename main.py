from media import Media
from dbcontrol import DBControl
from scrapelocal import ScrapeLocal
from scrapeimdboffline import ScrapeIMDbOffline
from scrapeimdbonline import ScrapeIMDbOnline

scrape = ScrapeLocal(r"Y:")
mediaList = scrape.scrapeLocalComplete()

mediaDict = {}
for x in mediaList:
    mediaDict[x.imdb_id] = x

scrapeimdbonline = ScrapeIMDbOnline(r"C:\Users\Sebastian\Desktop\scripting\media-control\covers", 5)
scrapeimdbonline.downloadCovers(mediaDict, 50)
mediaDict = scrapeimdbonline.parseMediaConnections(mediaDict, 30)

# add media to dict that are not in local library, but are referenced by local media (per IMDb connection)
mediaDictCopy = mediaDict.copy()
for x in mediaDictCopy.values():
    for y in x.mediaConnections:
        if y.foreignIMDbID not in mediaDict:
            mediaDict[y.foreignIMDbID] = Media(None, None, y.foreignIMDbID)

scrapeimdboffline = ScrapeIMDbOffline(scrapeimdbonline, r"C:\imdb_datasets")
mediaDict = scrapeimdboffline.parseTitleRatings(mediaDict)
mediaDict = scrapeimdboffline.parseTitleBasics(mediaDict)

db = DBControl(':memory:')
db.createMediaDB()

db.addMultipleMedia(mediaDict)

print(db.getMediaByGenreAND(["Horror", "Comedy"]))

#print(db.getMediaByRatingRange(80, 100))
#print(db.getAllMediaSortedByNumVotes())


