import re

class Media:
    
    def __init__(self, subdir, mediatype):
        thisMedia = subdir.rsplit('_', 2)
        
        if len(thisMedia) != 3 or thisMedia[0] == "" or not re.search("^\d{4}$", thisMedia[1]) or not re.search("^tt\d{7,8}$", thisMedia[2]):
            raise SyntaxError('Bad format of subdirectory ' + subdir)
        
        self.id_imdb = thisMedia[2]
        self.name = thisMedia[0]
        self.year = thisMedia[1]
        self.mediatype = mediatype # 0: not set, 1: movie, 2: series