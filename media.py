import re

class Media:

    rating_mul10 = None
    numVotes = None
    
    def __init__(self, subdir):
        thisMedia = subdir.rsplit('_', 2)
        
        if len(thisMedia) != 3 or thisMedia[0] == "" or not re.search("^\d{4}$", thisMedia[1]) or not re.search("^tt\d{7,8}$", thisMedia[2]):
            raise SyntaxError('Bad format of subdirectory ' + subdir)
        
        self.id_imdb = thisMedia[2]
        self.name = thisMedia[0]
        self.year = thisMedia[1]