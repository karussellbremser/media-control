from movie import Movie
from dbcontrol import DBControl
from scrapelocal import ScrapeLocal

db = DBControl(':memory:')
db.createMovieDB()

scrape = ScrapeLocal(r"Y:", db)
scrape.scrapeLocalComplete()
# print(db.getAllMovies())
print(db.getMoviesByYearRange(1992, 1992))
