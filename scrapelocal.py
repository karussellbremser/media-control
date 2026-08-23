import sys, os, re
from media import Media
from mediaversion import MediaVersion
from episode import Episode
from exceptions import LocalLibraryError

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
            raise LocalLibraryError('Bad content of subdirectory ' + subdir)
    
    def __scrapeSingleMovie(self, subdir, files):
        currentMovie = Media(subdir, False)
        
        mkv_files, sources_file, versions_exists = self.__checkMovieFilenames(subdir, files)
        
        src_dict = self.__parseDictFile(subdir, sources_file)
        if versions_exists:
            versions_dict = self.__parseDictFile(subdir, "versions.txt")
        
        for mkv_file in mkv_files:
            if mkv_file in src_dict:
                src = src_dict[mkv_file]
            elif "OTHER" in src_dict:
                src = src_dict["OTHER"]
            else:
                raise LocalLibraryError('Bad source file in subdirectory ' + subdir)
            
            if not versions_exists:
                version = None
            elif mkv_file in versions_dict:
                version = versions_dict[mkv_file]
            elif "OTHER" in versions_dict:
                version = versions_dict["OTHER"]
            else:
                raise LocalLibraryError('Bad versions file in subdirectory ' + subdir)
            
            currentMovie.mediaVersions.append(MediaVersion(mkv_file, src, version))
            
        
        return currentMovie
    
    def __scrapeSingleSeries(self, subdir):
        currentSeries = Media(subdir, True)

        root, seasonDirs, files = next(os.walk(self.__complDirPath(subdir)))
        # files is already known to be empty here -- __scrapeSingleMedia only routes a subdir here
        # when it contains no files directly, only subdirectories

        for seasonDir in seasonDirs:
            self.__scrapeSingleSeason(currentSeries, subdir, seasonDir)

        return currentSeries

    def __scrapeSingleSeason(self, currentSeries, subdir, seasonDir):
        seasonMatch = re.fullmatch(r"S(\d+)", seasonDir)
        if not seasonMatch:
            raise LocalLibraryError('Bad season folder name ' + seasonDir + ' in subdirectory ' + subdir)
        season_number = int(seasonMatch.group(1))

        seasonPath = os.path.join(subdir, seasonDir)
        root, dirs, files = next(os.walk(self.__complDirPath(seasonPath)))
        if len(dirs) != 0:
            raise LocalLibraryError('Bad content of season folder ' + seasonPath)

        mkv_files, sources_file, versions_exists = self.__checkSeasonFilenames(subdir, seasonDir, files)

        src_dict = self.__parseDictFile(seasonPath, sources_file)
        if versions_exists:
            versions_dict = self.__parseDictFile(seasonPath, "versions.txt")

        # group this season's files by episode number; each mkv_file's suffix (the part between
        # SxxExx and .mkv, if any) is either a version name (looked up in versions_dict below) or
        # an "Intro"/"IntroN" special-version marker, exempt from needing a versions.txt entry
        episodeFiles = {}
        for mkv_file in mkv_files:
            filenameMatch = re.fullmatch(r"(.+)_S(\d+)E(\d+)(?:_(.+))?", mkv_file[:-4])
            if not filenameMatch:
                raise LocalLibraryError('Bad episode filename ' + mkv_file + ' in season folder ' + seasonPath)
            file_season_number = int(filenameMatch.group(2))
            episode_number = int(filenameMatch.group(3))
            suffix = filenameMatch.group(4)
            if file_season_number != season_number:
                raise LocalLibraryError('Episode filename ' + mkv_file + ' does not match season folder ' + seasonPath)
            episodeFiles.setdefault(episode_number, []).append((mkv_file, suffix))

        for episode_number, fileList in episodeFiles.items():
            nonIntroCount = sum(1 for _, suffix in fileList if not (suffix and re.fullmatch(r"Intro\d*", suffix)))
            if nonIntroCount > 1 and not versions_exists:
                raise LocalLibraryError('Episode S' + str(season_number) + 'E' + str(episode_number) + ' in season folder ' + seasonPath + ' has multiple versions but no versions.txt')

            mediaVersions = []
            for mkv_file, suffix in fileList:
                if mkv_file in src_dict:
                    src = src_dict[mkv_file]
                elif "OTHER" in src_dict:
                    src = src_dict["OTHER"]
                else:
                    raise LocalLibraryError('Bad source file in season folder ' + seasonPath)

                isIntro = bool(suffix) and re.fullmatch(r"Intro\d*", suffix)
                if isIntro:
                    version = suffix
                elif nonIntroCount == 1:
                    # this episode's lone non-Intro file needs no disambiguation, regardless of
                    # whether versions.txt exists at all (it may, for some other episode in this
                    # season) -- but respect an explicit entry if the user gave one anyway
                    version = versions_dict.get(mkv_file) if versions_exists else None
                elif mkv_file in versions_dict:
                    version = versions_dict[mkv_file]
                elif "OTHER" in versions_dict:
                    version = versions_dict["OTHER"]
                else:
                    raise LocalLibraryError('Bad versions file in season folder ' + seasonPath)

                mediaVersions.append(MediaVersion(mkv_file, src, version))

            currentSeries.episodes.append(Episode(season_number, episode_number, mediaVersions))

    def __complDirPath(self, subdir):
        return(os.path.join(self.rootdir, subdir))
    
    def __complFilePath(self, subdir, file):
        return(os.path.join(self.__complDirPath(subdir), file))
        
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
                raise LocalLibraryError('Bad content of subdirectory ' + subdir + " in file " + file)
            
            if file_split[1] == "torrent": # torrent file
                continue
            elif file_split[1] == "txt":
                if file_split[0].startswith("check"): # check file
                    continue
                elif file_split[0] == "sources" or file_split[0].startswith("src-"): # sources file
                    if sources_file != "":
                        raise LocalLibraryError('Bad content of subdirectory ' + subdir + " in file " + file)
                    sources_file = file
                elif file_split[0] == "versions": # versions file
                    versions_exists = True
                else:
                    raise LocalLibraryError('Bad content of subdirectory ' + subdir + " in file " + file)
            elif file_split[1] == "mkv": # mkv files
                mkv_files.append(file)
            else:
                raise LocalLibraryError('Bad content of subdirectory ' + subdir + " in file " + file)
            
        if sources_file == "" or len(mkv_files) == 0 or (len(mkv_files) > 1 and versions_exists == False):
            raise LocalLibraryError('Bad content of subdirectory ' + subdir)

        return mkv_files, sources_file, versions_exists

    def __checkSeasonFilenames(self, subdir, seasonDir, files): # returns mkv_files, sources_file, versions_exists
        # same file-type rules as __checkMovieFilenames, except versions.txt isn't mandated just
        # because the season folder has more than one .mkv file overall -- multiple episodes
        # naturally means multiple files; that requirement is instead checked per episode, once
        # files are grouped by episode number (see __scrapeSingleSeason)
        seasonPath = os.path.join(subdir, seasonDir)
        mkv_files = []
        sources_file = ""
        versions_exists = False

        for file in files:
            file_split = file.rsplit('.', 1)
            if len(file_split) != 2:
                raise LocalLibraryError('Bad content of season folder ' + seasonPath + " in file " + file)

            if file_split[1] == "torrent": # torrent file
                continue
            elif file_split[1] == "txt":
                if file_split[0].startswith("check"): # check file
                    continue
                elif file_split[0] == "sources" or file_split[0].startswith("src-"): # sources file
                    if sources_file != "":
                        raise LocalLibraryError('Bad content of season folder ' + seasonPath + " in file " + file)
                    sources_file = file
                elif file_split[0] == "versions": # versions file
                    versions_exists = True
                else:
                    raise LocalLibraryError('Bad content of season folder ' + seasonPath + " in file " + file)
            elif file_split[1] == "mkv": # mkv files
                mkv_files.append(file)
            else:
                raise LocalLibraryError('Bad content of season folder ' + seasonPath + " in file " + file)

        if sources_file == "" or len(mkv_files) == 0:
            raise LocalLibraryError('Bad content of season folder ' + seasonPath)

        return mkv_files, sources_file, versions_exists

    def __parseDictFile(self, subdir, dictFile):
        pathToFile = self.__complFilePath(subdir, dictFile)
        
        if dictFile == "versions.txt":
            isSources = False
        elif dictFile == "sources.txt":
            isSources = True
        else: # source is embedded within filename (allowed format of filename was checked before)
            if not os.stat(pathToFile).st_size == 0: # file must be empty
                raise LocalLibraryError('Bad content of subdirectory ' + subdir + " in file " + dictFile)
            return {"OTHER": dictFile[:-4]} # source identifier from filename minus ".txt" at end
    
        with open(pathToFile, "r", encoding="utf8") as f:
            lines = f.read().splitlines()
            numLines = len(lines)
            
            if numLines == 0: # every remaining dict file must have at least one line
                raise LocalLibraryError('Bad content of subdirectory ' + subdir + " in file " + dictFile)
            elif numLines == 1:
                if isSources: # source files must have at least two lines, since only one source is embedded within file name
                    raise LocalLibraryError('Bad content of subdirectory ' + subdir + " in file " + dictFile)
                if ':' in lines[0] or lines[0] == '': # single-line version files must not have a key and must not be empty
                    raise LocalLibraryError('Bad content of subdirectory ' + subdir + " in file " + dictFile)
                return {"OTHER": lines[0]}
            
            # main loop for all dict files with > 1 line
            resultDict = {}
            for line in lines:
                if line.count(':') == 0 or line == '': # ':' must be present as separator between key and value (first instance only counts as separator) and line must not be empty
                    raise LocalLibraryError('Bad content of subdirectory ' + subdir + " in file " + dictFile)
                lineSplit = line.split(':', 1)
                if lineSplit[0] in resultDict: # no key must be present twice
                    raise LocalLibraryError('Bad content of subdirectory ' + subdir + " in file " + dictFile)
                resultDict[lineSplit[0]] = lineSplit[1]
            return resultDict
        
        
        
    