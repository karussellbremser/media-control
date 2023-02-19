import requests, re, time, random, math
from bs4 import BeautifulSoup
import os.path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from media import Media
from mediaconnection import MediaConnection

class ScrapeIMDbOnline:

    headers = {"Accept-Language": "en-US,en;q=0.5", 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.75 Safari/537.36'}
    
    ignoredConnections = ["references", "referenced_in", "features", "featured_in", "spoofs", "spoofed_in", "edited_into", "edited_from"]
    
    # TBD: restrict online parsing to locally available movies and no TV episodes
    
    def __init__(self, cover_directory, webdriver_path, delay = 0, maxCount = 0):
        self.cover_directory = cover_directory
        self.webdriver_path = webdriver_path
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
            url = "https://www.imdb.com/title/" + currentMedia.getIDString() + "/movieconnections"
            page = requests.get(url, headers=self.headers)
            if page.status_code != 200:
                raise EnvironmentError("no 200 code on page return")
            soup = BeautifulSoup(page.content, 'html.parser')

            for connectionType in MediaConnection.connectionTypeList:
                content = soup.find_all(attrs={"href": "#"+connectionType})
                if len(content) > 1:
                    raise EnvironmentError("multiple results for connection type " + connectionType)
                if len(content) == 0:
                    continue
                elementList = content[0].parent.next_sibling.contents[0]
                
                if elementList.contents[-1].name != "li": # check whether page needs to be dynamically expanded or not
                    count_dyn = 0
                    
                    chrome_options = Options()
                    user_agent = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/60.0.3112.50 Safari/537.36'
                    chrome_options.add_argument(f'user-agent={user_agent}')
                    chrome_options.add_argument('--no-sandbox')
                    chrome_options.add_argument('--window-size=1920,1080')
                    chrome_options.add_argument('--headless')
                    chrome_options.add_argument('--allow-running-insecure-content')
                    chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
                    browser = webdriver.Chrome(executable_path = self.webdriver_path, options=chrome_options)
                    browser.maximize_window()
                    browser.implicitly_wait(10)
                    
                    while True:
                        count_dyn += 1
                        if count_dyn > 5:
                            raise EnvironmentError("excessively long loop for page expanding for connection type " + connectionType)
                        
                        browser.get(url)
                        time.sleep(3)
                        element = browser.find_element("xpath", "//span[contains(@class, 'single-page-see-more-button-" + connectionType + "')]/button")
                        element.location_once_scrolled_into_view
                        time.sleep(1)
                        element.click()
                        time.sleep(2)
                        soup = BeautifulSoup(browser.page_source, 'html.parser')
                        
                        content = soup.find_all(attrs={"href": "#"+connectionType})
                        if len(content) != 1:
                            raise EnvironmentError("false results for connection type " + connectionType)
                        elementList = content[0].parent.next_sibling.contents[0]
                        
                        if elementList.contents[-1].name == "li": # check whether page needs to expanded further
                            browser.quit()
                            break
                
                for element in elementList.children:
                    if element.contents[0].name != "div":
                        raise EnvironmentError("connection scraping error")
                    if element.contents[0].contents[0].name != "ul":
                        raise EnvironmentError("connection scraping error")
                    if element.contents[0].contents[0].contents[0].name != "div":
                        raise EnvironmentError("connection scraping error")
                    if element.contents[0].contents[0].contents[0].contents[0].name != "div":
                        raise EnvironmentError("connection scraping error")
                    if element.contents[0].contents[0].contents[0].contents[0].contents[0].name != "p":
                        raise EnvironmentError("connection scraping error")
                    if element.contents[0].contents[0].contents[0].contents[0].contents[0].contents[0].name != "a":
                        raise EnvironmentError("connection scraping error")
                    
                    targetUrl = element.contents[0].contents[0].contents[0].contents[0].contents[0].contents[0]['href']
                    if targetUrl[0:7] != "/title/":
                        raise EnvironmentError("connection scraping error")
                    targetUrl = targetUrl[7:]
                    foreignIMDbID = targetUrl.split('?')[0]
                    
                    if not re.search("^tt\d{7,8}$", foreignIMDbID):
                        raise EnvironmentError("illegal foreign imdb id " + foreignIMDbID)
                    
                    # check for duplicate imdb connection entries (it happens)
                    duplicate = False
                    for x in resultDict[currentMedia.imdb_id].mediaConnections:
                        if x.foreignIMDbID == int(foreignIMDbID[2:]) and x.connectionType == connectionType:
                            duplicate = True
                            break
                    if duplicate:
                        continue
                    
                    resultDict[currentMedia.imdb_id].mediaConnections.append(MediaConnection(int(foreignIMDbID[2:]), connectionType))
            
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
        if page.text.find('<div data-testid="tm-box-up-title" class="sc-5766672e-1 fsIZKM">Coming soon</div>') != -1:
            return True
        if page.text.find('<div data-testid="tm-box-up-title" class="sc-5766672e-1 fsIZKM">') != -1:
            print("WARNING: unknown production status for IMDb ID " + str(imdb_id))
        return False


    def __sleep(self):
        if self.delay > 0:
            time.sleep(random.randint(self.delay - math.ceil(self.delay / 3), self.delay + math.ceil(self.delay / 3)))












