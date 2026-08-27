import requests, re, time, random, math
from bs4 import BeautifulSoup
import os.path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from media import Media
from mediaconnection import MediaConnection
from person import Person
from credit import Credit
from imdbinterestid import parseInterestID, formatInterestID
from exceptions import ScrapingError
from PIL import Image

class ScrapeIMDbOnline:

    headers = {"Accept-Language": "en-US,en;q=0.5", 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.75 Safari/537.36'}

    TARGET_WIDTH = 380
    TARGET_HEIGHT = 562

    # maps the type label IMDb shows in <title> (e.g. "Roundhay Garden Scene (Short 1888) - IMDb")
    # to our internal titleType strings; a plain movie shows no label at all
    titleTypeLabels = {
        "": "movie",
        "Short": "short",
        "Video": "video",
        "TV Movie": "tvMovie",
        "TV Special": "tvSpecial",
        "TV Short": "tvShort",
    }

    def __init__(self, cover_directory, thumbnail_directory, webdriver_path, delay = 0, maxCount = 0, profile_dir = None, headless = False, page_load_wait = 4):
        self.cover_directory = cover_directory
        self.thumbnail_directory = thumbnail_directory
        self.webdriver_path = webdriver_path
        self.delay = delay
        self.maxCount = maxCount
        self.profile_dir = profile_dir
        self.headless = headless
        self.page_load_wait = page_load_wait # seconds to wait after each __navigate for the page to render before scraping its DOM
        self.__interestNameMap = None # lazily-fetched cache, see __getGlobalInterestNameMap

        # the browser itself is started lazily, on first __navigate call -- a sync run that never
        # needs to scrape anything online (nothing newly added) never has to launch Chrome at all
        self.browser = None

    def __launchBrowser(self, headless):
        chrome_options = Options()
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option("useAutomationExtension", False)
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument("--start-maximized")
        if headless:
            chrome_options.add_argument('--headless=new')
        chrome_options.add_argument('--allow-running-insecure-content')
        chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
        if self.profile_dir is not None:
            # reuses cookies/session state across runs (created automatically by Chrome if missing),
            # so IMDb sees a returning browser rather than a brand-new one on every single run
            chrome_options.add_argument(f'--user-data-dir={self.profile_dir}')
        browser = webdriver.Chrome(executable_path = self.webdriver_path, options=chrome_options)
        browser.maximize_window()
        browser.implicitly_wait(10)
        time.sleep(5)
        return browser

    def __isHumanVerificationPage(self):
        # IMDb's bot-detection challenge is a standard AWS WAF CAPTCHA page: <title>Human
        # Verification</title> plus a #captcha-container div the awswaf.com scripts render into.
        # Both are checked (rather than the title alone) since it's the more specific, harder to
        # coincidentally collide with signal -- see a real captured occurrence for tt31195136.
        if self.browser.title != "Human Verification":
            return False
        return len(self.browser.find_elements("id", "captcha-container")) > 0

    def __handleHumanVerification(self, url):
        print("Human verification required -- reopening the browser so you can solve it...")
        self.browser.quit()
        self.browser = self.__launchBrowser(False)
        self.browser.get(url)
        input("Solve the verification in the browser window, then press Enter here to continue...")
        if self.__isHumanVerificationPage():
            raise ScrapingError("human verification still present after manual solve attempt")
        self.browser.quit()
        self.browser = self.__launchBrowser(self.headless)
        self.browser.get(url)
        time.sleep(self.page_load_wait)
        if self.__isHumanVerificationPage():
            raise ScrapingError("human verification still present after browser restart")

    def __navigate(self, url):
        if self.browser is None:
            self.browser = self.__launchBrowser(self.headless)
        self.browser.get(url)
        time.sleep(self.page_load_wait)
        if self.__isHumanVerificationPage():
            self.__handleHumanVerification(url)

    def __del__(self):
        if self.browser is not None:
            self.browser.quit()

    def __printStepHeader(self, number, description):
        """Prints a step-header line matching main.py's syncLocal step numbering, for the steps
        (7, 8, 9, 12, 16) that are owned by a single method here rather than inline in main.py. Only
        ever called once a method has already confirmed it has something to do -- see each
        caller's own emptiness/todo check."""
        print("\nStep " + str(number) + ": " + description)

    def __printProgress(self, index, total, media):
        """Prints a uniform per-title progress line for an online-scraping loop -- used by every
        method here that visits one IMDb page per title (downloadCovers, scrapeMainPages,
        parseMediaConnections, scrapeFullCredits, fillMissingBasics), so the same title/id/count
        format shows up regardless of which of those is currently running."""
        print("  [" + str(index) + "/" + str(total) + "] " + str(media.originalTitle) + " (" + media.getIDString() + ")")

    def restrictToScrapeBudget(self, mediaDict):
        """Restricts mediaDict to at most self.maxCount 'units' before any online scraping starts,
        so a sync run can never be cut off midway through a series: an episode always counts
        together with its parent series (identified via series_imdb_id) as a single unit, rather
        than each episode counting individually. maxCount == 0 means unlimited (the existing
        convention for the config value), in which case mediaDict is returned unchanged. Order of
        first appearance is preserved. Once a unit's budget slot is taken, every entry belonging to
        it is kept regardless of how many episodes that turns out to be -- the cap bounds the number
        of titles considered per run, not the number of online page visits."""
        if not self.maxCount:
            return mediaDict

        selectedUnits = set()
        result = {}
        for imdb_id, medium in mediaDict.items():
            unitKey = medium.series_imdb_id if medium.series_imdb_id is not None else imdb_id
            if unitKey not in selectedUnits:
                if len(selectedUnits) == self.maxCount:
                    continue
                selectedUnits.add(unitKey)
            result[imdb_id] = medium
        return result

    def downloadCovers(self, mediaDict):
        """Downloads a cover for every medium in mediaDict that doesn't already have one on disk.
        Silent (no step header, no output at all) if every medium already has a cover file --
        matches every other step's "only announce it if there's actually something to do" rule."""

        todo = [m for m in mediaDict.values() if not os.path.isfile(os.path.join(self.cover_directory, m.getIDString() + ".jpg"))]
        if len(todo) == 0:
            return

        self.__printStepHeader(16, "recovering missing covers")

        count = 0

        for i, currentMedia in enumerate(todo, 1):
            self.__printProgress(i, len(todo), currentMedia)

            coverPath = os.path.join(self.cover_directory, currentMedia.getIDString() + ".jpg")
            self.__navigate("https://www.imdb.com/title/" + currentMedia.getIDString() + "/")

            self.__downloadCoverFromLoadedMainPage(currentMedia, coverPath)

            count += 1
            if count == self.maxCount:
                return

            self.__sleep()

    def scrapeMainPages(self, mediaDict, knownInterestIDs, knownLanguageIDs, knownPseudoGenreIDs, knownFranchiseIDs):
        """For every medium in mediaDict, visits its IMDb main page (and possibly, briefly, one or
        more /interest/<id>/ pages while classifying newly-discovered chips) and:
        - always scrapes its interests (standard genres and subgenres alike), language and plot summary
        - downloads its cover if the file doesn't already exist, unless it's a series or its
          language turns out non-English (covers for both are always added manually, never
          auto-downloaded -- see main.py's downloadCovers call for the matching exclusion on the
          cover-backfill path)

        knownInterestIDs/knownLanguageIDs are sets of already-known IMDb interest ids; both are
        mutated in place as new ones are discovered. knownPseudoGenreIDs is a name -> id map of
        already-known pseudo-genres (see __classifyChips), also mutated in place. knownFranchiseIDs
        is a set of already-seen franchise-type interest ids (ignored entirely, see __classifyChips),
        also mutated in place. A title with no language-type interest attached keeps Media's default
        language_id of 0 (English). Returns (newInterestRegistrations, newLanguageRegistrations,
        newFranchiseRegistrations): newInterestRegistrations is a list of (imdb_interest_id, name,
        description, parent_imdb_interest_id) tuples in dependency order (a subgenre's parent always
        appears before the subgenre itself); newLanguageRegistrations is a list of (imdb_interest_id,
        name, description) tuples; newFranchiseRegistrations is a list of (imdb_interest_id, name)
        tuples. Persist via DBControl.ensureInterestExists()/ensureLanguageExists()/
        ensureFranchiseInterestExists() in the order returned."""

        if len(mediaDict) == 0:
            return [], [], []

        self.__printStepHeader(7, "scraping main pages (interests, language, covers)")

        newInterestRegistrations = []
        newLanguageRegistrations = []
        newFranchiseRegistrations = []
        first = True

        for i, currentMedia in enumerate(mediaDict.values(), 1):
            if first:
                first = False
            else:
                self.__sleep()

            self.__printProgress(i, len(mediaDict), currentMedia)

            self.__navigate("https://www.imdb.com/title/" + currentMedia.getIDString() + "/")

            chips = self.__scrapeInterestChips()
            currentMedia.plotSummary = self.__scrapePlotSummary()

            attachedInterestIDs, newInterestRegs, newLanguageRegs, languageID, newFranchiseRegs, navigatedAway = self.__classifyChips(chips, knownInterestIDs, knownLanguageIDs, knownPseudoGenreIDs, knownFranchiseIDs)
            currentMedia.interests = attachedInterestIDs
            if languageID is not None:
                currentMedia.language_id = languageID
            newInterestRegistrations.extend(newInterestRegs)
            newLanguageRegistrations.extend(newLanguageRegs)
            newFranchiseRegistrations.extend(newFranchiseRegs)

            # cover download needs the browser back on the title's own main page -- classifying
            # newly-discovered interests above may have navigated away to separate /interest/...
            # pages, so only re-navigate (an extra page load) when that actually happened. Series
            # are excluded -- IMDb only offers the latest season's cover as a series' "main" image,
            # which isn't what should represent the whole series locally. Non-English movies get
            # the same manual-only treatment as series (by explicit choice, not auto-downloaded);
            # in both cases a cover is instead added manually (see main.py's downloadCovers call
            # for the matching exclusion on the cover-backfill path). titleType is still the
            # local-scrape placeholder here ("localSeries"), since offline parsing hasn't resolved
            # it to a real IMDb type yet.
            if currentMedia.titleType not in ["localSeries"] + Media.seriesTitleTypes and currentMedia.language_id == 0:
                coverPath = os.path.join(self.cover_directory, currentMedia.getIDString() + ".jpg")
                if not os.path.isfile(coverPath):
                    if navigatedAway:
                        self.__navigate("https://www.imdb.com/title/" + currentMedia.getIDString() + "/")
                    self.__downloadCoverFromLoadedMainPage(currentMedia, coverPath)

        return newInterestRegistrations, newLanguageRegistrations, newFranchiseRegistrations

    def fillMissingBasics(self, mediaDict):
        """For locally-owned titles missing from the offline IMDb datasets (flagged via
        needsOnlineFallback), scrapes titleType, primaryTitle, originalTitle, startYear
        (cross-checked against the already-known local value), endYear, rating and vote
        count from the title's main page. The locally-parsed folder name is not trusted as
        a source for originalTitle; it's scraped from the page's separate "Original title:"
        line when shown, or set equal to primaryTitle when it isn't (i.e. they're the same).
        Vote counts abbreviated by IMDb (e.g. "7.7K") are accepted as an approximation
        (printed to stdout when this happens) rather than an exact figure, since that's
        all that's available once a title crosses IMDb's abbreviation threshold. Raises
        on anything else unexpected."""

        if len(mediaDict) == 0:
            return

        self.__printStepHeader(12, "online fallback for titles missing from the offline dataset")

        first = True
        for i, currentMedia in enumerate(mediaDict.values(), 1):
            if first:
                first = False
            else:
                self.__sleep()

            self.__printProgress(i, len(mediaDict), currentMedia)

            self.__navigate("https://www.imdb.com/title/" + currentMedia.getIDString() + "/")

            # title type, from the document title's "(<type> <year>) - IMDb" suffix
            localTitleType = currentMedia.titleType # "localMovie" or "localSeries", set during local scraping

            docTitle = self.browser.execute_script("return document.title;")
            match = re.search(r"\(([^()]*?)\d{4}(?:–\d{4})?\)\s*-\s*IMDb$", docTitle or "")
            if not match:
                raise ScrapingError("could not parse title type/year from document title: " + str(docTitle))
            typeLabel = match.group(1).strip()
            if typeLabel not in self.titleTypeLabels:
                raise ScrapingError("unknown title type label '" + typeLabel + "' for " + currentMedia.getIDString())
            scrapedTitleType = self.titleTypeLabels[typeLabel]

            if ((localTitleType == "localMovie" and scrapedTitleType not in Media.movieTitleTypes)
                or (localTitleType == "localSeries" and scrapedTitleType not in Media.seriesTitleTypes)):
                raise ScrapingError("title type " + scrapedTitleType + " not acceptable for local parsing result " + localTitleType)

            currentMedia.titleType = scrapedTitleType

            # primary title
            primaryTitle = self.browser.execute_script("""
                const el = document.querySelector('[data-testid="hero__pageTitle"]');
                return el ? el.innerText.trim() : null;
            """)
            if not primaryTitle:
                raise ScrapingError("could not find primary title for " + currentMedia.getIDString())
            currentMedia.primaryTitle = primaryTitle

            # original title: only shown separately from the primary title when they differ
            # (e.g. https://www.imdb.com/title/tt36459128/); falls back to the primary title
            # otherwise. The locally-parsed folder name is not used as a source here.
            origTitleMatches = self.browser.execute_script("""
                const hero = document.querySelector('[data-testid="hero-parent"]');
                if (!hero) return null;
                return Array.from(hero.querySelectorAll('div'))
                    .filter(el => el.children.length === 0 && el.textContent.trim().startsWith('Original title:'))
                    .map(el => el.innerText.trim());
            """)
            if origTitleMatches is None:
                raise ScrapingError("hero section not found for " + currentMedia.getIDString())
            if len(origTitleMatches) > 1:
                raise ScrapingError("multiple 'Original title:' elements found for " + currentMedia.getIDString())
            if len(origTitleMatches) == 1:
                originalTitle = origTitleMatches[0][len("Original title:"):].strip()
                if not originalTitle:
                    raise ScrapingError("empty original title for " + currentMedia.getIDString())
                currentMedia.originalTitle = originalTitle
            else:
                currentMedia.originalTitle = primaryTitle

            # release year, cross-checked against the already-known (locally-parsed) year
            yearLinks = self.browser.execute_script("""
                const hero = document.querySelector('[data-testid="hero-parent"]');
                if (!hero) return null;
                return Array.from(hero.querySelectorAll('a[href*="/releaseinfo"]')).map(a => a.innerText.trim());
            """)
            if yearLinks is None or len(yearLinks) != 1 or not re.fullmatch(r"\d{4}", yearLinks[0]):
                raise ScrapingError("could not uniquely determine release year for " + currentMedia.getIDString() + ": " + str(yearLinks))
            scrapedYear = int(yearLinks[0])
            if currentMedia.startYear is not None and currentMedia.startYear != scrapedYear:
                raise ScrapingError("startYear mismatch for " + currentMedia.getIDString() + ": local=" + str(currentMedia.startYear) + " vs scraped=" + str(scrapedYear))
            currentMedia.startYear = scrapedYear
            currentMedia.endYear = None # movies only; series are not supported

            # rating and vote count
            scoreText = self.browser.execute_script("""
                const el = document.querySelector('[data-testid="hero-rating-bar__aggregate-rating__score"]');
                return el ? el.innerText.trim() : null;
            """)
            voteText = self.browser.execute_script("""
                const el = document.querySelector('[data-testid="rating-histogram-vote-count"]');
                return el ? el.innerText.trim() : null;
            """)

            if scoreText is None and voteText is None:
                currentMedia.rating_mul10 = None
                currentMedia.numVotes = None
            elif scoreText is not None and voteText is not None:
                scoreMatch = re.fullmatch(r"(\d+\.\d)\s*/\s*10", scoreText.replace("\n", ""))
                if not scoreMatch:
                    raise ScrapingError("could not parse rating score '" + scoreText + "' for " + currentMedia.getIDString())
                rating_mul10 = int(scoreMatch.group(1).replace('.', ''))
                if rating_mul10 < 10 or rating_mul10 > 100:
                    raise ScrapingError("rating conversion problem for " + currentMedia.getIDString())
                currentMedia.rating_mul10 = rating_mul10

                voteMatch = re.fullmatch(r"(\d+(?:\.\d+)?)(K|M)?", voteText)
                if not voteMatch:
                    raise ScrapingError("could not parse vote count '" + voteText + "' for " + currentMedia.getIDString())
                voteValue = float(voteMatch.group(1))
                voteSuffix = voteMatch.group(2)
                if voteSuffix == "K":
                    currentMedia.numVotes = round(voteValue * 1_000)
                elif voteSuffix == "M":
                    currentMedia.numVotes = round(voteValue * 1_000_000)
                else:
                    currentMedia.numVotes = round(voteValue)

                if voteSuffix is not None:
                    print("INFO: vote count for " + currentMedia.getIDString() + " is approximate (" + voteText + " ~= " + str(currentMedia.numVotes) + ")")
            else:
                raise ScrapingError("inconsistent rating state for " + currentMedia.getIDString() + ": score=" + str(scoreText) + " votes=" + str(voteText))

            currentMedia.needsOnlineFallback = False

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
            raise ScrapingError("no unique cover tag found")

        # scrape cover page
        self.__navigate("https://www.imdb.com" + matches[0])

        matches = self.browser.execute_script("""
            return Array.from(document.querySelectorAll('[property]'))
                .filter(el => (el.getAttribute('property') || '') === "og:image")
                .map(el => el.getAttribute('content'));
        """)

        if len(matches) != 1:
            raise ScrapingError("no unique cover tag found")

        link_parts = matches[0].rsplit('.', 2)
        if len(link_parts) != 3 or link_parts[2] != "jpg":
            raise ScrapingError("cover link not properly formatted: " + currentMedia.getIDString() + " - " + matches[0])
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
            raise ScrapingError("expected exactly one interests block on title page, found " + str(box_count))

        chips = self.browser.execute_script("""
            const box = document.querySelector('[data-testid="interests"]');
            return Array.from(box.querySelectorAll('a')).map(a => ({
                text: a.innerText,
                href: a.getAttribute('href')
            }));
        """)

        if len(chips) == 0:
            raise ScrapingError("interests block present but contains no chips")

        result = []
        seenIDs = set()
        for chip in chips:
            match = re.search(r"^/interest/(in\d+)/", chip.get("href") or "")
            if not match:
                raise ScrapingError("interest chip href not properly formatted: " + str(chip.get("href")))
            chip_id = parseInterestID(match.group(1))
            name = (chip.get("text") or "").strip()
            if name == "":
                raise ScrapingError("interest chip has empty name: " + str(chip_id))
            if chip_id in seenIDs:
                raise ScrapingError("duplicate interest chip on page: " + str(chip_id))
            seenIDs.add(chip_id)
            result.append((chip_id, name))

        return result

    def __scrapePlotSummary(self):
        """Scrapes the plot summary from the currently-loaded title main page. Its underlying text
        content is always the full summary regardless of viewport (IMDb truncates it visually via
        CSS at narrower breakpoints, not in the DOM), so no "Read all"/"..." handling is needed.
        Raises on any unexpected structure, rather than silently skipping or guessing."""

        box_count = self.browser.execute_script('return document.querySelectorAll(\'[data-testid="plot"]\').length;')
        if box_count != 1:
            raise ScrapingError("expected exactly one plot summary block on title page, found " + str(box_count))

        plotSummary = self.browser.execute_script("""
            const box = document.querySelector('[data-testid="plot"]');
            return box.innerText.trim();
        """)
        if not plotSummary:
            raise ScrapingError("plot summary block present but empty")

        return plotSummary

    def __classifyChips(self, chips, knownInterestIDs, knownLanguageIDs, knownPseudoGenreIDs, knownFranchiseIDs):
        """Classifies every (imdb_interest_id, name) in chips as a top-level interest (IMDb's hero
        page labels these "Genre" for most, but "Form" for e.g. Documentary/Short and "Style" for
        Anime -- all three are treated identically here, just different IMDb labels for the same
        parentless-interest role), subgenre, language, or franchise, visiting each not-yet-known
        id's IMDb interest page to determine which and scrape its description text. A subgenre's
        parent is NOT necessarily among the same title's other chips (a title can carry a subgenre
        without also being tagged with its parent directly), so the parent's id is resolved against
        IMDb's full interest directory instead. The parent is registered first if it too is new.
        knownInterestIDs/knownLanguageIDs are mutated in place.

        Franchise-type interests (e.g. "Evil Dead") are recognized but deliberately ignored --
        never attached to the title and never registered in interest_enum at all -- since that
        relationship is already covered via IMDb connection parsing (see MediaConnection). Only
        the type check runs for them; their description/parent category is never even scraped.
        knownFranchiseIDs is a set of already-seen franchise ids (see DBControl.getAllKnownFranchiseIDs/
        ensureFranchiseInterestExists), mutated in place, so a franchise is only ever classified once
        (an extra IMDb page visit) across all syncs, not just the current one.

        A subgenre's breadcrumb "parent category" text is sometimes not a real, individually
        taggable genre interest at all -- e.g. "Holiday Comedy"'s breadcrumb is "Seasonal", which
        doesn't appear anywhere in IMDb's interest directory; IMDb uses it purely to group several
        subgenres on the browse-all-interests page. When that happens, a synthetic pseudo-genre
        (a negative, self-minted id -- real ids are always positive) is registered/reused as the
        parent instead of failing, via knownPseudoGenreIDs (a name -> id map, mutated in place,
        shared across the whole sync so the same category always resolves to the same id).

        Returns (attachedInterestIDs, newInterestRegistrations, newLanguageRegistrations,
        languageID, newFranchiseRegistrations, navigatedAway): attachedInterestIDs are the
        genre/subgenre ids actually attached to this title (for media_interests -- language ids
        are never included); newInterestRegistrations is a list of (imdb_interest_id, name,
        description, parent_imdb_interest_id) tuples; newLanguageRegistrations is a list of
        (imdb_interest_id, name, description) tuples; languageID is this title's language_id if a
        language chip was found, else None; newFranchiseRegistrations is a list of
        (imdb_interest_id, name) tuples -- persist via DBControl.ensureFranchiseInterestExists()
        in the order returned; navigatedAway is True if classifying any chip navigated the browser
        away from the title's own main page (to a /interest/<id>/ page), False if every chip was
        already known and the browser never left -- callers that need to be back on the main page
        afterwards (e.g. to download the cover) should check this rather than assume either way.

        Raises on any unexpected structure (unknown type, missing description, ambiguous parent,
        more than two genre/subgenre taxonomy levels, more than one language attached)."""

        attachedInterestIDs = []
        newInterestRegistrations = []
        newLanguageRegistrations = []
        newFranchiseRegistrations = []
        languageID = None
        navigatedAway = False

        # IMDb labels a top-level (parentless) interest's hero type differently depending on what
        # kind of category it is -- "Genre" for most (Drama, Comedy, ...), but "Form" for things
        # like Documentary/Short and "Style" for Anime. All three behave identically here: no real
        # parent category, registered the same way in interest_enum. A "Style"-type interest's
        # breadcrumb is a self-reference to its own name rather than empty (seen for Anime) -- still
        # not a real parent, so that's tolerated below rather than treated as one.
        topLevelTypes = ("Genre", "Form", "Style")

        def classify(interest_id, name):
            nonlocal navigatedAway
            navigatedAway = True
            self.__navigate("https://www.imdb.com/interest/" + formatInterestID(interest_id) + "/")

            typeText = self.browser.execute_script("""
                const el = document.querySelector('[data-testid="interest-hero-type"]');
                return el ? el.innerText.trim() : null;
            """)
            if typeText not in topLevelTypes + ("Subgenre", "Language", "Franchise"):
                raise ScrapingError("unexpected interest type '" + str(typeText) + "' for " + str(interest_id) + " (" + name + ")")

            if typeText == "Franchise":
                return ("Franchise", None, None)

            categoryTexts = self.browser.execute_script("""
                const header = document.querySelector('[data-testid="interest-hero-header"]');
                if (!header) return null;
                return Array.from(header.querySelectorAll('[data-testid="hero-breadcrumb-category"]')).map(a => a.innerText.trim());
            """)
            if categoryTexts is None:
                raise ScrapingError("interest hero header not found for " + str(interest_id))

            description = self.browser.execute_script("""
                const box = document.querySelector('[data-testid="interest-description-and-chips"]');
                if (!box) return null;
                const descEls = box.querySelectorAll('.ipc-overflowText');
                return descEls.length === 1 ? descEls[0].innerText.trim() : null;
            """)
            if not description:
                raise ScrapingError("could not find description text for interest " + str(interest_id) + " (" + name + ")")

            if typeText in topLevelTypes or typeText == "Language":
                realParents = set(categoryTexts) - {name}
                if len(realParents) != 0:
                    raise ScrapingError(typeText + "-type interest unexpectedly has a parent category: " + str(interest_id))
                return (typeText, None, description)
            else:
                distinctParents = set(categoryTexts)
                if len(distinctParents) != 1:
                    raise ScrapingError("could not determine a single parent category for subgenre " + str(interest_id) + ": " + str(distinctParents))
                return ("Subgenre", next(iter(distinctParents)), description)

        for chip_id, chip_name in chips:
            if chip_id in knownInterestIDs:
                attachedInterestIDs.append(chip_id)
                continue

            if chip_id in knownLanguageIDs:
                if languageID is not None:
                    raise ScrapingError("multiple language interests attached to the same title")
                languageID = chip_id
                continue

            if chip_id in knownFranchiseIDs:
                continue

            typeText, parentName, description = classify(chip_id, chip_name)

            if typeText == "Franchise":
                newFranchiseRegistrations.append((chip_id, chip_name))
                knownFranchiseIDs.add(chip_id)
                continue

            if typeText in topLevelTypes:
                newInterestRegistrations.append((chip_id, chip_name, description, None))
                knownInterestIDs.add(chip_id)
                attachedInterestIDs.append(chip_id)
                continue

            if typeText == "Language":
                if languageID is not None:
                    raise ScrapingError("multiple language interests attached to the same title")
                newLanguageRegistrations.append((chip_id, chip_name, description))
                knownLanguageIDs.add(chip_id)
                languageID = chip_id
                continue

            candidates = self.__getGlobalInterestNameMap().get(parentName)
            if candidates:
                if len(candidates) != 1:
                    raise ScrapingError("parent genre '" + parentName + "' for subgenre " + str(chip_id) + " (" + chip_name + ") not uniquely found in IMDb's interest directory: " + str(candidates))
                parent_id = next(iter(candidates))

                if parent_id not in knownInterestIDs:
                    parentType, parentParentName, parentDescription = classify(parent_id, parentName)
                    if parentType not in topLevelTypes:
                        raise ScrapingError("expected '" + parentName + "' to be a top-level genre, but it is a " + parentType)
                    newInterestRegistrations.append((parent_id, parentName, parentDescription, None))
                    knownInterestIDs.add(parent_id)
            elif parentName in knownPseudoGenreIDs:
                parent_id = knownPseudoGenreIDs[parentName]
            else:
                # not a real genre interest -- see this method's docstring
                parent_id = min(knownPseudoGenreIDs.values(), default=0) - 1
                knownPseudoGenreIDs[parentName] = parent_id
                newInterestRegistrations.append((parent_id, parentName,
                    "A category IMDb groups related subgenres under, without itself being a taggable interest.",
                    None))
                knownInterestIDs.add(parent_id)

            newInterestRegistrations.append((chip_id, chip_name, description, parent_id))
            knownInterestIDs.add(chip_id)
            attachedInterestIDs.append(chip_id)

        return attachedInterestIDs, newInterestRegistrations, newLanguageRegistrations, languageID, newFranchiseRegistrations, navigatedAway

    def __getGlobalInterestNameMap(self):
        """Lazily fetches and caches IMDb's full interest directory (/interest/all/) as a
        name -> set(imdb_interest_id) map. Used to resolve a subgenre's parent genre name to
        its id, since the parent is not always among the same title's own interest chips.
        Raises if the directory can't be parsed as expected."""

        if self.__interestNameMap is not None:
            return self.__interestNameMap

        self.__navigate("https://www.imdb.com/interest/all/")

        links = self.browser.execute_script("""
            return Array.from(document.querySelectorAll('a[href^="/interest/in"]'))
                .map(a => ({text: a.innerText.trim(), href: a.getAttribute('href')}))
                .filter(l => l.text !== '');
        """)

        if len(links) == 0:
            raise ScrapingError("IMDb interest directory (/interest/all/) returned no entries")

        nameMap = {}
        for link in links:
            match = re.search(r"^/interest/(in\d+)/", link.get("href") or "")
            if not match:
                raise ScrapingError("interest directory entry href not properly formatted: " + str(link.get("href")))
            nameMap.setdefault(link["text"], set()).add(parseInterestID(match.group(1)))

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

    def generateThumbnails(self): # generate every missing/outdated thumbnail
        todo = []
        for filename in os.listdir(self.cover_directory):
            if not filename.lower().endswith(".jpg"):
                continue

            in_path = os.path.join(self.cover_directory, filename)
            out_filename = os.path.splitext(filename)[0] + ".webp"
            out_path = os.path.join(self.thumbnail_directory, out_filename)

            if os.path.exists(out_path) and os.path.getmtime(in_path) <= os.path.getmtime(out_path):
                continue
            todo.append((filename, in_path, out_path))

        if len(todo) == 0:
            return

        print("  generating thumbnails...")

        for filename, in_path, out_path in todo:
            if os.path.exists(out_path):
                os.remove(out_path)

            # a corrupt/unreadable cover file is not worth aborting the whole sync over -- thumbnails
            # are a derived, non-critical asset, unlike the structural DB data everything else here
            # fails loudly over -- so this is deliberately caught broadly and just reported
            try:
                self.__makeThumbnail(in_path, out_path)
            except Exception as e:
                print("WARNING: failed to generate thumbnail for " + filename + ": " + str(e))

    def parseMediaConnections(self, mediaDict):

        if len(mediaDict) == 0:
            return mediaDict

        resultDict = {}

        self.__printStepHeader(8, "parsing media connections")

        first = True
        for i, currentMedia in enumerate(mediaDict.values(), 1):

            if first:
                first = False
            else:
                self.__sleep()

            self.__printProgress(i, len(mediaDict), currentMedia)

            # enter medium into result dict
            resultDict[currentMedia.imdb_id] = currentMedia

            # scrape IMDb media movie connections page
            url = "https://www.imdb.com/title/" + currentMedia.getIDString() + "/movieconnections"

            self.__navigate(url)
            soup = BeautifulSoup(self.browser.page_source, 'html.parser')

            if len(soup.find_all("h1", string="Connections")) != 1:
                raise ScrapingError("connection page did not load properly")

            for connectionType in MediaConnection.connectionTypeList:
                content = soup.find_all(attrs={"href": "#"+connectionType})
                if len(content) > 1:
                    raise ScrapingError("multiple results for connection type " + connectionType)
                if len(content) == 0:
                    continue
                elementList = content[0].parent.next_sibling.contents[0]

                if elementList.contents[-1].name != "li": # check whether page needs to be dynamically expanded or not
                    count_dyn = 0

                    # dynamic scraping

                    while True:
                        count_dyn += 1
                        if count_dyn > 5:
                            raise ScrapingError("excessively long loop for page expanding for connection type " + connectionType)

                        element = self.browser.find_element("xpath", "//span[contains(@class, 'single-page-see-more-button-" + connectionType + "')]/button")
                        element.location_once_scrolled_into_view
                        time.sleep(1)
                        self.browser.execute_script("arguments[0].click();", element)
                        time.sleep(3)
                        soup = BeautifulSoup(self.browser.page_source, 'html.parser')

                        content = soup.find_all(attrs={"href": "#"+connectionType})
                        if len(content) != 1:
                            raise ScrapingError("false results for connection type " + connectionType)
                        elementList = content[0].parent.next_sibling.contents[0]

                        if elementList.contents[-1].name == "li": # check whether page needs to be expanded further
                            break

                for element in elementList.children:
                    if element.contents[0].name != "div":
                        raise ScrapingError("connection scraping error")
                    if element.contents[0].contents[0].name != "ul":
                        raise ScrapingError("connection scraping error")
                    if element.contents[0].contents[0].contents[0].name != "div":
                        raise ScrapingError("connection scraping error")
                    if element.contents[0].contents[0].contents[0].contents[0].name != "div":
                        raise ScrapingError("connection scraping error")
                    if element.contents[0].contents[0].contents[0].contents[0].contents[0].name != "p":
                        raise ScrapingError("connection scraping error")
                    if element.contents[0].contents[0].contents[0].contents[0].contents[0].contents[0].name != "a":
                        raise ScrapingError("connection scraping error")

                    targetUrl = element.contents[0].contents[0].contents[0].contents[0].contents[0].contents[0]['href']
                    if targetUrl[0:7] != "/title/":
                        raise ScrapingError("connection scraping error")
                    targetUrl = targetUrl[7:]
                    foreignIMDbID = targetUrl.split('?')[0]

                    if foreignIMDbID[-1] == "/":
                        foreignIMDbID = foreignIMDbID[:-1]

                    if not re.search("^tt\d{7,8}$", foreignIMDbID):
                        raise ScrapingError("illegal foreign imdb id " + foreignIMDbID)

                    # check for duplicate imdb connection entries (it happens)
                    duplicate = False
                    for x in resultDict[currentMedia.imdb_id].mediaConnections:
                        if x.foreignIMDbID == int(foreignIMDbID[2:]) and x.connectionType == connectionType:
                            duplicate = True
                            break
                    if duplicate:
                        continue

                    resultDict[currentMedia.imdb_id].mediaConnections.append(MediaConnection(int(foreignIMDbID[2:]), connectionType))

        return resultDict

    def scrapeFullCredits(self, mediaDict, knownPersonIDs):
        """For every medium in mediaDict, visits its IMDb fullcredits page and records director/
        writer/actor credits directly onto that medium's own .credits list (see Credit), as one
        running `ordering` sequence per medium across all three roles in the page's own order
        (director(s), then writer(s), then actor(s)). "Actor" covers both actors and actresses,
        matching IMDb's own "Cast" section label; every other section on the page (producers,
        composer, etc.) is ignored entirely. Both credited and "(uncredited)" entries are included.
        A Cast section IMDb splits into a primary list plus a "Rest of cast listed alphabetically"
        continuation (rendered as a second, separate sub-list) is scraped as one combined sequence,
        since credit rows are located generically within the whole enclosing section rather than
        by picking out a single expected sub-list.

        A credited person not yet known (not in knownPersonIDs) is minted here as a Person stub --
        name is whatever was scraped from this page, a placeholder until
        ScrapeIMDbOffline.parsePeople resolves the authoritative name.basics.tsv name (see Person).
        knownPersonIDs is mutated in place, mirroring knownInterestIDs/knownLanguageIDs elsewhere.
        Returns newPersonRegistrations: a list of such Person stubs, in order of first appearance,
        for the caller to run through ScrapeIMDbOffline.parsePeople and persist before this run's
        write.

        Raises ScrapingError on any unexpected structure (missing person link, an unrecognized
        credits-list-item shape)."""

        if len(mediaDict) == 0:
            return []

        self.__printStepHeader(9, "scraping full credits (director/writer/actor)")

        newPersonRegistrations = []
        first = True

        for i, currentMedia in enumerate(mediaDict.values(), 1):
            if first:
                first = False
            else:
                self.__sleep()

            self.__printProgress(i, len(mediaDict), currentMedia)

            self.__navigate("https://www.imdb.com/title/" + currentMedia.getIDString() + "/fullcredits/")
            soup = BeautifulSoup(self.browser.page_source, 'html.parser')

            ordering = 0
            for creditRole, headingText, exactMatch in (
                ("director", "Director", False), # "Director" or "Directors"
                ("writer", "Writer", False),      # "Writer" or "Writers"
                ("actor", "Cast", True),
            ):
                matchingHeadings = [h for h in soup.find_all("h3") if
                                     (h.get_text(strip=True) == headingText if exactMatch
                                      else h.get_text(strip=True).startswith(headingText))]
                if len(matchingHeadings) == 0:
                    continue # e.g. no credited writer at all -- tolerated, not every title has one
                if len(matchingHeadings) > 1:
                    raise ScrapingError("multiple '" + headingText + "' headings found on " + currentMedia.getIDString() + "/fullcredits/")
                section = matchingHeadings[0].find_parent("section")
                if section is None:
                    raise ScrapingError("could not find enclosing section for '" + headingText + "' heading on " + currentMedia.getIDString() + "/fullcredits/")

                for li in section.find_all("li", attrs={"data-testid": "name-credits-list-item"}):
                    # every credits-list-item observed carries the person's name twice (once from
                    # each of two duplicate links IMDb renders), followed optionally by role/detail
                    # text (a character name for cast, a credit qualifier like "original story by &"
                    # for writers, "(uncredited)"/"(voice)" suffixes, etc.) -- reading this generically
                    # via stripped_strings rather than hard-coding which element holds what text is
                    # what lets the same code handle director/writer/cast rows uniformly, split-cast
                    # continuations, and any of these qualifier variants without special-casing them
                    texts = list(li.stripped_strings)
                    if len(texts) < 2 or texts[0] != texts[1]:
                        raise ScrapingError("unexpected credits list item structure on " + currentMedia.getIDString() + "/fullcredits/: " + str(texts))

                    nameLink = li.find("a", href=re.compile(r"^/name/nm\d+/"))
                    if nameLink is None:
                        raise ScrapingError("no person link found in credits list item on " + currentMedia.getIDString() + "/fullcredits/: " + str(texts))
                    person_id = int(re.match(r"^/name/nm(\d+)/", nameLink["href"]).group(1))

                    creditDetails = " ".join(texts[2:]) if len(texts) > 2 else None

                    if person_id not in knownPersonIDs:
                        knownPersonIDs.add(person_id)
                        newPersonRegistrations.append(Person(person_id, texts[0]))

                    ordering += 1
                    currentMedia.credits.append(Credit(person_id, ordering, creditRole, creditDetails))

        return newPersonRegistrations

    def isInDevelopment(self, imdb_id):
        # scrape IMDb media main page. IMDb apparently shows an in-production title's status via
        # one of two independent, coexisting mechanisms depending on the title -- checked here as
        # two separate signals, OR'd together, since neither alone covers every case (confirmed
        # against real occurrences: tt16744566 "Sonic the Hedgehog 4" only has the older badge
        # below, "Post-production"; tt14722868 "10,000 Ships" only has the newer link, "In
        # development: More at IMDbPro"; tt0903747 "Breaking Bad" has neither, a normal released
        # title):
        # 1. the older [data-testid="tm-box-up-title"] badge, matched against a known status
        #    vocabulary (case-sensitive as IMDb renders it here, e.g. "Post-production")
        # 2. the hero subnav's IMDbPro link, which reads plain "IMDbPro" normally but
        #    "<status>: More at IMDbPro" (e.g. "In development: More at IMDbPro", lowercase 'd' --
        #    a different casing convention than #1's vocabulary, treated as a separate signal
        #    rather than folded into the same vocabulary check) when in production; presence of a
        #    colon is the signal, not an exact-vocabulary match
        self.__navigate("https://www.imdb.com/title/tt" + str(imdb_id).zfill(7) + "/")
        soup = BeautifulSoup(self.browser.page_source, 'html.parser')

        expectedValues = {
            "In Development",
            "In Production",
            "Post-production",
            "Pre-production",
            "Coming soon",
            "Completed",
            "Abandoned" # never finished/released, so never getting real rating data either -- see tt6857128
        }

        statusBadge = soup.find("div", attrs={"data-testid": "tm-box-up-title"})
        if statusBadge is not None:
            text = statusBadge.get_text(strip=True)
            if text in expectedValues:
                return True
            raise ScrapingError("unknown production status '" + text + "' for IMDb ID " + str(imdb_id))

        proLink = soup.find(attrs={"data-testid": "hero-subnav-bar-imdb-pro-link"})
        if proLink is None:
            raise ScrapingError("could not find IMDbPro link to determine production status for IMDb ID " + str(imdb_id))
        elif ":" in proLink.get_text(strip=True):
            return True

        return False


    def __sleep(self):
        if self.delay > 0:
            time.sleep(random.randint(self.delay - math.ceil(self.delay / 3), self.delay + math.ceil(self.delay / 3)))
