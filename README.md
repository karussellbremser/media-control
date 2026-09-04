# media-control

Framework for storing and displaying a local collection of movies and TV series, and assisting playback.

Management functionality is similar to the ones of Plex or Kodi, but specifically tailored to the author's needs and with full control over the local (sqlite) database. Incorporates IMDb scraping for detailed information about individual movies and series.

## Features

- Scans a local media library and syncs it into a SQLite database. Movies live in one subdirectory each, named `Title_Year_ttIMDbID`; series use the same convention for the series folder, with episodes inside per-season subfolders (`S01`, `S02`, ...). Kaleidescape-owned titles (no local media file) are supported via empty `.kscape` placeholder files, usable interchangeably with real `.mkv` files.
- Enriches entries with IMDb data: cover art and thumbnails, ratings, vote counts, genres/subgenres, language, plot summaries, connections to related titles (sequels, remakes, spin-offs, alternate-language versions, ...), and director/writer/actor credits (including uncredited appearances) with each person's name, birth year and death year.
- Uses IMDb's downloadable offline datasets for bulk metadata (including each series' full episode catalog and per-person details), and SeleniumBase-based online scraping for covers, subgenres/language, title connections, and full cast/crew credits (scraped per-episode as well as per-movie/series, since a series' director/writer/cast can vary by episode). Movie covers are only auto-downloaded for English-language titles; series and non-English movie covers must be added manually.
- Runs [MediaInfo](https://mediaarea.net/en/MediaInfo) against each newly-added local file to record detailed video/audio/subtitle track information (codec, resolution, HDR metadata, bitrate, languages, ...).
- Auto-detects each file's actual black-bar cropping/aspect ratio via `ffmpeg`'s `cropdetect`, sampled across the runtime and reduced to one confident answer -- or left for manual review (a `cropping.txt` override file alongside the media, also usable for content with genuinely variable aspect ratio, e.g. IMAX-expansion scenes) when the detected data doesn't actually support a single confident result.
- Optional, opt-in auto-update: detects a locally-owned file that's been replaced (e.g. with a new remux/remaster, via a newer file mtime) and re-scrapes it from scratch.
- Automatic, rotating DB backups before a sync/refresh, plus an on-demand backup command.
- Flask web UI for browsing/searching/filtering the collection (by title, year, rating, votes, genre/subgenre, movies vs. series), including per-series episode ownership.
- Basic statistics (yearly counts/ratings charts, franchise/connection clustering) via matplotlib.
- Three-tier console verbosity, configurable per run.

## Requirements

- Python 3
- `pip install -r requirements.txt`
- The [MediaInfo CLI](https://mediaarea.net/en/MediaInfo/Download) executable, for analyzing locally-owned media files
- An [ffmpeg](https://ffmpeg.org/download.html) executable, for black-bar/aspect-ratio detection
- No separate browser driver to install -- SeleniumBase manages its own chromedriver automatically
- No separate download needed for IMDb's [offline datasets](https://datasets.imdbws.com/) — `python main.py --update` fetches and indexes them into a local helper DB itself

## Configuration

All local paths and settings live in `config.ini`, which is not tracked in git (it's specific to your machine). To set up:

```bash
cp config.example.ini config.ini
```

Then edit `config.ini` with your own paths and settings -- see `config.example.ini` itself for the full, authoritative set of comments; summarized by section below:

**`[paths]`**
- `media_dir` — root directory of your local media library
- `db_path`, `covers_dir`, `covers_small_dir` — where the database and cover images are stored (relative paths resolve against the project directory)
- `mediainfo_path` — path to the MediaInfo CLI executable
- `ffmpeg_path` — path to the ffmpeg executable
- `chrome_profile_dir` — persistent Chrome profile (cookies/session state), reused across runs
- `imdb_helper_db_path` — where the indexed IMDb offline-dataset helper DB is stored (built by `--update`)
- `ignored_ids_path` / `wontadd_ids_path` — text files of IMDb ids (one per line): ignored ids must never appear in the DB at all; wontadd ids are fine to have (and, for a series, to partially own) but aren't worth actively adding locally
- `hidden_interest_ids_path` — text file of subgenre interest ids to keep out of the web UI's filter list

**`[scraping]`**
- `delay` / `max_count` — throttling for online IMDb scraping (`max_count` counts a series and all its episodes as a single title)
- `headless` / `page_load_wait` — Chrome headless mode and per-page render wait for online scraping

**`[backup]`** — automatic DB backups before `-s`/`-r` (see `-b`/`--backup` below for an on-demand one)
- `auto_backup` — whether they happen automatically at all
- `backup_dir`, `backup_frequency_days`, `backup_max_count` — where backups go, how old the newest one must be before another is made automatically, and how many to keep

**`[helper_db]`** — automatic upkeep of the IMDb offline-dataset helper DB
- `auto_update`, `update_frequency_days` — whether `-s`/`-r` rebuild it automatically once missing/stale, and how old counts as stale
- `auto_refresh` — whether an update (automatic or manual `-u`) is immediately followed by a full `-r`-equivalent refresh of all known media

**`[media_update]`**
- `auto_update_media` — opt-in detection of locally-owned files that changed (newer mtime than what's stored), automatically re-scraping them from scratch on `-s`

**`[cropping]`** — tuning for the black-bar/aspect-ratio auto-detection
- `burst_frame_count`, `runtime_percentages` — how the video is sampled
- `cluster_tolerance`, `symmetry_tolerance`, `minimum_cluster_size`, `windowboxing_tolerance`, `minimum_deviation` — thresholds controlling when a detected result is trusted versus left for manual review via a `cropping.txt` override

**`[output]`**
- `verbosity` — 0 (warnings/status only), 1 (+ everything else), or 2 (+ individual "new person added" lines)

**`[server]`**
- `host` / `port` — for the Flask web server
- `curtain_animation` — whether a theater-curtain-opening animation plays on page load (real loads only, never on an in-place filter/search/sort update)

**`[web_providers]`**
- abbreviation-to-full-name mappings for streaming/purchase sources you track

## Usage

```bash
python main.py --createdb # create a new, empty database at the configured db_path (run once, before first sync)
python main.py --sync     # sync local media folder into the database
python main.py --update   # refresh IMDb offline datasets
python main.py --refresh  # refresh ratings, basic title data, each owned series' episode list, and known people
python main.py --stats    # show statistics about the collection
python main.py --backup   # immediately create a DB backup, regardless of how recent the last one is
python main.py --help     # list all options
```

To browse the collection in a browser:

```bash
python server.py
```
