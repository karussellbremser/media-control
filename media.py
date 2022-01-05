import re

class Media:

    id_imdb = None
    titleType = None
    originalTitle = None
    primaryTitle = None
    startYear = None
    endYear = None
    rating_mul10 = None
    numVotes = None
    genres = []
    
    def __init__(self, subdir):
        thisMedia = subdir.rsplit('_', 2)
        
        if len(thisMedia) != 3 or thisMedia[0] == "" or not re.search("^\d{4}$", thisMedia[1]) or not re.search("^tt\d{7,8}$", thisMedia[2]):
            raise SyntaxError('Bad format of subdirectory ' + subdir)
        
        self.id_imdb = thisMedia[2]
        self.originalTitle = thisMedia[0]
        self.startYear = int(thisMedia[1])