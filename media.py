import re

from exceptions import LocalLibraryError

class Media:

    # accepted IMDb titleType values for locally-scraped movies/series respectively; part of the
    # fail-loud methodology (see scrapeimdboffline.py/scrapeimdbonline.py), catching when IMDb's
    # own titleType disagrees with the local structural convention a title was parsed under (a
    # files-only folder is expected to be a movie, a dirs-only folder a series -- see
    # ScrapeLocal.__scrapeSingleMedia)
    movieTitleTypes = ["movie", "video", "short", "tvMovie", "tvSpecial", "tvShort"]
    seriesTitleTypes = ["tvSeries", "tvMiniSeries"]

    # accepted IMDb titleType value(s) for episodes. Narrower purpose than the two lists above:
    # episodes are never locally placeholder-guessed (their media row comes from title.episode.tsv
    # via ScrapeIMDbOffline.parseTitleEpisode, not from local folder structure), so this doesn't
    # feed that same local-vs-IMDb consistency check -- it's used to seed title_type_enum, and to
    # catch a different fail-loud case: title.basics.tsv disagreeing with title.episode.tsv about
    # whether a given id is actually an episode.
    episodeTitleTypes = ["tvEpisode"]

    # fixed vocabulary for a mediaVersion's source(s), used by dbcontrol.py to seed
    # source_type_enum/source_role_enum and by sourceparser.py
    source_type_list = ["dvd", "br", "uhd", "web-dl", "webrip", "tv", "vhs", "hifivhs", "ld", "di", "kscape", "hddvd"]
    source_role_list = ["main", "video", "audio", "video_base", "video_dynhdr"]

    def __init__(self, subdir, isSeries, imdbIDInt = None): # this function has become ugly, but python does not offer constructor overloading...
        if subdir != None:
            thisMedia = subdir.rsplit('_', 2)
            
            if len(thisMedia) != 3 or thisMedia[0] == "" or not re.search("^\d{4}$", thisMedia[1]) or not re.search("^tt\d{7,8}$", thisMedia[2]):
                raise LocalLibraryError('Bad format of subdirectory ' + subdir)
            if len(thisMedia[2]) == 10 and thisMedia[2][2] == '0': # 8-digit id's must not start with '0', otherwise id ambiguities may occur
                raise LocalLibraryError('Bad format of imdb id in subdirectory ' + subdir)
            
            self.imdb_id = int(thisMedia[2][2:]) # delete 'tt' at beginning and convert to int
            self.originalTitle = thisMedia[0]
            self.startYear = int(thisMedia[1])
        else:
            self.imdb_id = imdbIDInt
            self.originalTitle = None
            self.startYear = None
        
        self.titleType = None
        if isSeries != None:
            self.titleType = "localMovie" if not isSeries else "localSeries"
        
        self.primaryTitle = None
        self.plotSummary = None # scraped from the title's IMDb main page; only set for locally-owned movies/series, never for episodes
        self.season_number = None # None unless this is an episode (titleType in episodeTitleTypes); None also covers IMDb's own "unnumbered" episodes, never conflated with a real season/episode number (see ScrapeIMDbOffline.parseTitleEpisode)
        self.episode_number = None
        self.series_imdb_id = None # imdb_id of the parent series; None unless this is an episode
        self.intended_order = None # this episode's 1-indexed rank in its season's intended_order.txt, if any -- purely local data (unlike season_number/episode_number), so cleared like language_id/interests once no longer locally owned (see DBControl.removeSingleMedia)
        self.endYear = None
        self.rating_mul10 = None
        self.numVotes = None
        self.releaseMonth = None # only entered manually when necessary
        self.releaseDay = None # only entered manually when necessary
        self.subdir = subdir
        self.interests = [] # list of IMDb interest ids as integers (e.g. 76 for "in0000076"), covering both standard genres and subgenres
        self.language_id = 0 # imdb_interest_id into language_enum; 0 = English (the reserved default id), overwritten if a language-type interest is attached
        self.mediaVersions = []
        self.mediaConnections = []
        self.credits = [] # list of Credit (director/writer/actor); only ever populated for locally-owned movies and episodes (see ScrapeIMDbOnline.scrapeFullCredits), never series
        self.episodes = [] # list of Episode, only ever populated for a locally-scraped series (see ScrapeLocal.__scrapeSingleSeries)
        self.needsOnlineFallback = False # set when locally-owned media is missing from the IMDb offline datasets

    def __str__(self):
        return_str = str(self.imdb_id) + " " + str(self.titleType) + " " + str(self.originalTitle) + " " + str(self.primaryTitle) + " " + str(self.startYear) + " " + str(self.endYear) + " " + str(self.rating_mul10) + " " + str(self.numVotes) + " " + str(self.interests)
        if (len(self.mediaConnections) > 0): return_str += " mediaConnections:"
        for x in self.mediaConnections:
            return_str += str(" " + str(x))
        if (len(self.credits) > 0): return_str += " credits:"
        for x in self.credits:
            return_str += str(" " + str(x))
        return return_str
    
    def getIDString(self):
        return "tt" + str(self.imdb_id).zfill(7)
