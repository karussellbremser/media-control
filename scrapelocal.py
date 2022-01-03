import sys, os
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
        currentMovie = Movie(subdir)
        
        mkv_files, sources_file, versions_exists = self.__checkMovieFilenames(subdir, files)
        
        ### TODO: parse source and version files
        
        self.db.addMovie(currentMovie)
    
    def __scrapeSingleSeries(self, subdir): # TBD
        return
    
    def __complDirPath(self, subdir):
        return(self.rootdir + '\\' + subdir)
        
    def __checkMovieFilenames(self, subdir, files): # returns mkv_files, sources_file, versions_exists
        # rules:
        # - .torrent files are ignored
        # - check[#].txt files are ignored
        # - src-[...].txt or sources.txt must exist once
        # - 1 or more .mkv files must exist
        # - versions.txt may exist. if > 1 .mkv file exists, versions.txt must exist
        # - no other files must exist
        
        mkv_files = []
        sources_file = ""
        versions_exists = False
        
        for file in files:
            file_split = file.rsplit('.', 1)
            if len(file_split) != 2:
                raise SyntaxError('Bad content of subdirectory ' + subdir + " in file " + file)
            
            if file_split[1] == "torrent": # torrent file
                continue
            elif file_split[1] == "txt":
                if file_split[0].startswith("check"): # check file
                    continue
                elif file_split[0] == "sources" or file_split[0].startswith("src-"): # sources file
                    if sources_file != "":
                        raise SyntaxError('Bad content of subdirectory ' + subdir + " in file " + file)
                    sources_file = file
                elif file_split[0] == "versions": # versions file
                    versions_exists = True
                else:
                    raise SyntaxError('Bad content of subdirectory ' + subdir + " in file " + file)
            elif file_split[1] == "mkv": # mkv files
                mkv_files.append(file)
            else:
                raise SyntaxError('Bad content of subdirectory ' + subdir + " in file " + file)
            
        if sources_file == "" or len(mkv_files) == 0 or (len(mkv_files) > 1 and versions_exists == False):
            raise SyntaxError('Bad content of subdirectory ' + subdir)
        
        return mkv_files, sources_file, versions_exists
