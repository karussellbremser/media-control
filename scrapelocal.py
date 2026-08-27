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
        
        media_files, sources_file, versions_exists = self.__checkMovieFilenames(subdir, files)

        src_dict = self.__parseDictFile(subdir, sources_file)
        if versions_exists:
            versions_dict = self.__parseDictFile(subdir, "versions.txt")

        for media_file in media_files:
            if media_file in src_dict:
                src = src_dict[media_file]
            elif "OTHER" in src_dict:
                src = src_dict["OTHER"]
            else:
                raise LocalLibraryError('Bad source file in subdirectory ' + subdir)

            if not versions_exists:
                version = None
            elif media_file in versions_dict:
                version = versions_dict[media_file]
            elif "OTHER" in versions_dict:
                version = versions_dict["OTHER"]
            else:
                raise LocalLibraryError('Bad versions file in subdirectory ' + subdir)

            currentMovie.mediaVersions.append(MediaVersion(media_file, src, version))
            
        
        return currentMovie
    
    def __scrapeSingleSeries(self, subdir):
        currentSeries = Media(subdir, True)

        root, seasonDirs, files = next(os.walk(self.__complDirPath(subdir)))
        # files is already known to be empty here -- __scrapeSingleMedia only routes a subdir here
        # when it contains no files directly, only subdirectories
        if len(seasonDirs) == 0:
            raise LocalLibraryError('Series subdirectory contains no season folders: ' + subdir)

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

        media_files, sources_file, versions_exists, intended_order_file = self.__checkSeasonFilenames(subdir, seasonDir, files)

        if intended_order_file != "" and season_number == 0:
            raise LocalLibraryError('intended_order.txt is not supported in the unnumbered season folder ' + seasonPath)

        src_dict = self.__parseDictFile(seasonPath, sources_file)
        if versions_exists:
            versions_dict = self.__parseDictFile(seasonPath, "versions.txt")

        # group this season's files by episode; each media_file's suffix (the part after the episode
        # identifier and before its extension, if any) is either a version name (looked up in
        # versions_dict below) or an "Intro"/"IntroN" special-version marker, exempt from needing a
        # versions.txt entry. S00 is reserved for IMDb's "unnumbered" episodes (see Episode's
        # docstring / title.episode.tsv's "\N"), whose files embed the episode's own imdb id
        # directly instead of a season/episode number, since there isn't one to encode. The
        # extension is stripped via splitext rather than a fixed-length slice, since media_file may
        # be either a real .mkv or a Kaleidescape .kscape placeholder (different lengths)
        isUnnumbered = (season_number == 0)
        episodeFiles = {}
        for media_file in media_files:
            media_file_stem = os.path.splitext(media_file)[0]
            if isUnnumbered:
                filenameMatch = re.fullmatch(r"(.+)_tt(\d{7,8})(?:_(.+))?", media_file_stem)
                if not filenameMatch:
                    raise LocalLibraryError('Bad unnumbered episode filename ' + media_file + ' in season folder ' + seasonPath)
                episode_id_str = filenameMatch.group(2)
                if len(episode_id_str) == 8 and episode_id_str[0] == '0': # 8-digit id's must not start with '0', matching Media's own subdir parsing
                    raise LocalLibraryError('Bad format of imdb id in filename ' + media_file + ' in season folder ' + seasonPath)
                episode_key = int(episode_id_str)
                suffix = filenameMatch.group(3)
            else:
                filenameMatch = re.fullmatch(r"(.+)_S(\d+)E(\d+)(?:_(.+))?", media_file_stem)
                if not filenameMatch:
                    raise LocalLibraryError('Bad episode filename ' + media_file + ' in season folder ' + seasonPath)
                file_season_number = int(filenameMatch.group(2))
                if file_season_number != season_number:
                    raise LocalLibraryError('Episode filename ' + media_file + ' does not match season folder ' + seasonPath)
                episode_key = int(filenameMatch.group(3))
                suffix = filenameMatch.group(4)
            episodeFiles.setdefault(episode_key, []).append((media_file, suffix))

        # intended_order.txt: a comma-separated permutation of this season's own episode numbers,
        # in artistically-intended watch order (distinct from IMDb's official numbering, which stays
        # the source of truth -- see Episode/Media.intended_order). Optional; intendedOrderMap stays
        # empty when absent, so every episode's intended_order ends up None (see below)
        intendedOrderMap = {}
        if intended_order_file != "":
            with open(self.__complFilePath(seasonPath, intended_order_file), "r", encoding="utf8") as f:
                content = f.read().strip()
            rawValues = content.split(",") if content != "" else []
            parsedOrder = []
            for rawValue in rawValues:
                rawValue = rawValue.strip()
                if not rawValue.isdigit():
                    raise LocalLibraryError('Bad content of season folder ' + seasonPath + " in file " + intended_order_file)
                parsedOrder.append(int(rawValue))
            if len(parsedOrder) != len(episodeFiles) or set(parsedOrder) != set(episodeFiles.keys()):
                raise LocalLibraryError('intended_order.txt in season folder ' + seasonPath +
                                         ' must be an exact permutation of the locally-present episode numbers ' + str(sorted(episodeFiles.keys())))
            for rank, episode_number in enumerate(parsedOrder, start=1):
                intendedOrderMap[episode_number] = rank

        for episode_key, fileList in episodeFiles.items():
            nonIntroCount = sum(1 for _, suffix in fileList if not (suffix and re.fullmatch(r"Intro\d*", suffix)))
            if nonIntroCount > 1 and not versions_exists:
                raise LocalLibraryError('Episode ' + str(episode_key) + ' in season folder ' + seasonPath + ' has multiple versions but no versions.txt')

            mediaVersions = []
            for media_file, suffix in fileList:
                if media_file in src_dict:
                    src = src_dict[media_file]
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
                    version = versions_dict.get(media_file) if versions_exists else None
                elif media_file in versions_dict:
                    version = versions_dict[media_file]
                elif "OTHER" in versions_dict:
                    version = versions_dict["OTHER"]
                else:
                    raise LocalLibraryError('Bad versions file in season folder ' + seasonPath)

                mediaVersions.append(MediaVersion(media_file, src, version))

            if isUnnumbered:
                currentSeries.episodes.append(Episode(None, None, mediaVersions, seasonPath, imdb_id=episode_key))
            else:
                currentSeries.episodes.append(Episode(season_number, episode_key, mediaVersions, seasonPath, intended_order=intendedOrderMap.get(episode_key)))

    def __complDirPath(self, subdir):
        return(os.path.join(self.rootdir, subdir))
    
    def __complFilePath(self, subdir, file):
        return(os.path.join(self.__complDirPath(subdir), file))
        
    def __checkMovieFilenames(self, subdir, files): # returns media_files, sources_file, versions_exists
        # rules:
        # - .torrent files are ignored
        # - check[#].txt files are ignored
        # - src-[...].txt or sources.txt must exist once
        # - 1 or more media files (.mkv, or .kscape for a Kaleidescape-owned title with no local
        #   file at all -- see MediaVersion.isKaleidescapeOnly) must exist
        # - a .kscape file must be empty; it's a placeholder, not real content
        # - versions.txt may exist. if > 1 media file exists, versions.txt must exist
        # - no other files must exist

        media_files = []
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
            elif file_split[1] == "mkv": # real media file
                media_files.append(file)
            elif file_split[1] == "kscape": # Kaleidescape placeholder -- must be empty
                if os.stat(self.__complFilePath(subdir, file)).st_size != 0:
                    raise LocalLibraryError('Bad content of subdirectory ' + subdir + " in file " + file + " (Kaleidescape placeholder must be empty)")
                media_files.append(file)
            else:
                raise LocalLibraryError('Bad content of subdirectory ' + subdir + " in file " + file)

        if sources_file == "" or len(media_files) == 0 or (len(media_files) > 1 and versions_exists == False):
            raise LocalLibraryError('Bad content of subdirectory ' + subdir)

        return media_files, sources_file, versions_exists

    def __checkSeasonFilenames(self, subdir, seasonDir, files): # returns media_files, sources_file, versions_exists, intended_order_file
        # same file-type rules as __checkMovieFilenames (including the .mkv/.kscape media-file
        # split -- a season can freely mix real and Kaleidescape-only episodes, since sources are
        # already resolved per-file), except versions.txt isn't mandated just because the season
        # folder has more than one media file overall -- multiple episodes naturally means multiple
        # files; that requirement is instead checked per episode, once files are grouped by episode
        # number (see __scrapeSingleSeason). intended_order.txt is an optional extra: an
        # artistically-intended watch order, distinct from IMDb's official numbering (see
        # __scrapeSingleSeason for how it's parsed/validated)
        seasonPath = os.path.join(subdir, seasonDir)
        media_files = []
        sources_file = ""
        versions_exists = False
        intended_order_file = ""

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
                elif file_split[0] == "intended_order": # intended watch order file
                    intended_order_file = file
                else:
                    raise LocalLibraryError('Bad content of season folder ' + seasonPath + " in file " + file)
            elif file_split[1] == "mkv": # real media file
                media_files.append(file)
            elif file_split[1] == "kscape": # Kaleidescape placeholder -- must be empty
                if os.stat(self.__complFilePath(seasonPath, file)).st_size != 0:
                    raise LocalLibraryError('Bad content of season folder ' + seasonPath + " in file " + file + " (Kaleidescape placeholder must be empty)")
                media_files.append(file)
            else:
                raise LocalLibraryError('Bad content of season folder ' + seasonPath + " in file " + file)

        if sources_file == "" or len(media_files) == 0:
            raise LocalLibraryError('Bad content of season folder ' + seasonPath)

        return media_files, sources_file, versions_exists, intended_order_file

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
        
        
        
    