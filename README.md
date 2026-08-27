# media-control

Framework for storing and displaying a local collection of movies and TV series, and assisting playback.

Management functionality is similar to the ones of Plex or Kodi, but specifically tailored to the author's needs and with full control over the local (sqlite) database. Incorporates IMDb scraping for detailed information about individual movies and series.

## Features

- Scans a local media library and syncs it into a SQLite database. Movies live in one subdirectory each, named `Title_Year_ttIMDbID`; series use the same convention for the series folder, with episodes inside per-season subfolders (`S01`, `S02`, ...). Kaleidescape-owned titles (no local media file) are supported via empty `.kscape` placeholder files, usable interchangeably with real `.mkv` files.
- Enriches entries with IMDb data: cover art and thumbnails, ratings, vote counts, genres/subgenres, language, plot summaries, connections to related titles (sequels, remakes, spin-offs, alternate-language versions, ...), and director/writer/actor credits (including uncredited appearances) with each person's name, birth year and death year.
- Uses IMDb's downloadable offline datasets for bulk metadata (including each series' full episode catalog and per-person details), and Selenium-based online scraping for covers, subgenres/language, title connections, and full cast/crew credits (scraped per-episode as well as per-movie/series, since a series' director/writer/cast can vary by episode). Movie covers are only auto-downloaded for English-language titles; series and non-English movie covers must be added manually.
- Runs [MediaInfo](https://mediaarea.net/en/MediaInfo) against each newly-added local file to record detailed video/audio/subtitle track information (codec, resolution, HDR metadata, bitrate, languages, ...).
- Flask web UI for browsing/searching/filtering the collection (by title, year, rating, votes, genre/subgenre, movies vs. series), including per-series episode ownership.
- Basic statistics (yearly counts/ratings charts, franchise/connection clustering) via matplotlib.

## Requirements

- Python 3
- `pip install -r requirements.txt`
- A Selenium-compatible driver (e.g. [chromedriver](https://chromedriver.chromium.org/)) matching your installed browser
- The [MediaInfo CLI](https://mediaarea.net/en/MediaInfo/Download) executable, for analyzing locally-owned media files
- IMDb's [offline dataset files](https://datasets.imdbws.com/) downloaded locally (`title.basics` / `title.ratings` / `title.episode` / `name.basics`)

## Configuration

All local paths and settings live in `config.ini`, which is not tracked in git (it's specific to your machine). To set up:

```bash
cp config.example.ini config.ini
```

Then edit `config.ini` with your own paths:

- `media_dir` — root directory of your local media library
- `db_path`, `covers_dir`, `covers_small_dir` — where the database and cover images are stored (relative paths resolve against the project directory)
- `webdriver_path` — path to your chromedriver executable
- `mediainfo_path` — path to the MediaInfo CLI executable
- `chrome_profile_dir` — persistent Chrome profile (cookies/session state), reused across runs
- `imdb_datasets_dir` — directory containing the downloaded IMDb offline datasets
- `ignored_ids_path` / `wontadd_ids_path` — text files of IMDb ids (one per line) to keep out of the database entirely, or to allow only as referenced (not locally-owned) media
- `hidden_interest_ids_path` — text file of subgenre interest ids to keep out of the web UI's filter list
- `delay` / `max_count` — throttling for online IMDb scraping (`max_count` counts a series and all its episodes as a single title)
- `headless` / `page_load_wait` — Chrome headless mode and per-page render wait for online scraping
- `host` / `port` — for the Flask web server
- `[web_providers]` — abbreviation-to-full-name mappings for streaming/purchase sources you track

## Usage

```bash
python main.py --createdb # create a new, empty database at the configured db_path (run once, before first sync)
python main.py --sync     # sync local media folder into the database
python main.py --update   # refresh IMDb offline datasets
python main.py --refresh  # refresh ratings, basic title data, each owned series' episode list, and known people
python main.py --stats    # show statistics about the collection
python main.py --help     # list all options
```

To browse the collection in a browser:

```bash
python server.py
```
