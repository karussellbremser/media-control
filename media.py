import re

class Media:
    
    def __init__(self, subdir, isSeries):
        thisMedia = subdir.rsplit('_', 2)
        
        if len(thisMedia) != 3 or thisMedia[0] == "" or not re.search("^\d{4}$", thisMedia[1]) or not re.search("^tt\d{7,8}$", thisMedia[2]):
            raise SyntaxError('Bad format of subdirectory ' + subdir)
        if len(thisMedia[2]) == 10 and thisMedia[2][2] == '0': # 8-digit id's must not start with '0', otherwise id ambiguities may occur
            raise SyntaxError('Bad format of imdb id in subdirectory ' + subdir)
        
        self.imdb_id = int(thisMedia[2][2:]) # delete 'tt' at beginning and convert to int
        self.titleType = "localMovie" if not isSeries else "localSeries"
        self.originalTitle = thisMedia[0]
        self.primaryTitle = None
        self.startYear = int(thisMedia[1])
        self.endYear = None
        self.rating_mul10 = None
        self.numVotes = None
        self.subdir = subdir
        self.genres = []
        self.mediaVersions = []
    
    def __str__(self):
        return str(self.imdb_id) + " " + str(self.titleType) + " " + str(self.originalTitle) + " " + str(self.primaryTitle) + " " + str(self.startYear) + " " + str(self.endYear) + " " + str(self.rating_mul10) + " " + str(self.numVotes) + " " + str(self.genres)