import sqlite3

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
            id_imdb text,
            name text,
            year integer,
            seriestype integer
            )""")

    def addMovie(self, movie):
        with self.conn:
            self.c.execute("INSERT INTO movies VALUES (?, ?, ?, ?)", (movie.id_imdb, movie.name, movie.year, movie.seriestype))
            
    def getAllMovies(self):
        with self.conn:
            self.c.execute("SELECT name FROM movies")
            return(self.c.fetchall())
    
    def getMoviesByYear(self, year):
        with self.conn:
            self.c.execute("SELECT name FROM movies WHERE year=?", (year,))
            return(self.c.fetchall())
            
    def getMoviesByYearRange(self, yearStart, yearEnd):
        with self.conn:
            self.c.execute("SELECT name FROM movies WHERE year BETWEEN ? AND ?", (yearStart, yearEnd))
            return(self.c.fetchall())
            