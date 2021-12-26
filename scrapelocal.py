import sys, os, re
from media import Media
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
            self.__scrapeSingleMedia(subdir)
            
    def __scrapeSingleMedia(self, subdir):
        root, dirs, files = next(os.walk(self.__complDirPath(subdir)))
        
        if len(dirs) == 0:
            self.__scrapeSingleMovie(subdir, files)
        elif len(files) == 0:
            self.__scrapeSingleSeries(subdir)
        else:
            raise SyntaxError('Bad content of subdirectory ' + subdir)
    
    def __scrapeSingleMovie(self, subdir, files):
        currentMovie = self.__getMovieObjFromSubdir(subdir)
        currentMovie.mediatype = 1
        
        # TBD all checks
        # rules:
        # - .torrent files are ignored
        # - check[#].txt files are ignored
        # - src-[...].txt or sources.txt must exist once
        # - 1 or more .mkv files must exist
        # - versions.txt may exist. if > 1 .mkv file exists, versions.txt must exist
        # - no other files must exist
        
        self.db.addMovie(currentMovie)
    
    def __scrapeSingleSeries(self, subdir): # TBD
        return
    
    def __complDirPath(self, subdir):
        return(self.rootdir + '\\' + subdir)
    
    def __getMovieObjFromSubdir(self, subdir):
        thisMovie = subdir.rsplit('_', 2)
        
        if len(thisMovie) != 3 or thisMovie[0] == "" or not re.search("^\d{4}$", thisMovie[1]) or not re.search("^tt\d{7,8}$", thisMovie[2]):
            raise SyntaxError('Bad format of subdirectory ' + subdir)
        
        return Media(thisMovie[2], thisMovie[0], int(thisMovie[1]))
