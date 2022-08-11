import sys, os, re
from media import Media
from mediaversion import MediaVersion

class ScrapeLocal:

    def __init__ (self, rootdir):
        self.rootdir = rootdir

    def scrapeLocalComplete(self):
        root, dirs, files = next(os.walk(self.rootdir))
        
        mediaDict = {}
        
        for subdir in dirs:
            if "!" in subdir or subdir == "#recycle": #skip 'in progress' directories and trash bin
                continue
            currentMedia = self.__scrapeSingleMedia(subdir)
            if currentMedia != None:
                mediaDict[currentMedia.imdb_id] = currentMedia
        
        return mediaDict
            
    def __scrapeSingleMedia(self, subdir):
        root, dirs, files = next(os.walk(self.__complDirPath(subdir)))
        
        if len(dirs) == 0:
            return self.__scrapeSingleMovie(subdir, files)
        elif len(files) == 0:
            return self.__scrapeSingleSeries(subdir)
        else:
            raise SyntaxError('Bad content of subdirectory ' + subdir)
    
    def __scrapeSingleMovie(self, subdir, files):
        currentMovie = Media(subdir, False)
        
        mkv_files, sources_file, versions_exists = self.__checkMovieFilenames(subdir, files)
        
        src_dict = self.__parseDictFile(subdir, sources_file)
        self.__checkSrcDict(subdir, src_dict)
        
        if versions_exists:
            versions_dict = self.__parseDictFile(subdir, "versions.txt")
        
        for mkv_file in mkv_files:
            if mkv_file in src_dict:
                src = src_dict[mkv_file]
            elif "OTHER" in src_dict:
                src = src_dict["OTHER"]
            else:
                raise SyntaxError('Bad source file in subdirectory ' + subdir)
            
            if not versions_exists:
                version = None
            elif mkv_file in versions_dict:
                version = versions_dict[mkv_file]
            elif "OTHER" in versions_dict:
                version = versions_dict["OTHER"]
            else:
                raise SyntaxError('Bad versions file in subdirectory ' + subdir)
            
            currentMovie.mediaVersions.append(MediaVersion(mkv_file, src, version))
            
        
        return currentMovie
    
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
            return {"OTHER": dictFile[:-4]} # source identifier from filename minus ".txt" at end
    
        with open(pathToFile, "r", encoding="utf8") as f:
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
    
    def __checkSrcDict(self, subdir, srcDict):
        singleMatch = "((dvd|br|uhd)-(\d+|ger)(-(corrected|downmixed|core|bl))?|(WEB-DL|WEBRip)(-(AMZN|NF|BCORE|HULU|TUBI|iT|DSNP|VMEO|YT|JOYN|HMAX))?|TVRip)"
        doubleMatch = singleMatch + "-" + singleMatch
        tripleMatch = doubleMatch + "-" + singleMatch
        for x in srcDict.values():
            if not re.search("^(src-" + singleMatch + "|src-((dynhdr)?hybrid|fanres)-" + doubleMatch + "|src-hybrid-dynhdrhybrid-" + tripleMatch + ")$", x):
                raise SyntaxError("Illegal src string '" + x + "' in subdirectory " + subdir)
        
        
        
    