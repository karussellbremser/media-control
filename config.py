import configparser
import os
import sys

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(_BASE_DIR, "config.ini")

_config = configparser.ConfigParser()
if not _config.read(_CONFIG_PATH):
    sys.exit(
        "config.ini not found. Copy config.example.ini to config.ini "
        "and fill in your local paths."
    )

def _resolve(path):
    return path if os.path.isabs(path) else os.path.join(_BASE_DIR, path)

MEDIA_DIR = _config["paths"]["media_dir"]
DB_PATH = _resolve(_config["paths"]["db_path"])
COVERS_DIR = _resolve(_config["paths"]["covers_dir"])
COVERS_SMALL_DIR = _resolve(_config["paths"]["covers_small_dir"])
WEBDRIVER_PATH = _resolve(_config["paths"]["webdriver_path"])
IMDB_DATASETS_DIR = _config["paths"]["imdb_datasets_dir"]

SCRAPE_DELAY = _config.getint("scraping", "delay")
SCRAPE_MAX_COUNT = _config.getint("scraping", "max_count")

SERVER_HOST = _config["server"]["host"]
SERVER_PORT = _config.getint("server", "port")

WEB_PROVIDERS = dict(_config.items("web_providers"))
