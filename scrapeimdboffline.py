class ScrapeIMDbOffline:
    
    # class for scraping offline IMDb dataset files (see https://www.imdb.com/interfaces/ and https://datasets.imdbws.com/)
    
    def __init__(self, dataset_directory):
        self.dataset_directory = dataset_directory