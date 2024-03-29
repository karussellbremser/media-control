import sqlite3
from media import Media
from mediaversion import MediaVersion
from mediaconnection import MediaConnection

class DBControl:

    genre_list = ["Action", "Adventure", "Animation", "Biography", "Comedy", "Crime", "Documentary", "Drama", "Family", "Fantasy", "Film-Noir", "Game-Show", "History", "Horror", "Music", "Musical", "Mystery", "News", "Reality-TV", "Romance", "Sci-Fi", "Short", "Sport", "Talk-Show", "Thriller", "War", "Western", "Adult"]
    
    titleType_list = ["movie", "video", "short", "tvMovie", "tvSpecial"]
    
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
            for connection_type in MediaConnection.connectionTypeList:
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
    
    def removeMultipleMedia(self, removedDict):
        for x in removedDict.values():
            self.removeSingleMedia(x)
    
    def removeSingleMedia(self, mediumToRemove):
        with self.conn:
            #1. remove all mediaVersions of mediumToRemove
            self.c.execute("DELETE FROM mediaVersions WHERE imdb_id=?", (mediumToRemove.imdb_id,))
        
            #2. remove and save all connections FROM mediumToRemove to list referencesToRemove
            self.c.execute("SELECT imdb_id, foreign_imdb_id FROM mediaConnections WHERE imdb_id=?", (mediumToRemove.imdb_id,))
            referencesToRemove = self.c.fetchall()
            self.c.execute("DELETE FROM mediaConnections WHERE imdb_id=?", (mediumToRemove.imdb_id,))
        
            #3. check whether there are any connections TO mediumToRemove
            self.c.execute("SELECT * FROM mediaConnections WHERE foreign_imdb_id=?", (mediumToRemove.imdb_id,))
            remainingConnections = self.c.fetchall()
            
            #3a. if yes: only "light-remove" mediumToRemove (remove only subdir)
            if len(remainingConnections) != 0:
                print("Removing " + mediumToRemove.originalTitle + " from DB as local medium (still being referenced)")
                self.c.execute("UPDATE media SET subdir = NULL WHERE imdb_id=?", (mediumToRemove.imdb_id,))
            
            #3b. if no: remove genre and media entries
            else:
                print("Removing " + mediumToRemove.originalTitle + " from DB")
                self.c.execute("DELETE FROM genres WHERE imdb_id=?", (mediumToRemove.imdb_id,))
                self.c.execute("DELETE FROM media WHERE imdb_id=?", (mediumToRemove.imdb_id,))
            
            #4. for all x in list referencesToRemove:
            for x in referencesToRemove:
            
                #4a. if x not in db table media or if subdir NOT EMPTY: continue
                self.c.execute("SELECT imdb_id, originalTitle, subdir FROM media WHERE imdb_id=?", (x[1],))
                mediumData = self.c.fetchall()
                if len(mediumData) == 0 or mediumData[0][2] != None:
                    continue
                
                #4b. check whether there are any connections TO x
                self.c.execute("SELECT * FROM mediaConnections WHERE foreign_imdb_id=?", (x[1],))
                remainingConnections = self.c.fetchall()
                
                #4b1. if yes: continue
                if len(remainingConnections) != 0:
                    continue
                
                #4b2. if no: remove genre and media entries
                else:
                    print("Removing referenced medium " + mediumData[0][1] + " from DB")
                    self.c.execute("DELETE FROM genres WHERE imdb_id=?", (x[1],))
                    self.c.execute("DELETE FROM media WHERE imdb_id=?", (x[1],))
            
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
            self.c.execute("SELECT originalTitle FROM (SELECT * FROM media WHERE media.subdir IS NOT NULL) WHERE startYear=?", (startYear,))
            return(self.c.fetchall())
            
    def getMediaByYearRange(self, yearFrom, yearTo):
        with self.conn:
            self.c.execute("SELECT originalTitle FROM (SELECT * FROM media WHERE media.subdir IS NOT NULL) WHERE startYear BETWEEN ? AND ?", (yearFrom, yearTo))
            return(self.c.fetchall())
    
    def getMediaByRatingRange(self, ratingFrom, ratingTo):
        with self.conn:
            self.c.execute("SELECT originalTitle FROM (SELECT * FROM media WHERE media.subdir IS NOT NULL) WHERE rating_mul10 BETWEEN ? AND ?", (ratingFrom, ratingTo))
            return(self.c.fetchall())
    
    def getAllMediaSortedByRating(self):
        with self.conn:
            self.c.execute("SELECT originalTitle, rating_mul10, numVotes FROM (SELECT * FROM media WHERE media.subdir IS NOT NULL) WHERE rating_mul10 ORDER BY rating_mul10 DESC")
            return(self.c.fetchall())
    
    def getAllMediaSortedByNumVotes(self):
        with self.conn:
            self.c.execute("SELECT originalTitle, rating_mul10, numVotes FROM (SELECT * FROM media WHERE media.subdir IS NOT NULL) WHERE rating_mul10 ORDER BY numVotes DESC")
            return(self.c.fetchall())
    
    def getAllMediaSortedByRating(self):
        with self.conn:
            self.c.execute("SELECT originalTitle, rating_mul10, numVotes FROM (SELECT * FROM media WHERE media.subdir IS NOT NULL) WHERE rating_mul10 ORDER BY startYear DESC")
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
    
    def getLocalMediaByGenreAND(self, genreNameList):
        with self.conn:
            if len(genreNameList) not in range(1, 4):
                raise SyntaxError('illegal length of genreNameList: ' + len(genreNameList))
            sqlStatement = "SELECT localMedia.originalTitle, localMedia.rating_mul10, localMedia.numVotes FROM (SELECT * FROM media WHERE media.subdir IS NOT NULL) localMedia INNER JOIN genres ON localMedia.imdb_id = genres.imdb_id WHERE genres.genre_id in ("
            first = True
            for genreName in genreNameList:
                if not first:
                    sqlStatement += ","
                first = False
                sqlStatement += str(self.__getGenreIDByGenreName(genreName))
            sqlStatement += ") GROUP BY genres.imdb_id HAVING count(distinct genres.genre_id)=" + str(len(genreNameList)) + " ORDER BY localMedia.rating_mul10 DESC"
            self.c.execute(sqlStatement)
            return(self.c.fetchall())
    
    def __getGenreIDByGenreName(self, genre_name):
        with self.conn:
            self.c.execute("SELECT genre_id FROM genre_enum WHERE genre_name=?", (genre_name,))
            genre_id = self.c.fetchone()
            if not genre_id or not genre_id[0]:
                raise SyntaxError('unknown genre ' + genre_name)
            return(genre_id[0])
    
    def __getGenreNameByGenreID(self, genre_id):
        with self.conn:
            self.c.execute("SELECT genre_name FROM genre_enum WHERE genre_id=?", (genre_id,))
            genre_name = self.c.fetchone()
            if not genre_name or not genre_name[0]:
                raise SyntaxError('unknown genre ID ' + str(genre_id))
            return(genre_name[0])
    
    def __getTitleTypeIDByTitleTypeName(self, titleType_name):
        with self.conn:
            self.c.execute("SELECT titleType_id FROM titleType_enum WHERE titleType_name=?", (titleType_name,))
            titleType_id = self.c.fetchone()
            if not titleType_id or not titleType_id[0]:
                raise SyntaxError('unknown titleType ' + titleType_name)
            return(titleType_id[0])
    
    def __getTitleTypeNameByTitleTypeID(self, titleType_id):
        with self.conn:
            self.c.execute("SELECT titleType_name FROM titleType_enum WHERE titleType_id=?", (titleType_id,))
            titleType_name = self.c.fetchone()
            if not titleType_name or not titleType_name[0]:
                raise SyntaxError('unknown titleType ID ' + str(titleType_id))
            return(titleType_name[0])
    
    def __getConnectionTypeIDByConnectionTypeName(self, connectionType_name):
        with self.conn:
            self.c.execute("SELECT connection_type_id FROM connection_type_enum WHERE connection_type_name=?", (connectionType_name,))
            connection_type_id = self.c.fetchone()
            if not connection_type_id or not connection_type_id[0]:
                raise SyntaxError('unknown connection type ' + connectionType_name)
            return(connection_type_id[0])
    
    def __getConnectionTypeNameByConnectionTypeID(self, connectionType_id):
        with self.conn:
            self.c.execute("SELECT connection_type_name FROM connection_type_enum WHERE connection_type_id=?", (connectionType_id,))
            connection_type_name = self.c.fetchone()
            if not connection_type_name or not connection_type_name[0]:
                raise SyntaxError('unknown connection type ' + str(connectionType_id))
            return(connection_type_name[0])
    
    def determineNewlyAddedMedia(self, mediaDict):
        newlyAddedDict = {}
        with self.conn:
            for medium in mediaDict.values():
                self.c.execute("SELECT originalTitle, subdir FROM media WHERE imdb_id = ?", (medium.imdb_id,)) # need to get originalTitle as well, as otherwise no NULL subdirs will be returned
                data = self.c.fetchall()
                if len(data) == 0 or data[0][1] == None:
                    newlyAddedDict[medium.imdb_id] = medium
        return newlyAddedDict
    
    def determineLocallyRemovedMedia(self, mediaDict):
        removedDict = {}
        with self.conn:
            self.c.execute("SELECT imdb_id, originalTitle FROM media WHERE media.subdir IS NOT NULL")
            data = self.c.fetchall()
            for db_medium in data:
                if db_medium[0] not in mediaDict:
                    removedMedium = Media(None, None, db_medium[0])
                    removedMedium.originalTitle = db_medium[1]
                    removedDict[removedMedium.imdb_id] = removedMedium
        return removedDict
    
    def getReferencedOnlyMedia(self):
        with self.conn:
            self.c.execute("SELECT originalTitle, startYear, rating_mul10, numVotes FROM media WHERE subdir IS NULL ORDER BY numVotes DESC")
            return(self.c.fetchall())
    
    def getLocalMovieObjects(self):
        resultDict = {}
        with self.conn:
            self.c.execute("SELECT * FROM media WHERE subdir IS NOT NULL")
            dbResult = self.c.fetchall()
            for dbRow in dbResult:
                resultDict[dbRow[0]] = self.__getMovieObjectFromDBRow(dbRow)
        return resultDict
    
    def __getMovieObjectFromDBRow(self, dbRow):
        # imdb_id, titleType_id, originalTitle, primaryTitle, startYear, endYear, rating_mul10, numVotes, releaseMonth, releaseDay, subdir
        mediaObject = Media(None, None, dbRow[0])
        mediaObject.originalTitle = dbRow[2]
        mediaObject.primaryTitle = dbRow[3]
        mediaObject.startYear = dbRow[4]
        mediaObject.endYear = dbRow[5]
        mediaObject.rating_mul10 = dbRow[6]
        mediaObject.numVotes = dbRow[7]
        mediaObject.releaseMonth = dbRow[8]
        mediaObject.releaseDay = dbRow[9]
        mediaObject.subdir = dbRow[10]
        mediaObject.titleType = self.__getTitleTypeNameByTitleTypeID(dbRow[1])
        mediaObject.genres = self.__getGenreNameList(dbRow[0])
        mediaObject.mediaVersions = self.__getMediaVersionList(dbRow[0])
        mediaObject.mediaConnections = self.__getMediaConnectionsList(dbRow[0])
        return mediaObject
    
    def __getGenreNameList(self, imdbID):
        with self.conn:
            self.c.execute("SELECT genre_id FROM genres WHERE imdb_id=?", (imdbID,))
            dbResult = self.c.fetchall()
            genreList = []
            for genre_id in dbResult:
                genreList.append(self.__getGenreNameByGenreID(genre_id[0]))
            return genreList
    
    def __getMediaVersionList(self, imdbID):
        with self.conn:
            self.c.execute("SELECT * FROM mediaVersions WHERE imdb_id=?", (imdbID,))
            dbResult = self.c.fetchall()
            resultList = []
            for mediaVersionRow in dbResult:
                resultList.append(MediaVersion(mediaVersionRow[1], mediaVersionRow[2], mediaVersionRow[3]))
            return resultList
    
    def __getMediaConnectionsList(self, imdbID):
        with self.conn:
            self.c.execute("SELECT * FROM mediaConnections WHERE imdb_id=?", (imdbID,))
            dbResult = self.c.fetchall()
            resultList = []
            for mediaConnectionRow in dbResult:
                resultList.append(MediaConnection(mediaConnectionRow[1], self.__getConnectionTypeNameByConnectionTypeID(mediaConnectionRow[2])))
            return resultList
    
    def getAllMovieObjects(self):
        resultDict = {}
        with self.conn:
            self.c.execute("SELECT * FROM media")
            dbResult = self.c.fetchall()
            for dbRow in dbResult:
                resultDict[dbRow[0]] = self.__getMovieObjectFromDBRow(dbRow)
        return resultDict
    
    
    
    
    