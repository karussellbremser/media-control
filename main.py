from media import Media
from dbcontrol import DBControl
from scrapelocal import ScrapeLocal
from scrapeimdboffline import ScrapeIMDbOffline


db = DBControl(':memory:')
db.createMediaDB()

scrape = ScrapeLocal(r"Y:", db)
mediaList = scrape.scrapeLocalComplete()
#print(db.getAllMedia())
#print(db.getMediaByYearRange(1992, 1992))

mediaDict = {}
for x in mediaList:
    mediaDict[x.id_imdb] = x

scrapeimdboffline = ScrapeIMDbOffline(r"C:\imdb_datasets")
ratingDict = scrapeimdboffline.parseTitleRatings(mediaDict)
ratingAndBasicsDict = scrapeimdboffline.parseTitleBasics(ratingDict)


db.addMultipleMedia(ratingAndBasicsDict)

print(db.getMediaByGenre("Documentary"))

#print(db.getMediaByRatingRange(80, 100))
#print(db.getAllMediaSortedByNumVotes())


