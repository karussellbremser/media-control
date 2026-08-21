import csv, requests, gzip, shutil, os
from media import Media
from scrapeimdbonline import ScrapeIMDbOnline
from exceptions import OfflineDatasetError

class ScrapeIMDbOffline:
    
    # class for scraping offline IMDb dataset files (see https://www.imdb.com/interfaces/ and https://datasets.imdbws.com/)
    
    title_ratings_filename = "title.ratings.tsv"
    title_basics_filename = "title.basics.tsv"

    def __init__(self, scrapeimdbonline, dataset_directory):
        self.dataset_directory = dataset_directory
        self.scrapeimdbonline = scrapeimdbonline
    
    def __updateDataset(self, in_path, url):
        path_bkp = in_path + "_bkp"
        renamed = False
        if os.path.exists(in_path):
            os.rename(in_path, path_bkp)
            renamed = True
        
        with requests.get(url, stream=True) as r:
            r.raise_for_status()
            with gzip.GzipFile(fileobj=r.raw) as gz:
                with open(in_path, "wb") as f_out:
                    shutil.copyfileobj(gz, f_out)
        
        if renamed:
            os.remove(path_bkp)
    
    def updateDatasets(self):
        print("Updating IMDb offline datasets...")
        
        # update Title Basics
        self.__updateDataset(os.path.join(self.dataset_directory, self.title_basics_filename), "https://datasets.imdbws.com/title.basics.tsv.gz")
        
        # update Title Ratings
        self.__updateDataset(os.path.join(self.dataset_directory, self.title_ratings_filename), "https://datasets.imdbws.com/title.ratings.tsv.gz")
        
        return
    
    def parseTitleRatings(self, content_dict):
        return self.__parseIMDbOfflineFile(content_dict, 0, True)
    
    def refreshTitleRatings(self, content_dict):
        return self.__parseIMDbOfflineFile(content_dict, 0, False)
    
    def parseTitleBasics(self, content_dict):
        return self.__parseIMDbOfflineFile(content_dict, 1, True)
    
    def __parseIMDbOfflineFile(self, content_dict, file_type, remove_illegal): # file_type: 0 -> TitleRatings, 1 -> TitleBasics
        if len(content_dict) == 0:
            return content_dict
        
        if file_type == 0:
            filename = self.title_ratings_filename
        elif file_type == 1:
            filename = self.title_basics_filename
        else:
            raise RuntimeError("unknown filetype") # internal misuse: file_type is always 0 or 1, passed by this class's own methods
        
        with open(os.path.join(self.dataset_directory, filename), "r", encoding="utf8") as f:
            c = csv.reader(f, delimiter="\t")
            next(c, None) # read from second line
            for row in c:
                current_imdb_id = int(row[0][2:])
                if current_imdb_id in content_dict:
                    if file_type == 0:
                        content_dict[current_imdb_id] = self.__insertTitleRatings(content_dict[current_imdb_id], row)
                    elif file_type == 1:
                        content_dict[current_imdb_id] = self.__insertTitleBasics(content_dict[current_imdb_id], row)
                    else:
                        raise RuntimeError("unknown filetype") # internal misuse: file_type is always 0 or 1, passed by this class's own methods
        
        if (remove_illegal):
            # make sure that all items have been touched; mark ones that are illegal for deletion
            illegal_ids = []
            for x in content_dict.values():
                if file_type == 0 and x.numVotes == None:
                    if x.subdir == None and self.scrapeimdbonline.isInDevelopment(x.imdb_id): # in-development titles are excluded
                        # illegal title. mark for deletion from dict keys and mediaConnections
                        illegal_ids.append(x.imdb_id)
                        continue
                
                if file_type == 1 and x.titleType in (None, "localMovie", "localSeries"): # titleType still unset or still the local-scrape placeholder: no matching row was found in title.basics
                    if x.subdir == None:
                        # referenced-only title missing from the dataset: not worth an online fallback scrape, discard
                        illegal_ids.append(x.imdb_id)
                        continue
                    else:
                        # locally-owned title missing from the dataset (e.g. very obscure titles): flag for online fallback instead of silently dropping it
                        x.needsOnlineFallback = True
                        continue

                if file_type == 1 and x.titleType not in Media.movieTitleTypes + Media.seriesTitleTypes:
                    # found in the dataset, but not an acceptable title type (e.g. a TV episode ending up in the movie library)
                    illegal_ids.append(x.imdb_id)
            
            # remove illegal media from dict
            for x in illegal_ids:
                content_dict.pop(x)
            
            # remove references to illegal media
            for x in content_dict.values():
                content_dict[x.imdb_id].mediaConnections = [y for y in x.mediaConnections if not y.foreignIMDbID in illegal_ids]
        
        return content_dict
    
    def __insertTitleRatings(self, media_obj, row): # row: imdb_id || rating || numVotes
        
        if row[1] == "\\N":
            media_obj.rating_mul10 = None
        else:
            rating_mul10 = int(row[1].replace('.',''))
            if rating_mul10 < 10 or rating_mul10 > 100:
                raise OfflineDatasetError("rating conversion problem for movie " + row[0])
            media_obj.rating_mul10 = rating_mul10
        media_obj.numVotes = int(row[2]) if row[2] != "\\N" else None
        
        return media_obj
    
    def __insertTitleBasics(self, media_obj, row): # row: imdb_id || titleType || primaryTitle || originalTitle || isAdult || startYear || endYear || runtimeMinutes || genres
        
        localTitleType = media_obj.titleType # result of local parsing (movie or series)
        if ((localTitleType == "localMovie" and row[1] not in Media.movieTitleTypes)
            or (localTitleType == "localSeries" and row[1] not in Media.seriesTitleTypes)):
            raise OfflineDatasetError("title type " + row[1] + " not acceptable for local parsing result " + localTitleType)
        if (row[1] == "\\N" or row[2] == "\\N" or row[3] == "\\N" or row[5] == "\\N"):
            media_obj.titleType = "ILLEGAL" # set illegal title type so that object will be removed later
            return media_obj
        media_obj.titleType = row[1]
        media_obj.primaryTitle = row[2]
        media_obj.originalTitle = row[3]
        if media_obj.startYear != None and media_obj.startYear != int(row[5]):
            raise OfflineDatasetError("startYear does not match for title " + row[0] + " " + row[3] + " (" + str(media_obj.startYear) + " vs. " + row[5] + ")")
        media_obj.startYear = int(row[5])
        media_obj.endYear = int(row[6]) if row[6] != "\\N" else None

        return media_obj
        