class Movie:
    
    def __init__(self, id_imdb, name, year):
        self.id_imdb = id_imdb
        self.name = name
        self.year = year
        self.movietype = 0 # 0: not set, 1: movie, 2: series
