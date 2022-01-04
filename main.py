from media import Media
from dbcontrol import DBControl
from scrapelocal import ScrapeLocal
from scrapeimdboffline import ScrapeIMDbOffline

db = DBControl(':memory:')
db.createMovieDB()

scrape = ScrapeLocal(r"Y:", db)
scrape.scrapeLocalComplete()
# print(db.getAllMovies())
print(db.getMoviesByYearRange(1992, 1992))

db_id_list = db.getAllMovieIDs()
plain_id_list = []
for x in db_id_list:
    (id_imdb,) = x
    plain_id_list.append(id_imdb)

scrapeimdboffline = ScrapeIMDbOffline(r"C:\imdb_datasets")
print(scrapeimdboffline.parseTitleRatings(plain_id_list))