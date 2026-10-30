# media-control

Framework for storing and displaying a local collection of movies and TV series, and assisting playback.

Management functionality is similar to the ones of Plex or Kodi, but specifically tailored to the author's needs and with full control over the local (sqlite) database. Incorporates IMDb scraping for detailed information about individual movies and series.

## Features

- Scans a local media library and syncs it into a SQLite database. Movies live in one subdirectory each, named `Title_Year_ttIMDbID`; series use the same convention for the series folder, with episodes inside per-season subfolders (`S01`, `S02`, ...). Kaleidescape-owned titles (no local media file) are supported via empty `.kscape` placeholder files, usable interchangeably with real `.mkv` files.
- Enriches entries with IMDb data: cover art and thumbnails, ratings, vote counts, genres/subgenres (read from the title page's complete interest list, since IMDb's chip row is capped at 10 and cuts off the last subgenres and the genres), languages and countries of origin (in IMDb's order, the first language being the primary one), plot summaries, connections to related titles (sequels, remakes, spin-offs, alternate-language versions, ...), and director/writer/actor credits (including uncredited appearances) with each person's name, birth year and death year.
- Uses IMDb's downloadable offline datasets for bulk metadata (including each series' full episode catalog and per-person details), and SeleniumBase-based online scraping for covers, subgenres, languages/countries, title connections, and full cast/crew credits (scraped per-episode as well as per-movie/series, since a series' director/writer/cast can vary by episode). Movie covers are only auto-downloaded for titles whose primary (first-listed) language is English; series, movies with any other primary language, and movies with no language listed must have their covers added manually.
- Runs [MediaInfo](https://mediaarea.net/en/MediaInfo) against each newly-added local file to record detailed video/audio/subtitle track information (codec, resolution, HDR metadata, bitrate, languages, ...).
- Auto-detects each file's actual black-bar cropping/aspect ratio via `ffmpeg`'s `cropdetect`, sampled across the runtime and reduced to one confident answer -- or left for manual review (a `cropping.txt` override file alongside the media, also usable for content with genuinely variable aspect ratio, e.g. IMAX-expansion scenes) when the detected data doesn't actually support a single confident result.
- Optional, opt-in auto-update: detects a locally-owned file that's been replaced (e.g. with a new remux/remaster, via a newer file mtime) and re-scrapes it from scratch.
- Automatic, rotating DB backups before a sync/refresh, plus an on-demand backup command.
- Flask web UI for browsing/searching/filtering the collection (by title, year, rating, votes, genre/subgenre, primary language, movies vs. series; a genre/subgenre can also be excluded -- right-click, or long-press on touch, turns it into a red "NOT" filter, and a left click flips it straight to "YES") and sorting (title, year, rating, votes, last-modified, random), including per-series episode ownership.
- Basic statistics (yearly counts/ratings charts, franchise/connection clustering) via matplotlib.
- Languages and countries of origin are stored against canonical ISO 639-3/ISO 3166 reference tables rather than raw, differently-shaped codes from each source, so IMDb-parsed and MediaInfo-parsed language data are directly comparable.
- Custom connections: a `custom_connections.txt` file lets you declare relationships between titles that IMDb itself doesn't list (e.g. `tt_id follows tt_id`, `tt_id spin_off_from tt_id`, chains and groups for ordered/undirected relationships) -- reconciled against the database at the end of every sync, without ever overriding or conflicting with IMDb-sourced connections.
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
- `ignored_ids_path` / `wontadd_ids_path` — text files of IMDb ids (one per line, `#` comments supported): ignored ids must never appear in the DB at all; wontadd ids are fine to have (and, for a series, to partially own) but aren't worth actively adding locally
- `hidden_interest_ids_path` — text file of subgenre interest ids to keep out of the web UI's filter list
- `custom_connections_path` — text file declaring connections between titles that IMDb doesn't list itself (one relationship per line, `#` comments supported); optional, defaults to `custom_connections.txt` if not set -- see the Features list above and the file's own format comments in `config.example.ini`

**`[local_scan]`**
- `ignored_file_patterns` — comma-separated glob patterns (`*`, `?`) for filenames that may sit alongside real media files but should be silently ignored during the local scan (e.g. `*.nfo`)

**`[scraping]`**
- `delay` / `max_count` — throttling for online IMDb scraping (`max_count` counts a series and all its episodes as a single title). `max_count` is just the default; `--max-count N` on the command line overrides it for that one run (e.g. a lower number for a quick daily sync)
- `recover_missing_covers` — whether `--sync` also backfills missing covers (e.g. a deleted file) for every already-owned movie with an English primary language at the end of each run, not just titles newly added that run (its own `max_count`-sized allowance, on top of whatever the rest of the run already spent). Only titles already written to the database are considered, so it finds little to do on a first sync
- `headless` / `page_load_wait` — Chrome headless mode and per-page render wait for online scraping
- `page_load_timeout` — how long a single page-navigation attempt may take before it's treated as failed and retried (see `network_retry_max_wait`/`network_retry_delay`)
- `network_retry_max_wait` / `network_retry_delay` — how a connectivity failure (dropped/refused/reset connection, DNS briefly failing, a stalled request) during online scraping or a file download is retried: keep retrying for up to `network_retry_max_wait` seconds in total, waiting `network_retry_delay` seconds between attempts. Only genuine connectivity failures are retried this way — an IMDb block, a human-verification page, or an unexpected page structure are not, since retrying those wouldn't help

**`[backup]`** — automatic DB backups before `-s`/`-r` (see `-b`/`--backup` below for an on-demand one)
- `auto_backup` — whether they happen automatically at all
- `backup_dir`, `backup_frequency_days`, `backup_max_count` — where backups go, how old the newest one must be before another is made automatically, and how many to keep

**`[helper_db]`** — automatic upkeep of the IMDb offline-dataset helper DB
- `auto_update`, `update_frequency_days` — whether `-s`/`-r` rebuild it automatically once missing/stale, and how old counts as stale
- `auto_refresh` — whether an update (automatic or manual `-u`) is immediately followed by a full `-r`-equivalent refresh of all known media

**`[media_update]`**
- `auto_update_media` — `-s` always detects and re-scrapes a locally-owned medium whose set of version files changed (a rename, an added version, or one version removed while another survives); this setting additionally opts into detecting an unchanged filename whose content was replaced in place (via a newer mtime than what's stored), which is a heuristic rather than a guarantee

**`[cropping]`** — tuning for the black-bar/aspect-ratio auto-detection
- `burst_frame_count`, `runtime_percentages` — how the video is sampled
- `cluster_tolerance`, `symmetry_tolerance`, `minimum_cluster_size`, `windowboxing_tolerance`, `minimum_deviation` — thresholds controlling when a detected result is trusted versus left for manual review via a `cropping.txt` override
- `cropping_cache_enabled`, `cropping_cache_path` — a JSON cache (outside the main database) of auto-detected results keyed on imdb_id/filename/mtime/these detection parameters, so an unchanged file's expensive ffmpeg analysis isn't repeated just because a sibling version of the same title changed

**`[output]`**
- `verbosity` — 0 (warnings/status only), 1 (+ everything else), or 2 (+ individual "new person added" lines)

**`[server]`**
- `host` / `port` — for the Flask web server
- `curtain_animation` — whether a theater-curtain-opening animation plays on page load (real loads only, never on an in-place filter/search/sort update)
- `curtain_style` — `classic` (red velvet, gold scalloped valance) or `reserved` (warm greige, echoing the page's own light-gray palette)
- `auth_file` — optional: a one-line `username:password-hash` file; when set, the whole web UI asks for that login (see "Hosting the web UI with Docker")

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

python main.py --sync --max-count 5  # override config.ini's [scraping] max_count for this run only
```

To browse the collection in a browser:

```bash
python server.py
```

## Hosting the web UI with Docker

Only the web UI (`server.py`) is meant to be hosted; scanning, scraping, MediaInfo and ffmpeg stay on the machine that owns the media library. The `Dockerfile` builds an image holding the code only (served by gunicorn, which takes host and port from the `[server]` section of `docker/config.docker.ini`, the image's `config.ini` -- only a dozen lines, since the web UI reads just the data paths and `[server]`, see `serverconfig.py`); the database, covers and `hidden_interests.txt` live in a `data/` directory next to `compose.yaml` that is mounted read-only at `/data`, so updating them never needs a rebuild. `compose.yaml` publishes the app on the host port set as `HOST_PORT` in a `.env` file next to it (required, there is no default -- see `.env.example`) for a reverse proxy to forward to (it does the HTTPS), and is written for rootless Docker. If you ever change the `[server]` port in `docker/config.docker.ini`, change the container side of the port mapping in `compose.yaml` to match.

**Login.** The whole site (pages, API and covers) is protected by HTTP basic auth whenever `config.ini`'s `[server]` `auth_file` names a credentials file -- the image's config always sets it, and the server refuses to start if the file is missing or malformed, so it can't be exposed unprotected by accident. Your local `config.ini` has no such key, so `python server.py` needs no login. Create the file (one line, `username:password-hash`) with the command below, which writes the file from Python itself -- not with a shell redirect (`> auth.txt`), which in Windows PowerShell produces a UTF-16 file:

```bash
python -c "import getpass; from werkzeug.security import generate_password_hash as g; open('auth.txt','w',encoding='utf-8').write('yourname:' + g(getpass.getpass('password: ')) + '\n')"
```

**First deployment** (on the server, then from the machine that owns the library; `user@server` is your login):

```bash
git clone https://github.com/karussellbremser/media-control.git && cd media-control && mkdir data   # on the server
cp .env.example .env                                                                                  # on the server, then set HOST_PORT in it

scp auth.txt user@server:media-control/auth.txt
scp myMovieDB.db hidden_interests.txt user@server:media-control/data/
scp -r covers covers_small user@server:media-control/data/

docker compose up -d --build                                                                         # on the server
```

Files must stay world-readable (the default for `scp`), since rootless Docker maps the container's user to a different host user than yours.

**Updating: `deploy.py`.** After the first deployment, updates are done from the machine that owns the library with `deploy.py`, which needs a `deploy.ini` (copy `deploy.example.ini`: server, user, project directory; not tracked by git) and the `paramiko` library (`pip install paramiko`). The whole run -- every command and transfer -- goes through **one** ssh connection, so a server that limits new logins sees a single one. It logs in with your ssh key and only trusts hosts already in your `~/.ssh/known_hosts`, so connect to the server once with the `ssh` command first.

```bash
python deploy.py status                 # what runs on the server vs. what you have locally
python deploy.py content                # new/changed covers and the current database
python deploy.py code                   # the server code, as pushed to GitHub
python deploy.py full                   # both, switched over together (code that needs a changed database format, e.g. a new column)
python deploy.py rollback [--db]        # back to the previous version (and, with --db, the previous database)
```

Every command takes `--dry-run` (prints what it would change on the server, changes nothing) and `-y` (no confirmation prompt); `content` and `full` take `--prune` (also delete covers that exist on the server only, which are otherwise just reported) and `--skip-covers`, `content` also `--skip-db`. What it does and checks:

- The database is never copied live: a consistent snapshot is taken with SQLite's backup function, checked with `integrity_check`, and that snapshot is uploaded -- as `myMovieDB.db.new`, verified by SHA-256, then renamed over the live file (atomic). The previous database stays as `myMovieDB.db.prev`.
- Before anything reaches the server, the server code of your working tree is run against that snapshot (pages, search with filters and every sort order, detail views), so code and database that don't fit together are caught on your machine.
- `code` and `full` deploy what is on GitHub (the server pulls it): uncommitted changes to tracked files, or commits that aren't pushed, are refused (`--skip-git-check` overrides that).
- Covers: the server's own file list is compared with yours; only new or changed files are sent, in one tar stream (made on the fly, no tar program needed).
- `full` builds the new image while the old container keeps serving, and only then switches database and container over, so the downtime is just the restart (a few seconds). `code` does the same without the database.
- After a restart or a database swap, the result is verified from inside the container: it answers on its port, its own user can read the database (the row count must match what was uploaded) and the covers. If not, the previous code and database are restored automatically.
- The port the app answers on is asked of docker compose, so `.env` on the server stays the only place `HOST_PORT` is set. A `code` or `full` deploy to a server whose `.env` doesn't have it yet (from before `compose.yaml` required it) shows that in its plan and writes the port the running container publishes.
- Permissions on `data/` are fixed after every upload (rootless Docker needs the files and folders world-readable), and `hidden_interests.txt` is uploaded and the container restarted when it changed. `auth.txt` is only read at server start: after changing it, run `docker compose restart` on the server.

`docker/config.docker.ini` is the image's own config and is separate from your local `config.ini`; it only has to carry what `serverconfig.py` reads, so options for scanning, scraping and the like never need adding there.
