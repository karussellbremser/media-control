import csv

class ScrapeIMDbOffline:
    
    # class for scraping offline IMDb dataset files (see https://www.imdb.com/interfaces/ and https://datasets.imdbws.com/)
    
    title_ratings_filename = "title.ratings.tsv"
    
    def __init__(self, dataset_directory):
        self.dataset_directory = dataset_directory
    
    def updateDatasets(self): #TBD
        return
    
    def parseTitleRatings(self, id_list):
        resultDict = {}
        
        with open(self.dataset_directory + '\\' + self.title_ratings_filename, "r") as f:
            c = csv.reader(f, delimiter="\t")
            firstRow = True
            for row in c:
                if firstRow:
                    firstRow = False
                    continue
                if row[0] in id_list:
                    resultDict[row[0]] = [row[1], row[2]]
        
        return resultDict