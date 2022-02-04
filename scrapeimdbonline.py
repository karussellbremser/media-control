import requests
from bs4 import BeautifulSoup
import os.path

class ScrapeIMDbOnline:

    headers = {"Accept-Language": "en-US,en;q=0.5"}
    
    def __init__(self, cover_directory):
        self.cover_directory = cover_directory
    
    def downloadCovers(self, mediaList, maxCount = 0): # maxCount = 0: unlimited cover downloads
        
        count = 0
        
        for currentMedia in mediaList:
        
            # check if file exists, in this case skip this media
            if os.path.isfile(self.cover_directory + "\\" + currentMedia.getIDString() + ".jpg"):
                continue
            
            # scrape IMDb media main page
            page = requests.get("https://www.imdb.com/title/" + currentMedia.getIDString() + "/", headers=self.headers)
            if page.status_code != 200:
                raise EnvironmentError("no 200 code on page return")
            soup = BeautifulSoup(page.content, 'html.parser')
            
            cover_search_result = soup.find_all(attrs={"aria-label": "View {Title} Poster"})
            if len(cover_search_result) != 1:
                raise EnvironmentError("no unique cover tag found")
            
            # scrape cover page
            page = requests.get("https://www.imdb.com" + cover_search_result[0]['href'], headers=self.headers)
            if page.status_code != 200:
                raise EnvironmentError("no 200 code on page return")
            soup = BeautifulSoup(page.content, 'html.parser')
            
            cover_search_result = soup.find_all(attrs={"property": "og:image"})
            if len(cover_search_result) != 1:
                raise EnvironmentError("no unique cover tag found")
            
            cover_direct_link = cover_search_result[0]['content']
            link_parts = cover_direct_link.rsplit('.', 2)
            if len(link_parts) != 3 or link_parts[2] != "jpg":
                raise EnvironmentError("cover link not properly formatted: " + currentMedia.getIDString() + " - " + cover_direct_link)
            cover_direct_link = link_parts[0] + "._V1_.jpg"
            
            # download cover
            coverFile = requests.get(cover_direct_link, allow_redirects=True)
            open(self.cover_directory + "\\" + currentMedia.getIDString() + ".jpg", 'wb').write(coverFile.content)
            
            count += 1
            if count == maxCount:
                return
