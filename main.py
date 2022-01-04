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

id_list = []
for x in mediaList:
    id_list.append(x.id_imdb)

scrapeimdboffline = ScrapeIMDbOffline(r"C:\imdb_datasets")
rating_dict = scrapeimdboffline.parseTitleRatings(id_list)

for x in mediaList:
    rating_and_numVotes = rating_dict[x.id_imdb]
    x.rating_mul10 = int(rating_and_numVotes[0].replace('.',''))
    if x.rating_mul10 < 10 or x.rating_mul10 > 100:
        raise SyntaxError("rating conversion problem")
    x.numVotes = int(rating_and_numVotes[1])

db.addMovies(mediaList)

#print(db.getMoviesByRatingRange(80, 100))
print(db.getAllMoviesSortedByNumVotes())