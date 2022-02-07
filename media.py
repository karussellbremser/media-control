import re

class Media:
    
    def __init__(self, subdir, isSeries, imdbIDInt = None): # this function has become ugly, but python does not offer constructor overloading...
        if subdir != None:
            thisMedia = subdir.rsplit('_', 2)
            
            if len(thisMedia) != 3 or thisMedia[0] == "" or not re.search("^\d{4}$", thisMedia[1]) or not re.search("^tt\d{7,8}$", thisMedia[2]):
                raise SyntaxError('Bad format of subdirectory ' + subdir)
            if len(thisMedia[2]) == 10 and thisMedia[2][2] == '0': # 8-digit id's must not start with '0', otherwise id ambiguities may occur
                raise SyntaxError('Bad format of imdb id in subdirectory ' + subdir)
            
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
        self.endYear = None
        self.rating_mul10 = None
        self.numVotes = None
        self.releaseMonth = None # only entered manually when necessary
        self.releaseDay = None # only entered manually when necessary
        self.subdir = subdir
        self.genres = []
        self.mediaVersions = []
        self.mediaConnections = []
    
    def __str__(self):
        return str(self.imdb_id) + " " + str(self.titleType) + " " + str(self.originalTitle) + " " + str(self.primaryTitle) + " " + str(self.startYear) + " " + str(self.endYear) + " " + str(self.rating_mul10) + " " + str(self.numVotes) + " " + str(self.genres)
    
    def getIDString(self):
        idString = str(self.imdb_id)
        if len(idString) < 7:
            idString = idString.zfill(7)
        return "tt" + idString
