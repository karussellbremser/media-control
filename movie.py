from media import Media

class Movie(Media):
    
    def __init__(self, subdir):
        super().__init__(subdir)