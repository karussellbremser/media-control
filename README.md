# media-control

Framework for storing and displaying a local collection of movies and assisting playback.

Management functionality is similar to the ones of Plex or Kodi, but specifically tailored to the author's needs and with full control over the local (sqlite) database. Incorporates IMDb scraping for detailed information about individual movies and series.

## Features

- Scans a local media library (one subdirectory per movie, named `Title_Year_ttIMDbID`) and syncs it into a SQLite database.
- Enriches entries with IMDb data: cover art and thumbnails, ratings, vote counts, genres, and connections to related titles (sequels, remakes, spin-offs, ...).
- Uses IMDb's downloadable offline datasets for bulk metadata, and Selenium-based online scraping for covers and title connections.
- Flask web UI for browsing/searching/filtering the collection (by title, year, rating, votes, genre).
- Basic statistics (yearly counts/ratings charts, franchise/connection clustering) via matplotlib.

Series scraping is not yet implemented; only movies are currently handled.

## Requirements

- Python 3
- `pip install -r requirements.txt`
- A Selenium-compatible driver (e.g. [chromedriver](https://chromedriver.chromium.org/)) matching your installed browser
- IMDb's [offline dataset files](https://datasets.imdbws.com/) downloaded locally (for `title.basics` / `title.ratings`)

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
python main.py --refresh  # refresh ratings for all entries
python main.py --stats    # show statistics about the collection
python main.py --help     # list all options
```

To browse the collection in a browser:

```bash
python server.py
```
