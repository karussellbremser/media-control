import csv
from media import Media

class ScrapeIMDbOffline:
    
    # class for scraping offline IMDb dataset files (see https://www.imdb.com/interfaces/ and https://datasets.imdbws.com/)
    
    title_ratings_filename = "title.ratings.tsv"
    title_basics_filename = "title.basics.tsv"
    
    def __init__(self, dataset_directory):
        self.dataset_directory = dataset_directory
    
    def updateDatasets(self): #TBD
        return
    
    def parseTitleRatings(self, media_dict): # imdb_id || rating || numVotes
        with open(self.dataset_directory + '\\' + self.title_ratings_filename, "r", encoding="utf8") as f:
            c = csv.reader(f, delimiter="\t")
            next(c, None) # read from second line
            for row in c:
                if row[0] in media_dict:
                    rating_mul10 = int(row[1].replace('.',''))
                    if rating_mul10 < 10 or rating_mul10 > 100:
                        raise SyntaxError("rating conversion problem for movie " + row[0])
                    media_dict[row[0]].rating_mul10 = rating_mul10
                    media_dict[row[0]].numVotes = int(row[2])
        
        # make sure that all items have been touched
        for x in media_dict.values():
            if x.numVotes == None:
                raise SyntaxError("no rating info for " + x.id_imdb + " found")
        
        return media_dict
    
    def parseTitleBasics(self, media_dict): # imdb_id || titleType || primaryTitle || originalTitle || isAdult || startYear || endYear || runtimeMinutes || genres
        with open(self.dataset_directory + '\\' + self.title_basics_filename, "r", encoding="utf8") as f:
            c = csv.reader(f, delimiter="\t")
            next(c, None) # read from second line
            for row in c:
                current_imdb_id = row[0]
                if current_imdb_id in media_dict:
                    media_dict[current_imdb_id].titleType = row[1]
                    media_dict[current_imdb_id].primaryTitle = row[2]
                    media_dict[current_imdb_id].originalTitle = row[3]
                    if media_dict[current_imdb_id].startYear != int(row[5]):
                        raise SyntaxError("startYear does not match for title " + current_imdb_id + " " + row[3] + " (" + str(media_dict[current_imdb_id].startYear) + " vs. " + row[5] + ")")
                    if row[6] != "\\N":
                        media_dict[current_imdb_id].endYear = int(row[6])
                    if len(media_dict[current_imdb_id].genres) != 0:
                        raise SyntaxError("genres not empty for title " + current_imdb_id)
                    if len(row[8].split(',')) not in range(1, 4):
                        raise SyntaxError("illegal genre count for title " + current_imdb_id)
                    for genre in row[8].split(','):
                        media_dict[current_imdb_id].genres.append(genre)
        
        # make sure that all items have been touched
        for x in media_dict.values():
            if x.titleType == None:
                raise SyntaxError("no title info for " + x.id_imdb + " found")
        
        return media_dict
