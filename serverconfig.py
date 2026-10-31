"""The part of config.ini the web UI (web/server.py, web/gunicorn.conf.py) needs: the data paths it reads and
the [server] section. Kept apart from config.py, which parses everything else (scraping, cropping,
backups, ...) and re-exports these values, so the docker image can run the server with a config file of
a dozen lines instead of a copy of the whole thing -- see deploy/config.docker.ini. Every other
module keeps using config.DB_PATH etc. as before."""
import configparser
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(BASE_DIR, "config.ini")

parser = configparser.ConfigParser()
parser.optionxform = str  # preserve option name case (e.g. web_providers abbreviations like "iT"/"IMDb")
if not parser.read(_CONFIG_PATH):
    sys.exit(
        "config.ini not found. Copy config.example.ini to config.ini "
        "and fill in your local paths."
    )

def resolve(path):
    """path as given if absolute, else relative to this project's directory."""
    return path if os.path.isabs(path) else os.path.join(BASE_DIR, path)

DB_PATH = resolve(parser["paths"]["db_path"])
COVERS_DIR = resolve(parser["paths"]["covers_dir"])
COVERS_SMALL_DIR = resolve(parser["paths"]["covers_small_dir"])
HIDDEN_INTEREST_IDS_PATH = resolve(parser["paths"]["hidden_interest_ids_path"])

SERVER_HOST = parser["server"]["host"]
SERVER_PORT = parser.getint("server", "port")
CURTAIN_ANIMATION_ENABLED = parser.getboolean("server", "curtain_animation")
CURTAIN_STYLE = parser["server"]["curtain_style"]
if CURTAIN_STYLE not in ("classic", "reserved"):
    sys.exit("config.ini: [server] curtain_style must be 'classic' or 'reserved', got '" + CURTAIN_STYLE + "'")
# optional: protects the whole web UI with HTTP basic auth when set (see web/server.py's requireLogin)
_authFile = parser.get("server", "auth_file", fallback="").strip()
SERVER_AUTH_FILE = resolve(_authFile) if _authFile else None
