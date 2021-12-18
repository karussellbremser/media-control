import sqlite3

class DBControl:
    
    DB_LOCATION = ':memory:' # in RAM for testing purposes
    
    def __init__(self):
        """Initialize db class variables"""
        self.conn = sqlite3.connect(DBControl.DB_LOCATION)
        self.c = self.conn.cursor()

    def close(self):
        """close sqlite3 connection"""
        self.conn.close()
    
    def createMovieDB():
        with self.conn:
            c.execute("""CREATE TABLE movies (
            id_imdb text,
            name text,
            year integer,
            seriestype integer
            )""")

    def addMovie(movie):
        with self.conn:
            c.execute("INSERT INTO movies VALUES (?, ?, ?, ?)", (movie.id_imdb, movie.name, movie.year, movie.seriestype))
            
    def getAllMovies():
        with self.conn:
            c.execute("SELECT * FROM movies")
            return(c.fetchall())