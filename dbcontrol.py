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
    
    def createMediaDB(self):
        with self.conn:
            self.c.execute("""CREATE TABLE media (
            id_imdb integer NOT NULL,
            titleType text NOT NULL,
            originalTitle text NOT NULL,
            primaryTitle text NOT NULL,
            startYear integer NOT NULL,
            endYear integer,
            rating_mul10 integer NOT NULL,
            numVotes integer NOT NULL,
            PRIMARY KEY (id_imdb)
            )""")
            self.c.execute("""CREATE TABLE genres (
            id_imdb integer NOT NULL,
            genre text NOT NULL,
            PRIMARY KEY (id_imdb, genre)
            )""")

    def addSingleMedia(self, thisMedia):
        if not isinstance(thisMedia, Media):
            raise RuntimeError('no media object')
        with self.conn:
            self.c.execute("INSERT INTO media VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (thisMedia.id_imdb, thisMedia.titleType, thisMedia.originalTitle, thisMedia.primaryTitle, thisMedia.startYear, thisMedia.endYear, thisMedia.rating_mul10, thisMedia.numVotes))
            for genre in thisMedia.genres:
                self.c.execute("INSERT INTO genres VALUES (?, ?)", (thisMedia.id_imdb, genre))
            
    def addMultipleMedia(self, mediaDict):
        for x in mediaDict.values():
            self.addSingleMedia(x)
            
    def getAllMediaTitles(self):
        with self.conn:
            self.c.execute("SELECT originalTitle FROM media")
            return(self.c.fetchall())
        
    def getAllMediaIDs(self):
        with self.conn:
            self.c.execute("SELECT id_imdb FROM media")
            return(self.c.fetchall())
    
    def getMediaByYear(self, startYear):
        with self.conn:
            self.c.execute("SELECT originalTitle FROM media WHERE startYear=?", (startYear,))
            return(self.c.fetchall())
            
    def getMediaByYearRange(self, yearFrom, yearTo):
        with self.conn:
            self.c.execute("SELECT originalTitle FROM media WHERE startYear BETWEEN ? AND ?", (yearFrom, yearTo))
            return(self.c.fetchall())
    
    def getMediaByRatingRange(self, ratingFrom, ratingTo):
        with self.conn:
            self.c.execute("SELECT originalTitle FROM media WHERE rating_mul10 BETWEEN ? AND ?", (ratingFrom, ratingTo))
            return(self.c.fetchall())
    
    def getAllMediaSortedByRating(self):
        with self.conn:
            self.c.execute("SELECT originalTitle, rating_mul10, numVotes FROM media WHERE rating_mul10 ORDER BY rating_mul10 DESC")
            return(self.c.fetchall())
    
    def getAllMediaSortedByNumVotes(self):
        with self.conn:
            self.c.execute("SELECT originalTitle, rating_mul10, numVotes FROM media WHERE rating_mul10 ORDER BY numVotes DESC")
            return(self.c.fetchall())
    
    def getMediaByGenre(self, genre):
        with self.conn:
            self.c.execute("SELECT media.originalTitle, media.rating_mul10, media.numVotes FROM media INNER JOIN genres ON media.id_imdb = genres.id_imdb WHERE genres.genre=? ORDER BY media.rating_mul10 DESC", (genre,))
            return(self.c.fetchall())
            