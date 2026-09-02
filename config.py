import configparser
import os
import sys

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(_BASE_DIR, "config.ini")

_config = configparser.ConfigParser()
_config.optionxform = str  # preserve option name case (e.g. web_providers abbreviations like "iT"/"IMDb")
if not _config.read(_CONFIG_PATH):
    sys.exit(
        "config.ini not found. Copy config.example.ini to config.ini "
        "and fill in your local paths."
    )

def _resolve(path):
    return path if os.path.isabs(path) else os.path.join(_BASE_DIR, path)

MEDIA_DIR = _resolve(_config["paths"]["media_dir"])
DB_PATH = _resolve(_config["paths"]["db_path"])
COVERS_DIR = _resolve(_config["paths"]["covers_dir"])
COVERS_SMALL_DIR = _resolve(_config["paths"]["covers_small_dir"])
MEDIAINFO_PATH = _resolve(_config["paths"]["mediainfo_path"])
FFMPEG_PATH = _resolve(_config["paths"]["ffmpeg_path"])
CHROME_PROFILE_DIR = _resolve(_config["paths"]["chrome_profile_dir"])
IMDB_HELPER_DB_PATH = _resolve(_config["paths"]["imdb_helper_db_path"])
IGNORED_IDS_PATH = _resolve(_config["paths"]["ignored_ids_path"])
WONTADD_IDS_PATH = _resolve(_config["paths"]["wontadd_ids_path"])
HIDDEN_INTEREST_IDS_PATH = _resolve(_config["paths"]["hidden_interest_ids_path"])

SCRAPE_DELAY = _config.getint("scraping", "delay")
SCRAPE_MAX_COUNT = _config.getint("scraping", "max_count")
SCRAPE_HEADLESS = _config.getboolean("scraping", "headless")
SCRAPE_PAGE_LOAD_WAIT = _config.getint("scraping", "page_load_wait")

BACKUP_AUTO_ENABLED = _config.getboolean("backup", "auto_backup")
BACKUP_DIR = _resolve(_config["backup"]["backup_dir"])
BACKUP_FREQUENCY_DAYS = _config.getint("backup", "backup_frequency_days")
BACKUP_MAX_COUNT = _config.getint("backup", "backup_max_count")

HELPER_DB_AUTO_UPDATE_ENABLED = _config.getboolean("helper_db", "auto_update")
HELPER_DB_UPDATE_FREQUENCY_DAYS = _config.getint("helper_db", "update_frequency_days")
HELPER_DB_AUTO_REFRESH_ENABLED = _config.getboolean("helper_db", "auto_refresh")

MEDIA_AUTO_UPDATE_ENABLED = _config.getboolean("media_update", "auto_update_media")

VERBOSITY = _config.getint("output", "verbosity")

SERVER_HOST = _config["server"]["host"]
SERVER_PORT = _config.getint("server", "port")

WEB_PROVIDERS = dict(_config.items("web_providers"))
