import sqlite3
from media import Media
from mediaversion import MediaVersion

class DBControl:

    genre_list = ["Action", "Adventure", "Animation", "Biography", "Comedy", "Crime", "Documentary", "Drama", "Family", "Fantasy", "Film-Noir", "Game-Show", "History", "Horror", "Music", "Musical", "Mystery", "News", "Reality-TV", "Romance", "Sci-Fi", "Short", "Sport", "Talk-Show", "Thriller", "War", "Western"]
    
    titleType_list = ["movie", "video", "short", "tvMovie"]
    
    connection_type_list = ["follows", "followed_by", "remake_of", "remade_as", "spin_off", "spin_off_from", "version_of"]
    
    def __init__(self, dbLocation):
        """Initialize db class variables"""
        self.conn = sqlite3.connect(dbLocation)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.c = self.conn.cursor()

    def close(self):
        """close sqlite3 connection"""
        self.conn.close()
    
    def createMediaDB(self):
        with self.conn:
            # media table holds both media present in library and those only linked by IMDb connections. differentiator if medium is actually present is subdir not being NULL
            self.c.execute("""CREATE TABLE media (
            imdb_id integer NOT NULL,
            titleType_id integer NOT NULL,
            originalTitle text NOT NULL,
            primaryTitle text NOT NULL,
            startYear integer NOT NULL,
            endYear integer,
            rating_mul10 integer,
            numVotes integer,
            releaseMonth integer,
            releaseDay integer,
            subdir text UNIQUE,
            PRIMARY KEY (imdb_id),
            FOREIGN KEY (titleType_id)
                REFERENCES titleType_enum (titleType_id)
                    ON UPDATE CASCADE
                    ON DELETE RESTRICT
            )""")
            
            self.c.execute("""CREATE TABLE genres (
            imdb_id integer NOT NULL,
            genre_id integer NOT NULL,
            PRIMARY KEY (imdb_id, genre_id),
            FOREIGN KEY (imdb_id)
                REFERENCES media (imdb_id)
                    ON UPDATE CASCADE
                    ON DELETE CASCADE,
            FOREIGN KEY (genre_id)
                REFERENCES genre_enum (genre_id)
                    ON UPDATE CASCADE
                    ON DELETE CASCADE
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
            
            self.c.execute("""CREATE TABLE mediaVersions (
            imdb_id integer NOT NULL,
            filename text NOT NULL,
            source text NOT NULL,
            version text,
            PRIMARY KEY (imdb_id, version),
            UNIQUE (imdb_id, filename),
            FOREIGN KEY (imdb_id)
                REFERENCES media (imdb_id)
                    ON UPDATE CASCADE
                    ON DELETE CASCADE
            )""")
            
            self.c.execute("""CREATE TABLE mediaConnections (
            imdb_id integer NOT NULL,
            foreign_imdb_id integer NOT NULL,
            connection_type_id integer NOT NULL,
            PRIMARY KEY (imdb_id, foreign_imdb_id, connection_type_id),
            FOREIGN KEY (imdb_id)
                REFERENCES media (imdb_id)
                    ON UPDATE CASCADE
                    ON DELETE CASCADE,
            FOREIGN KEY (foreign_imdb_id)
                REFERENCES media (imdb_id)
                    ON UPDATE CASCADE
                    ON DELETE RESTRICT,
            FOREIGN KEY (connection_type_id)
                REFERENCES connection_type_enum (connection_type_id)
                    ON UPDATE CASCADE
                    ON DELETE RESTRICT
            )""")
            
            self.c.execute("""CREATE TABLE connection_type_enum (
            connection_type_id integer NOT NULL,
            connection_type_name text NOT NULL UNIQUE,
            PRIMARY KEY (connection_type_id)
            )""")
            i = 1
            for connection_type in self.connection_type_list:
                self.c.execute("INSERT INTO connection_type_enum VALUES (?, ?)", (i, connection_type))
                i += 1

    def addSingleMediaWoConnections(self, thisMedia):
        if not isinstance(thisMedia, Media):
            raise RuntimeError('no media object')
        with self.conn:
            self.c.execute("SELECT originalTitle, subdir FROM media WHERE imdb_id = ?", (thisMedia.imdb_id,)) # need to get originalTitle as well, as otherwise no NULL subdirs will be returned
            data = self.c.fetchall()
            if len(data) == 0:
                self.c.execute("INSERT INTO media VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (thisMedia.imdb_id, self.__getTitleTypeIDByTitleTypeName(thisMedia.titleType), thisMedia.originalTitle, thisMedia.primaryTitle, thisMedia.startYear, thisMedia.endYear, thisMedia.rating_mul10, thisMedia.numVotes, thisMedia.releaseMonth, thisMedia.releaseDay, thisMedia.subdir))
            elif data[0][1] == None:
                self.c.execute("UPDATE media SET titleType_id=?, originalTitle=?, primaryTitle=?, startYear=?, endYear=?, rating_mul10=?, numVotes=?, releaseMonth=?, releaseDay=?, subdir=? WHERE imdb_id=?", (self.__getTitleTypeIDByTitleTypeName(thisMedia.titleType), thisMedia.originalTitle, thisMedia.primaryTitle, thisMedia.startYear, thisMedia.endYear, thisMedia.rating_mul10, thisMedia.numVotes, thisMedia.releaseMonth, thisMedia.releaseDay, thisMedia.subdir, thisMedia.imdb_id))
            else:
                raise RuntimeError('already existing media object supposed to be newly added: ' + data[0][0])
            self.c.execute("DELETE FROM genres WHERE imdb_id=?", (thisMedia.imdb_id,)) # delete genre entries for the case of previously existing referenced medium now being newly added
            for genre_name in thisMedia.genres:
                self.c.execute("INSERT INTO genres VALUES (?, ?)", (thisMedia.imdb_id, self.__getGenreIDByGenreName(genre_name)))
            for mediaVersion in thisMedia.mediaVersions:
                self.c.execute("INSERT INTO mediaVersions VALUES (?, ?, ?, ?)", (thisMedia.imdb_id, mediaVersion.filename, mediaVersion.source, mediaVersion.version))
    
    def addSingleMediaConnections(self, thisMedia):
        if not isinstance(thisMedia, Media):
            raise RuntimeError('no media object')
        with self.conn:
            for mediaConnection in thisMedia.mediaConnections:
                self.c.execute("INSERT INTO mediaConnections VALUES (?, ?, ?)", (thisMedia.imdb_id, mediaConnection.foreignIMDbID, self.__getConnectionTypeIDByConnectionTypeName(mediaConnection.connectionType)))
            
    def addMultipleMedia(self, mediaDict): # media and connections must be separated, so that foreign constraints are always fulfilled during db entry
        for x in mediaDict.values():
            self.addSingleMediaWoConnections(x)
        for x in mediaDict.values():
            self.addSingleMediaConnections(x)
            
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
    
    def getMediaByGenreAND(self, genreNameList):
        with self.conn:
            if len(genreNameList) not in range(1, 4):
                raise SyntaxError('illegal length of genreNameList: ' + len(genreNameList))
            sqlStatement = "SELECT media.originalTitle, media.rating_mul10, media.numVotes FROM media INNER JOIN genres ON media.imdb_id = genres.imdb_id WHERE genres.genre_id in ("
            first = True
            for genreName in genreNameList:
                if not first:
                    sqlStatement += ","
                first = False
                sqlStatement += str(self.__getGenreIDByGenreName(genreName))
            sqlStatement += ") GROUP BY genres.imdb_id HAVING count(distinct genres.genre_id)=" + str(len(genreNameList)) + " ORDER BY media.rating_mul10 DESC"
            self.c.execute(sqlStatement)
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
    
    def __getConnectionTypeIDByConnectionTypeName(self, connectionType_name):
        with self.conn:
            self.c.execute("SELECT connection_type_id FROM connection_type_enum WHERE connection_type_name=?", (connectionType_name,))
            connection_type_id = self.c.fetchone()
            if not connection_type_id or not connection_type_id[0]:
                raise SyntaxError('unknown connection type ' + connectionType_name)
            return(connection_type_id[0])
    
    def determineNewlyAddedMedia(self, mediaList):
        newlyAddedList = []
        with self.conn:
            for medium in mediaList:
                self.c.execute("SELECT originalTitle, subdir FROM media WHERE imdb_id = ?", (medium.imdb_id,)) # need to get originalTitle as well, as otherwise no NULL subdirs will be returned
                data = self.c.fetchall()
                if len(data) == 0 or data[0][1] == None:
                    newlyAddedList.append(medium)
        return newlyAddedList
    
    