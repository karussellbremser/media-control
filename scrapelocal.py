import sys, os, re
from movie import Movie
from dbcontrol import DBControl

class ScrapeLocal:

    def __init__ (self, rootdir, db):
        self.rootdir = rootdir
        self.db = db

    def scrapeLocalComplete(self):
        root, dirs, files = next(os.walk(self.rootdir))
        
        for subdir in dirs:
            if "!" in subdir or subdir == "#recycle": #skip 'in progress' directories and trash bin
                continue
            self.__scrapeSingleMovieOrSeries(subdir)
            
    def __scrapeSingleMovieOrSeries(self, subdir):
        root, dirs, files = next(os.walk(self.__complDirPath(subdir)))
        
        if len(dirs) == 0:
            self.__scrapeSingleMovie(subdir, files)
        elif len(files) == 0:
            self.__scrapeSingleSeries(subdir)
        else:
            raise SyntaxError('Bad content of subdirectory ' + subdir)
    
    def __scrapeSingleMovie(self, subdir, files):
        currentMovie = self.__getMovieObjFromSubdir(subdir)
        currentMovie.movietype = 1
        
        #TBD all checks
        
        self.db.addMovie(currentMovie)
    
    def __scrapeSingleSeries(self, subdir): # TBD
        return
    
    def __complDirPath(self, subdir):
        return(self.rootdir + '\\' + subdir)
    
    def __getMovieObjFromSubdir(self, subdir):
        thisMovie = subdir.rsplit('_', 2)
        
        if len(thisMovie) != 3 or thisMovie[0] == "" or not re.search("^\d{4}$", thisMovie[1]) or not re.search("^tt\d{7,8}$", thisMovie[2]):
            raise SyntaxError('Bad format of subdirectory ' + subdir)
        
        return Movie(thisMovie[2], thisMovie[0], int(thisMovie[1]))
