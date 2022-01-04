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
        
        #if versions_exists:
        #    print(subdir)
        #    print(self.__parseDictFile(subdir, "versions.txt"))
        #    print("")
        
        #print(self.__parseDictFile(subdir, sources_file))
        
        self.db.addMovie(currentMovie)
    
    def __scrapeSingleSeries(self, subdir): # TBD
        return
    
    def __complDirPath(self, subdir):
        return(self.rootdir + '\\' + subdir)
    
    def __complFilePath(self, subdir, file):
        return(self.__complDirPath(subdir) + '\\' + file)
        
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
    
    def __parseDictFile(self, subdir, dictFile):
        pathToFile = self.__complFilePath(subdir, dictFile)
        
        if dictFile == "versions.txt":
            isSources = False
        elif dictFile == "sources.txt":
            isSources = True
        else: # source is embedded within filename (allowed format of filename was checked before)
            if not os.stat(pathToFile).st_size == 0: # file must be empty
                raise SyntaxError('Bad content of subdirectory ' + subdir + " in file " + dictFile)
            return {"OTHER": dictFile[4:-4]} # source identifier from filename minus "src-" at beginning and ".txt" at end
    
        with open(pathToFile, "r") as f:
            lines = f.read().splitlines()
            numLines = len(lines)
            
            if numLines == 0: # every remaining dict file must have at least one line
                raise SyntaxError('Bad content of subdirectory ' + subdir + " in file " + dictFile)
            elif numLines == 1:
                if isSources: # source files must have at least two lines, since only one source is embedded within file name
                    raise SyntaxError('Bad content of subdirectory ' + subdir + " in file " + dictFile)
                if ':' in lines[0] or lines[0] == '': # single-line version files must not have a key and must not be empty
                    raise SyntaxError('Bad content of subdirectory ' + subdir + " in file " + dictFile)
                return {"OTHER": lines[0]}
            
            # main loop for all dict files with > 1 line
            resultDict = {}
            for line in lines:
                if line.count(':') != 1 or line == '': # ':' must only be present as separator between key and value and line must not be empty
                    raise SyntaxError('Bad content of subdirectory ' + subdir + " in file " + dictFile)
                lineSplit = line.split(':', 1)
                if lineSplit[0] in resultDict: # no key must be present twice
                    raise SyntaxError('Bad content of subdirectory ' + subdir + " in file " + dictFile)
                resultDict[lineSplit[0]] = lineSplit[1]
            return resultDict
        
        
        
    