import requests, re, time, random, math
from bs4 import BeautifulSoup
import os.path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from media import Media
from mediaconnection import MediaConnection
from PIL import Image

class ScrapeIMDbOnline:

    headers = {"Accept-Language": "en-US,en;q=0.5", 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.75 Safari/537.36'}
    
    ignoredConnections = ["references", "referenced_in", "features", "featured_in", "spoofs", "spoofed_in", "edited_into", "edited_from"]
    
    TARGET_WIDTH = 380
    TARGET_HEIGHT = 562
    
    # TBD: restrict online parsing to locally available movies and no TV episodes
    
    def __init__(self, cover_directory, thumbnail_directory, webdriver_path, delay = 0, maxCount = 0):
        self.cover_directory = cover_directory
        self.thumbnail_directory = thumbnail_directory
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
            chrome_options = Options()
            user_agent = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/60.0.3112.50 Safari/537.36'
            chrome_options.add_argument(f'user-agent={user_agent}')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--window-size=1920,1080')
            chrome_options.add_argument("--start-maximized")
            chrome_options.add_argument('--headless')
            chrome_options.add_argument('--allow-running-insecure-content')
            chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
            browser = webdriver.Chrome(executable_path = self.webdriver_path, options=chrome_options)
            browser.maximize_window()
            browser.implicitly_wait(10)
            browser.get("https://www.imdb.com/title/" + currentMedia.getIDString() + "/")
            time.sleep(4)
            
            matches = browser.execute_script("""
                const re = /^View ’[^’"]+’ Poster$/;

                return Array.from(document.querySelectorAll('[aria-label]'))
                    .filter(el => re.test(el.getAttribute('aria-label') || ''))
                    .map(el => el.getAttribute('href'));
            """)

            if len(matches) != 1:
                raise EnvironmentError("no unique cover tag found")

            # scrape cover page
            browser.get("https://www.imdb.com" + matches[0])
            time.sleep(4)
            
            matches = browser.execute_script("""
                return Array.from(document.querySelectorAll('[property]'))
                    .filter(el => (el.getAttribute('property') || '') === "og:image")
                    .map(el => el.getAttribute('content'));
            """)
            
            browser.quit()

            if len(matches) != 1:
                raise EnvironmentError("no unique cover tag found")
            
            link_parts = matches[0].rsplit('.', 2)
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
    
    def make_thumbnail(self, in_path, out_path):
        with Image.open(in_path) as img:
            img = img.convert("RGB")  # important for WebP

            src_w, src_h = img.size
            target_ratio = self.TARGET_WIDTH / self.TARGET_HEIGHT
            src_ratio = src_w / src_h

            # Schritt 1: Skalieren (ohne Verzerren)
            if src_ratio > target_ratio:
                # Bild ist zu breit → Höhe anpassen
                new_height = self.TARGET_HEIGHT
                new_width = int(new_height * src_ratio)
            else:
                # Bild ist zu hoch → Breite anpassen
                new_width = self.TARGET_WIDTH
                new_height = int(new_width / src_ratio)

            img = img.resize((new_width, new_height), Image.LANCZOS)

            # Schritt 2: Center Crop
            left = (new_width - self.TARGET_WIDTH) / 2
            top = (new_height - self.TARGET_HEIGHT) / 2
            right = left + self.TARGET_WIDTH
            bottom = top + self.TARGET_HEIGHT

            img = img.crop((left, top, right, bottom))

            # Schritt 3: Als WebP speichern
            img.save(out_path, "WEBP", quality=90, method=6)
    
    def generateThumbnails(self):
        # generate every missing thumbnail
        for filename in os.listdir(self.cover_directory):
            if not filename.lower().endswith(".jpg"):
                continue

            in_path = os.path.join(self.cover_directory, filename)

            out_filename = os.path.splitext(filename)[0] + ".webp"
            out_path = os.path.join(self.thumbnail_directory, out_filename)

            if os.path.exists(out_path):
                continue

            try:
                self.make_thumbnail(in_path, out_path)
                print("Saved:", out_filename)
            except Exception as e:
                print("Error:", filename, e)

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
            
            chrome_options = Options()
            user_agent = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/60.0.3112.50 Safari/537.36'
            chrome_options.add_argument(f'user-agent={user_agent}')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--window-size=1920,1080')
            chrome_options.add_argument("--start-maximized")
            chrome_options.add_argument('--headless')
            chrome_options.add_argument('--allow-running-insecure-content')
            chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
            browser = webdriver.Chrome(executable_path = self.webdriver_path, options=chrome_options)
            browser.maximize_window()
            browser.implicitly_wait(10)
            browser.get(url)
            time.sleep(4)
            soup = BeautifulSoup(browser.page_source, 'html.parser')

            for connectionType in MediaConnection.connectionTypeList:
                content = soup.find_all(attrs={"href": "#"+connectionType})
                if len(content) > 1:
                    raise EnvironmentError("multiple results for connection type " + connectionType)
                if len(content) == 0:
                    continue
                elementList = content[0].parent.next_sibling.contents[0]
                
                if elementList.contents[-1].name != "li": # check whether page needs to be dynamically expanded or not
                    count_dyn = 0
                    
                    # prepare browser for dynamic scraping
                    chrome_options = Options()
                    user_agent = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/60.0.3112.50 Safari/537.36'
                    chrome_options.add_argument(f'user-agent={user_agent}')
                    chrome_options.add_argument('--no-sandbox')
                    chrome_options.add_argument('--window-size=1920,1080')
                    chrome_options.add_argument("--start-maximized")
                    chrome_options.add_argument('--headless')
                    chrome_options.add_argument('--allow-running-insecure-content')
                    chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
                    browser = webdriver.Chrome(executable_path = self.webdriver_path, options=chrome_options)
                    browser.maximize_window()
                    browser.implicitly_wait(10)
                    browser.get(url)
                    time.sleep(4)
                    
                    while True:
                        count_dyn += 1
                        if count_dyn > 5:
                            raise EnvironmentError("excessively long loop for page expanding for connection type " + connectionType)
                        
                        element = browser.find_element("xpath", "//span[contains(@class, 'single-page-see-more-button-" + connectionType + "')]/button")
                        element.location_once_scrolled_into_view
                        time.sleep(1)
                        browser.execute_script("arguments[0].click();", element)
                        time.sleep(3)
                        soup = BeautifulSoup(browser.page_source, 'html.parser')
                        
                        content = soup.find_all(attrs={"href": "#"+connectionType})
                        if len(content) != 1:
                            raise EnvironmentError("false results for connection type " + connectionType)
                        elementList = content[0].parent.next_sibling.contents[0]
                        
                        if elementList.contents[-1].name == "li": # check whether page needs to be expanded further
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
                    
                    if foreignIMDbID[-1] == "/":
                        foreignIMDbID = foreignIMDbID[:-1]
                    
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
        if re.search('<div data-testid="tm-box-up-title" class="[^\"]+">(In Development|In Production|Post-production|Pre-production|Coming soon|Completed)</div>', page.text):
            return True
        if re.search('<div data-testid="tm-box-up-title" class="[^\"]+">', page.text):
            print("WARNING: unknown production status for IMDb ID " + str(imdb_id))
        return False


    def __sleep(self):
        if self.delay > 0:
            time.sleep(random.randint(self.delay - math.ceil(self.delay / 3), self.delay + math.ceil(self.delay / 3)))












