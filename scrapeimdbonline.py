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

    TARGET_WIDTH = 380
    TARGET_HEIGHT = 562

    # TBD: restrict online parsing to locally available movies and no TV episodes

    def __init__(self, cover_directory, thumbnail_directory, webdriver_path, delay = 0, maxCount = 0):
        self.cover_directory = cover_directory
        self.thumbnail_directory = thumbnail_directory
        self.webdriver_path = webdriver_path
        self.delay = delay
        self.maxCount = maxCount
        self.__interestNameMap = None # lazily-fetched cache, see __getGlobalInterestNameMap

        # instantiate chrome browser
        chrome_options = Options()
        user_agent = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/60.0.3112.50 Safari/537.36'
        chrome_options.add_argument(f'user-agent={user_agent}')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument("--start-maximized")
        #chrome_options.add_argument('--headless')
        chrome_options.add_argument('--allow-running-insecure-content')
        chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
        self.browser = webdriver.Chrome(executable_path = self.webdriver_path, options=chrome_options)
        self.browser.maximize_window()
        self.browser.implicitly_wait(10)
        self.browser.get("https://www.imdb.com/")
        time.sleep(20)

    def __del__(self):
        self.browser.quit()

    def downloadCovers(self, mediaDict):

        if len(mediaDict) == 0:
            return

        print("downloading covers...")

        count = 0

        for currentMedia in mediaDict.values():

            # check if file exists, in this case skip this media
            coverPath = os.path.join(self.cover_directory, currentMedia.getIDString() + ".jpg")
            if os.path.isfile(coverPath):
                continue

            # scrape IMDb media main page
            self.browser.get("https://www.imdb.com/title/" + currentMedia.getIDString() + "/")
            time.sleep(4)

            self.__downloadCoverFromLoadedMainPage(currentMedia, coverPath)

            count += 1
            if count == self.maxCount:
                return

            self.__sleep()

    def scrapeMainPages(self, mediaDict, knownInterestIDs):
        """For every medium in mediaDict, visits its IMDb main page exactly once and:
        - always scrapes its interests (standard genres and subgenres alike)
        - downloads its cover if the file doesn't already exist

        knownInterestIDs is a set of already-known IMDb interest ids; it is mutated in place
        as new interests are discovered. Returns a list of (imdb_interest_id, name, description,
        parent_imdb_interest_id) tuples for newly discovered interests, in dependency order
        (a subgenre's parent genre always appears before the subgenre itself), so the caller
        can persist them via DBControl.ensureInterestExists() in the order returned."""

        if len(mediaDict) == 0:
            return []

        print("scraping main pages...")

        newInterestRegistrations = []
        count = 0
        first = True

        for currentMedia in mediaDict.values():
            if first:
                first = False
            else:
                self.__sleep()

            self.browser.get("https://www.imdb.com/title/" + currentMedia.getIDString() + "/")
            time.sleep(4)

            chips = self.__scrapeInterestChips()
            currentMedia.interests = [chip_id for chip_id, _ in chips]

            # cover download must happen here, while still on the title's main page from the browser.get()
            # above; classifying newly-discovered interests below navigates away to separate /interest/...
            # pages, so this ordering keeps the title's own main page visited exactly once per title
            coverPath = os.path.join(self.cover_directory, currentMedia.getIDString() + ".jpg")
            if not os.path.isfile(coverPath):
                self.__downloadCoverFromLoadedMainPage(currentMedia, coverPath)

            newInterestRegistrations.extend(self.__ensureInterestsRegistered(chips, knownInterestIDs))

            count += 1
            if count == self.maxCount:
                return newInterestRegistrations

        return newInterestRegistrations

    def __downloadCoverFromLoadedMainPage(self, currentMedia, coverPath):
        """Downloads the highest-quality cover available, assuming the browser is currently
        on currentMedia's IMDb main page. Visits the dedicated poster subpage rather than using
        the main page's own image directly, since the poster subpage serves a larger version."""

        matches = self.browser.execute_script("""
            const re = /^View ’[^’"]+’ Poster$/;

            return Array.from(document.querySelectorAll('[aria-label]'))
                .filter(el => re.test(el.getAttribute('aria-label') || ''))
                .map(el => el.getAttribute('href'));
        """)

        if len(matches) != 1:
            raise EnvironmentError("no unique cover tag found")

        # scrape cover page
        self.browser.get("https://www.imdb.com" + matches[0])
        time.sleep(4)

        matches = self.browser.execute_script("""
            return Array.from(document.querySelectorAll('[property]'))
                .filter(el => (el.getAttribute('property') || '') === "og:image")
                .map(el => el.getAttribute('content'));
        """)

        if len(matches) != 1:
            raise EnvironmentError("no unique cover tag found")

        link_parts = matches[0].rsplit('.', 2)
        if len(link_parts) != 3 or link_parts[2] != "jpg":
            raise EnvironmentError("cover link not properly formatted: " + currentMedia.getIDString() + " - " + matches[0])
        cover_direct_link = link_parts[0] + "._V1_.jpg"

        # download cover
        coverFile = requests.get(cover_direct_link, allow_redirects=True)
        open(coverPath, 'wb').write(coverFile.content)

    def __scrapeInterestChips(self):
        """Scrapes the interests chip list from the currently-loaded title main page.
        Returns a list of (imdb_interest_id, name) tuples. Raises on any unexpected structure,
        rather than silently skipping or guessing."""

        box_count = self.browser.execute_script('return document.querySelectorAll(\'[data-testid="interests"]\').length;')
        if box_count != 1:
            raise EnvironmentError("expected exactly one interests block on title page, found " + str(box_count))

        chips = self.browser.execute_script("""
            const box = document.querySelector('[data-testid="interests"]');
            return Array.from(box.querySelectorAll('a')).map(a => ({
                text: a.innerText,
                href: a.getAttribute('href')
            }));
        """)

        if len(chips) == 0:
            raise EnvironmentError("interests block present but contains no chips")

        result = []
        seenIDs = set()
        for chip in chips:
            match = re.search(r"^/interest/(in\d+)/", chip.get("href") or "")
            if not match:
                raise EnvironmentError("interest chip href not properly formatted: " + str(chip.get("href")))
            chip_id = match.group(1)
            name = (chip.get("text") or "").strip()
            if name == "":
                raise EnvironmentError("interest chip has empty name: " + chip_id)
            if chip_id in seenIDs:
                raise EnvironmentError("duplicate interest chip on page: " + chip_id)
            seenIDs.add(chip_id)
            result.append((chip_id, name))

        return result

    def __ensureInterestsRegistered(self, chips, knownInterestIDs):
        """For every (imdb_interest_id, name) in chips not already in knownInterestIDs, visits its
        IMDb interest page to classify it as a genre or subgenre and scrape its description text.
        A subgenre's parent genre is NOT necessarily among the same title's other chips (a title
        can carry a subgenre without also being tagged with its parent genre directly), so the
        parent's id is resolved against IMDb's full interest directory instead. The parent is
        registered first if it too is new. knownInterestIDs is mutated in place. Returns a list of
        (imdb_interest_id, name, description, parent_imdb_interest_id) tuples. Raises on any
        unexpected structure (unknown type, missing description, missing/ambiguous parent, more
        than two taxonomy levels)."""

        newRegistrations = []

        def classify(interest_id, name):
            self.browser.get("https://www.imdb.com/interest/" + interest_id + "/")
            time.sleep(4)

            typeText = self.browser.execute_script("""
                const el = document.querySelector('[data-testid="interest-hero-type"]');
                return el ? el.innerText.trim() : null;
            """)
            if typeText not in ("Genre", "Subgenre"):
                raise EnvironmentError("unexpected interest type '" + str(typeText) + "' for " + interest_id + " (" + name + ")")

            categoryTexts = self.browser.execute_script("""
                const header = document.querySelector('[data-testid="interest-hero-header"]');
                if (!header) return null;
                return Array.from(header.querySelectorAll('[data-testid="hero-breadcrumb-category"]')).map(a => a.innerText.trim());
            """)
            if categoryTexts is None:
                raise EnvironmentError("interest hero header not found for " + interest_id)

            description = self.browser.execute_script("""
                const box = document.querySelector('[data-testid="interest-description-and-chips"]');
                if (!box) return null;
                const descEls = box.querySelectorAll('.ipc-overflowText');
                return descEls.length === 1 ? descEls[0].innerText.trim() : null;
            """)
            if not description:
                raise EnvironmentError("could not find description text for interest " + interest_id + " (" + name + ")")

            if typeText == "Genre":
                if len(categoryTexts) != 0:
                    raise EnvironmentError("genre-type interest unexpectedly has a parent category: " + interest_id)
                return ("Genre", None, description)
            else:
                distinctParents = set(categoryTexts)
                if len(distinctParents) != 1:
                    raise EnvironmentError("could not determine a single parent category for subgenre " + interest_id + ": " + str(distinctParents))
                return ("Subgenre", next(iter(distinctParents)), description)

        for chip_id, chip_name in chips:
            if chip_id in knownInterestIDs:
                continue

            typeText, parentName, description = classify(chip_id, chip_name)

            if typeText == "Genre":
                newRegistrations.append((chip_id, chip_name, description, None))
                knownInterestIDs.add(chip_id)
                continue

            candidates = self.__getGlobalInterestNameMap().get(parentName)
            if not candidates or len(candidates) != 1:
                raise EnvironmentError("parent genre '" + parentName + "' for subgenre " + chip_id + " (" + chip_name + ") not uniquely found in IMDb's interest directory: " + str(candidates))
            parent_id = next(iter(candidates))

            if parent_id not in knownInterestIDs:
                parentType, parentParentName, parentDescription = classify(parent_id, parentName)
                if parentType != "Genre":
                    raise EnvironmentError("expected '" + parentName + "' to be a top-level genre, but it is a " + parentType)
                newRegistrations.append((parent_id, parentName, parentDescription, None))
                knownInterestIDs.add(parent_id)

            newRegistrations.append((chip_id, chip_name, description, parent_id))
            knownInterestIDs.add(chip_id)

        return newRegistrations

    def __getGlobalInterestNameMap(self):
        """Lazily fetches and caches IMDb's full interest directory (/interest/all/) as a
        name -> set(imdb_interest_id) map. Used to resolve a subgenre's parent genre name to
        its id, since the parent is not always among the same title's own interest chips.
        Raises if the directory can't be parsed as expected."""

        if self.__interestNameMap is not None:
            return self.__interestNameMap

        self.browser.get("https://www.imdb.com/interest/all/")
        time.sleep(4)

        links = self.browser.execute_script("""
            return Array.from(document.querySelectorAll('a[href^="/interest/in"]'))
                .map(a => ({text: a.innerText.trim(), href: a.getAttribute('href')}))
                .filter(l => l.text !== '');
        """)

        if len(links) == 0:
            raise EnvironmentError("IMDb interest directory (/interest/all/) returned no entries")

        nameMap = {}
        for link in links:
            match = re.search(r"^/interest/(in\d+)/", link.get("href") or "")
            if not match:
                raise EnvironmentError("interest directory entry href not properly formatted: " + str(link.get("href")))
            nameMap.setdefault(link["text"], set()).add(match.group(1))

        self.__interestNameMap = nameMap
        return nameMap

    def __makeThumbnail(self, in_path, out_path):
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

    def generateThumbnails(self): # generate every missing thumbnail
        print("generating thumbnails...")

        for filename in os.listdir(self.cover_directory):
            if not filename.lower().endswith(".jpg"):
                continue

            in_path = os.path.join(self.cover_directory, filename)

            out_filename = os.path.splitext(filename)[0] + ".webp"
            out_path = os.path.join(self.thumbnail_directory, out_filename)

            if os.path.exists(out_path):
                if os.path.getmtime(in_path) <= os.path.getmtime(out_path):
                    continue
                else:
                    os.remove(out_path)

            try:
                self.__makeThumbnail(in_path, out_path)
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

            self.browser.get(url)
            time.sleep(4)
            soup = BeautifulSoup(self.browser.page_source, 'html.parser')

            if len(soup.find_all("h1", string="Connections")) != 1:
                raise EnvironmentError("connection page did not load properly")

            for connectionType in MediaConnection.connectionTypeList:
                content = soup.find_all(attrs={"href": "#"+connectionType})
                if len(content) > 1:
                    raise EnvironmentError("multiple results for connection type " + connectionType)
                if len(content) == 0:
                    continue
                elementList = content[0].parent.next_sibling.contents[0]

                if elementList.contents[-1].name != "li": # check whether page needs to be dynamically expanded or not
                    count_dyn = 0

                    # dynamic scraping

                    while True:
                        count_dyn += 1
                        if count_dyn > 5:
                            raise EnvironmentError("excessively long loop for page expanding for connection type " + connectionType)

                        element = self.browser.find_element("xpath", "//span[contains(@class, 'single-page-see-more-button-" + connectionType + "')]/button")
                        element.location_once_scrolled_into_view
                        time.sleep(1)
                        self.browser.execute_script("arguments[0].click();", element)
                        time.sleep(3)
                        soup = BeautifulSoup(self.browser.page_source, 'html.parser')

                        content = soup.find_all(attrs={"href": "#"+connectionType})
                        if len(content) != 1:
                            raise EnvironmentError("false results for connection type " + connectionType)
                        elementList = content[0].parent.next_sibling.contents[0]

                        if elementList.contents[-1].name == "li": # check whether page needs to be expanded further
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
        self.browser.get("https://www.imdb.com/title/tt" + str(imdb_id).zfill(7) + "/")
        time.sleep(4)
        soup = BeautifulSoup(self.browser.page_source, 'html.parser')


        expectedValues = {
            "In Development",
            "In Production",
            "Post-production",
            "Pre-production",
            "Coming soon",
            "Completed"
        }

        divs = soup.find_all("div", attrs={"data-testid": "tm-box-up-title"})

        foundExpected = False
        foundOther = False

        for div in divs:
            text = div.get_text(strip=True)
            if text in expectedValues:
                foundExpected = True
            else:
                foundOther = True

        if foundExpected:
            return True
        if foundOther:
            print("WARNING: unknown production status for IMDb ID " + str(imdb_id))

        return False


    def __sleep(self):
        if self.delay > 0:
            time.sleep(random.randint(self.delay - math.ceil(self.delay / 3), self.delay + math.ceil(self.delay / 3)))
