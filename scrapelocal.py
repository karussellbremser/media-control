import sys, os, re
from movie import Movie
from dbcontrol import DBControl

class ScrapeLocal:

    def __init__ (self, rootdir, db):
        self.rootdir = rootdir
        self.db = db

    def scrapeLocalComplete(self):
        root, dirs, files = next(os.walk(self.rootdir))
        
        for directory in dirs:
            if "!" in directory or directory == "#recycle": #skip 'in progress' directories and trash bin
                continue
            currentMovie = directory.rsplit('_', 2)
            if len(currentMovie) != 3 or currentMovie[0] == "" or not re.search("^\d{4}$", currentMovie[1]) or not re.search("^tt\d{7,8}$", currentMovie[2]):
                raise SyntaxError('Bad format of directory ' + directory)
            
            self.db.addMovie(Movie(currentMovie[2], currentMovie[0], currentMovie[1], 0)) # movie type still TBD