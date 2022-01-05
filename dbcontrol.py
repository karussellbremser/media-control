import sqlite3
from media import Media

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
            originalTitle text NOT NULL,
            startYear integer NOT NULL,
            rating_mul10 integer NOT NULL,
            numVotes integer NOT NULL,
            PRIMARY KEY (id_imdb)
            )""")

    def addMovie(self, thismedia):
        if not isinstance(thismedia, Media):
            raise RuntimeError('no media object')
        with self.conn:
            self.c.execute("INSERT INTO movies VALUES (?, ?, ?, ?, ?)", (thismedia.id_imdb, thismedia.originalTitle, thismedia.startYear, thismedia.rating_mul10, thismedia.numVotes))
            
    def addMovies(self, movieDict):
        for x in movieDict.values():
            self.addMovie(x)
            
    def getAllMovieNames(self):
        with self.conn:
            self.c.execute("SELECT originalTitle FROM movies")
            return(self.c.fetchall())
        
    def getAllMovieIDs(self):
        with self.conn:
            self.c.execute("SELECT id_imdb FROM movies")
            return(self.c.fetchall())
    
    def getMoviesByYear(self, startYear):
        with self.conn:
            self.c.execute("SELECT originalTitle FROM movies WHERE startYear=?", (startYear,))
            return(self.c.fetchall())
            
    def getMoviesByYearRange(self, yearFrom, yearTo):
        with self.conn:
            self.c.execute("SELECT originalTitle FROM movies WHERE startYear BETWEEN ? AND ?", (yearFrom, yearTo))
            return(self.c.fetchall())
    
    def getMoviesByRatingRange(self, ratingFrom, ratingTo):
        with self.conn:
            self.c.execute("SELECT originalTitle FROM movies WHERE rating_mul10 BETWEEN ? AND ?", (ratingFrom, ratingTo))
            return(self.c.fetchall())
    
    def getAllMoviesSortedByRating(self):
        with self.conn:
            self.c.execute("SELECT originalTitle, rating_mul10, numVotes FROM movies WHERE rating_mul10 ORDER BY rating_mul10 DESC")
            return(self.c.fetchall())
    
    def getAllMoviesSortedByNumVotes(self):
        with self.conn:
            self.c.execute("SELECT originalTitle, rating_mul10, numVotes FROM movies WHERE rating_mul10 ORDER BY numVotes DESC")
            return(self.c.fetchall())
            