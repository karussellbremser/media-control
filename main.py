from media import Media
from dbcontrol import DBControl
from scrapelocal import ScrapeLocal
from scrapeimdboffline import ScrapeIMDbOffline

db = DBControl(':memory:')
db.createMovieDB()

scrape = ScrapeLocal(r"Y:", db)
mediaList = scrape.scrapeLocalComplete()
#print(db.getAllMovies())
#print(db.getMoviesByYearRange(1992, 1992))

mediaDict = {}
for x in mediaList:
    mediaDict[x.id_imdb] = x

scrapeimdboffline = ScrapeIMDbOffline(r"C:\imdb_datasets")
ratingDict = scrapeimdboffline.parseTitleRatings(mediaDict)
basicsDict = scrapeimdboffline.parseTitleBasics(ratingDict)

db.addMovies(basicsDict)

#print(db.getMoviesByRatingRange(80, 100))
#print(db.getAllMoviesSortedByNumVotes())

print(basicsDict)