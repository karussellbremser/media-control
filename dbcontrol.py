import sqlite3
from media import Media

class DBControl:

    genre_list = ["Action", "Adventure", "Animation", "Biography", "Comedy", "Crime", "Documentary", "Drama", "Family", "Fantasy", "Film-Noir", "Game-Show", "History", "Horror", "Music", "Musical", "Mystery", "News", "Reality-TV", "Romance", "Sci-Fi", "Short", "Sport", "Talk-Show", "Thriller", "War", "Western"]
    
    titleType_list = ["movie", "video", "short", "tvMovie"]
    
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
            imdb_id integer NOT NULL,
            titleType_id integer NOT NULL,
            originalTitle text NOT NULL,
            primaryTitle text NOT NULL,
            startYear integer NOT NULL,
            endYear integer,
            rating_mul10 integer NOT NULL,
            numVotes integer NOT NULL,
            PRIMARY KEY (imdb_id)
            )""")
            self.c.execute("""CREATE TABLE genres (
            imdb_id integer NOT NULL,
            genre_id integer NOT NULL,
            PRIMARY KEY (imdb_id, genre_id)
            )""")
            self.c.execute("""CREATE TABLE genre_enum (
            genre_id integer NOT NULL,
            genre_name text NOT NULL UNIQUE,
            PRIMARY KEY (genre_id)
            )""")
            i = 1
            for genre in self.genre_list:
                self.c.execute("INSERT INTO genre_enum VALUES (?, ?)", (i, genre))
                i += 1
            self.c.execute("""CREATE TABLE titleType_enum (
            titleType_id integer NOT NULL,
            titleType_name text NOT NULL UNIQUE,
            PRIMARY KEY (titleType_id)
            )""")
            i = 1
            for titleType in self.titleType_list:
                self.c.execute("INSERT INTO titleType_enum VALUES (?, ?)", (i, titleType))
                i += 1

    def addSingleMedia(self, thisMedia):
        if not isinstance(thisMedia, Media):
            raise RuntimeError('no media object')
        with self.conn:
            self.c.execute("INSERT INTO media VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (thisMedia.imdb_id, self.__getTitleTypeIDByTitleTypeName(thisMedia.titleType), thisMedia.originalTitle, thisMedia.primaryTitle, thisMedia.startYear, thisMedia.endYear, thisMedia.rating_mul10, thisMedia.numVotes))
            for genre_name in thisMedia.genres:
                self.c.execute("INSERT INTO genres VALUES (?, ?)", (thisMedia.imdb_id, self.__getGenreIDByGenreName(genre_name)))
            
    def addMultipleMedia(self, mediaDict):
        for x in mediaDict.values():
            self.addSingleMedia(x)
            
    def getAllMediaTitles(self):
        with self.conn:
            self.c.execute("SELECT originalTitle FROM media")
            return(self.c.fetchall())
        
    def getAllMediaIDs(self):
        with self.conn:
            self.c.execute("SELECT imdb_id FROM media")
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
    
    def getMediaByGenre(self, genre_name):
        with self.conn:
            self.c.execute("SELECT media.originalTitle, media.rating_mul10, media.numVotes FROM media INNER JOIN genres ON media.imdb_id = genres.imdb_id WHERE genres.genre_id=? ORDER BY media.rating_mul10 DESC", (self.__getGenreIDByGenreName(genre_name),))
            return(self.c.fetchall())
    
    def __getGenreIDByGenreName(self, genre_name):
        with self.conn:
            self.c.execute("SELECT genre_id FROM genre_enum WHERE genre_name=?", (genre_name,))
            genre_id = self.c.fetchone()
            if not genre_id or not genre_id[0]:
                raise SyntaxError('unknown genre ' + genre_name)
            return(genre_id[0])
    
    def __getTitleTypeIDByTitleTypeName(self, titleType_name):
        with self.conn:
            self.c.execute("SELECT titleType_id FROM titleType_enum WHERE titleType_name=?", (titleType_name,))
            titleType_id = self.c.fetchone()
            if not titleType_id or not titleType_id[0]:
                raise SyntaxError('unknown titleType ' + titleType_name)
            return(titleType_id[0])
            