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
    
    def parseIMDbOfflineFile(self, content_dict, file_type): # file_type: 0 -> TitleRatings, 1 -> TitleBasics
        if file_type == 0:
            filename = self.title_ratings_filename
        elif file_type == 1:
            filename = self.title_basics_filename
        else:
            raise SyntaxError("unknown filetype")
        
        with open(self.dataset_directory + '\\' + filename, "r", encoding="utf8") as f:
            c = csv.reader(f, delimiter="\t")
            next(c, None) # read from second line
            for row in c:
                current_imdb_id = int(row[0][2:])
                if current_imdb_id in content_dict:
                    if file_type == 0:
                        content_dict[current_imdb_id] = self.insertTitleRatings(content_dict[current_imdb_id], row)
                    elif file_type == 1:
                        content_dict[current_imdb_id] = self.insertTitleBasics(content_dict[current_imdb_id], row)
                    else:
                        raise SyntaxError("unknown filetype")
        
        # make sure that all items have been touched
        for x in content_dict.values():
            if (file_type == 0 and x.numVotes == None) or (file_type == 1 and x.titleType == None):
                raise SyntaxError("no info for " + x.imdb_id + " found")
        
        return content_dict
    
    def insertTitleRatings(self, media_obj, row): # row: imdb_id || rating || numVotes
        
        rating_mul10 = int(row[1].replace('.',''))
        if rating_mul10 < 10 or rating_mul10 > 100:
            raise SyntaxError("rating conversion problem for movie " + row[0])
        media_obj.rating_mul10 = rating_mul10
        media_obj.numVotes = int(row[2])
        
        return media_obj
    
    def insertTitleBasics(self, media_obj, row): # row: imdb_id || titleType || primaryTitle || originalTitle || isAdult || startYear || endYear || runtimeMinutes || genres

        media_obj.titleType = row[1]
        media_obj.primaryTitle = row[2]
        media_obj.originalTitle = row[3]
        if media_obj.startYear != int(row[5]):
            raise SyntaxError("startYear does not match for title " + row[0] + " " + row[3] + " (" + str(media_obj.startYear) + " vs. " + row[5] + ")")
        if row[6] != "\\N":
            media_obj.endYear = int(row[6])
        if len(media_obj.genres) != 0:
            raise SyntaxError("genres not empty for title " + row[0])
        if len(row[8].split(',')) not in range(1, 4):
            raise SyntaxError("illegal genre count for title " + row[0])
        for genre in row[8].split(','):
            media_obj.genres.append(genre)
        
        return media_obj
        