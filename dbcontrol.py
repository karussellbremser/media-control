import sqlite3
from movie import Movie

class DBControl:
    
    def __init__(self, dbLocation):
        """Initialize db class variables"""
        self.conn = sqlite3.connect(dbLocation)
        self.c = self.conn.cursor()

    def close(self):
        """close sqlite3 connection"""
        self.conn.close()
    
    def createMovieDB(self):
        with self.conn:
            self.c.execute("""CREATE TABLE movies (
            id_imdb text NOT NULL,
            name text NOT NULL,
            year integer NOT NULL,
            rating_mul10 integer NOT NULL,
            numVotes integer NOT NULL,
            PRIMARY KEY (id_imdb)
            )""")

    def addMovie(self, thismovie):
        if not isinstance(thismovie, Movie):
            raise RuntimeError('no movie object')
        with self.conn:
            self.c.execute("INSERT INTO movies VALUES (?, ?, ?, ?, ?)", (thismovie.id_imdb, thismovie.name, thismovie.year, thismovie.rating_mul10, thismovie.numVotes))
            
    def addMovies(self, movieList):
        for x in movieList:
            self.addMovie(x)
            
    def getAllMovieNames(self):
        with self.conn:
            self.c.execute("SELECT name FROM movies")
            return(self.c.fetchall())
        
    def getAllMovieIDs(self):
        with self.conn:
            self.c.execute("SELECT id_imdb FROM movies")
            return(self.c.fetchall())
    
    def getMoviesByYear(self, year):
        with self.conn:
            self.c.execute("SELECT name FROM movies WHERE year=?", (year,))
            return(self.c.fetchall())
            
    def getMoviesByYearRange(self, yearFrom, yearTo):
        with self.conn:
            self.c.execute("SELECT name FROM movies WHERE year BETWEEN ? AND ?", (yearFrom, yearTo))
            return(self.c.fetchall())
    
    def getMoviesByRatingRange(self, ratingFrom, ratingTo):
        with self.conn:
            self.c.execute("SELECT name FROM movies WHERE rating_mul10 BETWEEN ? AND ?", (ratingFrom, ratingTo))
            return(self.c.fetchall())
    
    def getAllMoviesSortedByRating(self):
        with self.conn:
            self.c.execute("SELECT name, rating_mul10, numVotes FROM movies WHERE rating_mul10 ORDER BY rating_mul10 DESC")
            return(self.c.fetchall())
    
    def getAllMoviesSortedByNumVotes(self):
        with self.conn:
            self.c.execute("SELECT name, rating_mul10, numVotes FROM movies WHERE rating_mul10 ORDER BY numVotes DESC")
            return(self.c.fetchall())
            