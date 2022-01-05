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
        with open(self.dataset_directory + '\\' + self.title_ratings_filename, "r") as f:
            c = csv.reader(f, delimiter="\t")
            firstRow = True
            for row in c:
                if firstRow:
                    firstRow = False
                    continue
                if row[0] in media_dict:
                    rating_mul10 = int(row[1].replace('.',''))
                    if rating_mul10 < 10 or rating_mul10 > 100:
                        raise SyntaxError("rating conversion problem for movie " + row[0])
                    media_dict[row[0]].rating_mul10 = rating_mul10
                    media_dict[row[0]].numVotes = int(row[2])
        
        return media_dict
    
    def parseTitleBasics(self, media_dict): # imdb_id || titleType || primaryTitle || originalTitle || isAdult || startYear || endYear || runtimeMinutes || genres
        with open(self.dataset_directory + '\\' + self.title_basics_filename, "r") as f:
            c = csv.reader(f, delimiter="\t")
            firstRow = True
            linecount=1
            for row in c:
                print(linecount)
                linecount+=1
                if firstRow:
                    firstRow = False
                    continue
                if row[0] in media_dict:
                    media_dict[row[0]].titleType = row[1]
                    media_dict[row[0]].primaryTitle = row[2]
                    media_dict[row[0]].originalTitle = row[3]
                    if media_dict[row[0]].startYear != int(row[5]):
                        raise SyntaxError("startYear does not match for title " + row[0] + " (" + str(media_dict[row[0]].startYear) + " vs. " + row[5])
                    if row[6] != "\\N":
                        media_dict[row[0]].endYear = int(row[6])
                    if len(media_dict[row[0]].genres) != 0:
                        raise SyntaxError("genres not empty for title " + row[0])
                    for genre in row[7].split(','):
                        media_dict[row[0]].append(genre)
        
        return media_dict