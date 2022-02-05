from media import Media
from dbcontrol import DBControl
from scrapelocal import ScrapeLocal
from scrapeimdboffline import ScrapeIMDbOffline
from scrapeimdbonline import ScrapeIMDbOnline

scrape = ScrapeLocal(r"Y:")
mediaList = scrape.scrapeLocalComplete()
#print(db.getAllMedia())
#print(db.getMediaByYearRange(1992, 1992))

scrapeimdbonline = ScrapeIMDbOnline(r"C:\Users\Sebastian\Desktop\scripting\media-control\covers")
#scrapeimdbonline.downloadCovers(mediaList, 50)

mediaDict = {}
for x in mediaList:
    mediaDict[x.imdb_id] = x

scrapeimdboffline = ScrapeIMDbOffline(r"C:\imdb_datasets")
ratingDict = scrapeimdboffline.parseIMDbOfflineFile(mediaDict, 0)
ratingAndBasicsDict = scrapeimdboffline.parseIMDbOfflineFile(ratingDict, 1)

db = DBControl(':memory:')
db.createMediaDB()

db.addMultipleMedia(ratingAndBasicsDict)

print(db.getMediaByGenreAND(["Horror", "Comedy"]))

#print(db.getMediaByRatingRange(80, 100))
#print(db.getAllMediaSortedByNumVotes())


