from media import Media
from dbcontrol import DBControl
from scrapelocal import ScrapeLocal
from scrapeimdboffline import ScrapeIMDbOffline
from scrapeimdbonline import ScrapeIMDbOnline

scrape = ScrapeLocal(r"Y:")
mediaList = scrape.scrapeLocalComplete()
#print(db.getAllMedia())
#print(db.getMediaByYearRange(1992, 1992))

mediaDict = {}
for x in mediaList:
    mediaDict[x.imdb_id] = x

scrapeimdbonline = ScrapeIMDbOnline(r"C:\Users\Sebastian\Desktop\scripting\media-control\covers")
#scrapeimdbonline.downloadCovers(mediaDict, 50)
mediaDict = scrapeimdbonline.parseMediaConnections(mediaDict, 50)

scrapeimdboffline = ScrapeIMDbOffline(r"C:\imdb_datasets")
mediaDict = scrapeimdboffline.parseIMDbOfflineFile(mediaDict, 0)
mediaDict = scrapeimdboffline.parseIMDbOfflineFile(mediaDict, 1)

db = DBControl('myMovieDB.db')
db.createMediaDB()

db.addMultipleMedia(mediaDict)

print(db.getMediaByGenreAND(["Horror", "Comedy"]))

#print(db.getMediaByRatingRange(80, 100))
#print(db.getAllMediaSortedByNumVotes())


