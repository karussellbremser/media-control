import requests, re, time, random, math
from bs4 import BeautifulSoup
import os.path
from media import Media
from mediaconnection import MediaConnection

class ScrapeIMDbOnline:

    headers = {"Accept-Language": "en-US,en;q=0.5", 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.75 Safari/537.36'}
    
    ignoredConnections = ["references", "referenced_in", "features", "featured_in", "spoofs", "spoofed_in", "edited_into", "edited_from"]
    
    # TBD: restrict online parsing to locally available movies and no TV episodes
    
    def __init__(self, cover_directory, delay = 0, maxCount = 0):
        self.cover_directory = cover_directory
        self.delay = delay
        self.maxCount = maxCount
    
    def downloadCovers(self, mediaDict):
        
        if len(mediaDict) == 0:
            return
        
        print("downloading covers...")
        
        count = 0
        
        for currentMedia in mediaDict.values():
        
            # check if file exists, in this case skip this media
            if os.path.isfile(self.cover_directory + "\\" + currentMedia.getIDString() + ".jpg"):
                continue
            
            # scrape IMDb media main page
            page = requests.get("https://www.imdb.com/title/" + currentMedia.getIDString() + "/", headers=self.headers)
            if page.status_code != 200:
                raise EnvironmentError("no 200 code on page return (received status code " + str(page.status_code) + " for IMDb ID " + currentMedia.getIDString() + ")")
            soup = BeautifulSoup(page.content, 'html.parser')
            
            cover_search_result = soup.find_all(attrs={"aria-label": re.compile("View ’[^’\"]+’ Poster")})
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
            if count == self.maxCount:
                return
            
            self.__sleep()

    def parseMediaConnections(self, mediaDict):
        
        if len(mediaDict) == 0:
            return mediaDict
        
        resultDict = {}
        count = 0
        
        print("parsing media connections...")
        
        first = True
        for currentMedia in mediaDict.values():
            
            if first:
                first = False
            else:
                self.__sleep()
            
            print(str(count+1) + " / " + str(len(mediaDict)) + " " + currentMedia.originalTitle)
            
            # enter medium into result dict
            resultDict[currentMedia.imdb_id] = currentMedia

            # scrape IMDb media movie connections page
            page = requests.get("https://www.imdb.com/title/" + currentMedia.getIDString() + "/movieconnections", headers=self.headers)
            if page.status_code != 200:
                raise EnvironmentError("no 200 code on page return")
            soup = BeautifulSoup(page.content, 'html.parser')

            # look for content element
            content = soup.find_all(attrs={"id": "connections_content"})
            if len(content) != 1:
                raise EnvironmentError("no unique connections_content tag found")

            # get direct child list element
            lists = content[0].find_all(attrs={"class": "list"}, recursive=False)
            if len(lists) != 1:
                raise EnvironmentError("no unique child list element found")
            contentList = lists[0]
            
            # check for no_content
            if contentList.has_attr('id') and contentList['id'] == "no_content":
                continue
            
            # iterate over list elements
            lastATagID = ""
            for tag in contentList.children:
                if tag == '\n':
                    continue
                elif tag.name == "a":
                    lastATagID = tag['id']
                elif lastATagID in self.ignoredConnections:
                    continue
                elif tag.name == "h4":
                    continue
                elif tag.name == "div":
                    subtag = next(tag.children)
                    if subtag.name != "a" or lastATagID == "":
                        raise EnvironmentError("html parsing problem")
                    foreignIMDbID = subtag['href'].rsplit('/', 1)[1]
                    if not re.search("^tt\d{7,8}$", foreignIMDbID):
                        raise EnvironmentError("illegal foreign imdb id " + foreignIMDbID)
                    
                    # check for duplicate imdb connection entries (it happens)
                    duplicate = False
                    for x in resultDict[currentMedia.imdb_id].mediaConnections:
                        if x.foreignIMDbID == int(foreignIMDbID[2:]) and x.connectionType == lastATagID:
                            duplicate = True
                            break
                    if duplicate:
                        continue
                    
                    resultDict[currentMedia.imdb_id].mediaConnections.append(MediaConnection(int(foreignIMDbID[2:]), lastATagID))
                else:
                    raise EnvironmentError("html parsing problem")
            
            count += 1
            if count == self.maxCount:
                return resultDict

        return resultDict
    
    def isInDevelopment(self, imdb_id):
        # scrape IMDb media main page
        page = requests.get("https://www.imdb.com/title/tt" + str(imdb_id).zfill(7) + "/", headers=self.headers)
        if page.status_code != 200:
            raise EnvironmentError("no 200 code on page return")
        if page.text.find('<div data-testid="tm-box-up-title" class="sc-5766672e-1 fsIZKM">In Development</div>') != -1:
            return True
        if page.text.find('<div data-testid="tm-box-up-title" class="sc-5766672e-1 fsIZKM">In Production</div>') != -1:
            return True
        if page.text.find('<div data-testid="tm-box-up-title" class="sc-5766672e-1 fsIZKM">Post-production</div>') != -1:
            return True
        if page.text.find('<div data-testid="tm-box-up-title" class="sc-5766672e-1 fsIZKM">Pre-production</div>') != -1:
            return True
        if page.text.find('<div data-testid="tm-box-up-title" class="sc-5766672e-1 fsIZKM">') != -1:
            print("WARNING: unknown production status for IMDb ID " + str(imdb_id))
        return False


    def __sleep(self):
        if self.delay > 0:
            time.sleep(random.randint(self.delay - math.ceil(self.delay / 3), self.delay + math.ceil(self.delay / 3)))












