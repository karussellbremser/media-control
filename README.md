# media-control

Framework for storing and displaying a local collection of movies and TV series, and assisting playback.

Management functionality is similar to the ones of Plex or Kodi, but specifically tailored to the author's needs and with full control over the local (sqlite) database. Incorporates IMDb scraping for detailed information about individual movies and series.

## Features

- Scans a local media library and syncs it into a SQLite database. Movies live in one subdirectory each, named `Title_Year_ttIMDbID`; series use the same convention for the series folder, with episodes inside per-season subfolders (`S01`, `S02`, ...).
- Enriches entries with IMDb data: cover art and thumbnails, ratings, vote counts, genres, plot summaries, and connections to related titles (sequels, remakes, spin-offs, ...).
- Uses IMDb's downloadable offline datasets for bulk metadata (including each series' full episode catalog), and Selenium-based online scraping for covers and title connections.
- Flask web UI for browsing/searching/filtering the collection (by title, year, rating, votes, genre, movies vs. series).
- Basic statistics (yearly counts/ratings charts, franchise/connection clustering) via matplotlib.

## Requirements

- Python 3
- `pip install -r requirements.txt`
- A Selenium-compatible driver (e.g. [chromedriver](https://chromedriver.chromium.org/)) matching your installed browser
- IMDb's [offline dataset files](https://datasets.imdbws.com/) downloaded locally (`title.basics` / `title.ratings` / `title.episode`)

## Configuration

All local paths and settings live in `config.ini`, which is not tracked in git (it's specific to your machine). To set up:

```bash
cp config.example.ini config.ini
```

Then edit `config.ini` with your own paths:

- `media_dir` — root directory of your local media library
- `db_path`, `covers_dir`, `covers_small_dir` — where the database and cover images are stored (relative paths resolve against the project directory)
- `webdriver_path` — path to your chromedriver executable
- `imdb_datasets_dir` — directory containing the downloaded IMDb offline datasets
- `delay` / `max_count` — throttling for online IMDb scraping
- `host` / `port` — for the Flask web server

## Usage

```bash
python main.py --createdb # create a new, empty database at the configured db_path (run once, before first sync)
python main.py --sync     # sync local media folder into the database
python main.py --update   # refresh IMDb offline datasets
python main.py --refresh  # refresh ratings, basic title data, and each owned series' episode list
python main.py --stats    # show statistics about the collection
python main.py --help     # list all options
```

To browse the collection in a browser:

```bash
python server.py
```
