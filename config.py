# the web UI's own part of config.ini lives in serverconfig.py (so the docker image can do without the
# rest); re-exported here so everything else keeps reading it as config.DB_PATH etc.
from serverconfig import (parser as _config, resolve as _resolve,
                          DB_PATH, COVERS_DIR, COVERS_SMALL_DIR, HIDDEN_INTEREST_IDS_PATH,
                          SERVER_HOST, SERVER_PORT, CURTAIN_ANIMATION_ENABLED, CURTAIN_STYLE, SERVER_AUTH_FILE)

MEDIA_DIR = _resolve(_config["paths"]["media_dir"])
MEDIAINFO_PATH = _resolve(_config["paths"]["mediainfo_path"])
FFMPEG_PATH = _resolve(_config["paths"]["ffmpeg_path"])
CHROME_PROFILE_DIR = _resolve(_config["paths"]["chrome_profile_dir"])
IMDB_HELPER_DB_PATH = _resolve(_config["paths"]["imdb_helper_db_path"])
IGNORED_IDS_PATH = _resolve(_config["paths"]["ignored_ids_path"])
WONTADD_IDS_PATH = _resolve(_config["paths"]["wontadd_ids_path"])
# fallback=, not required: newer than config.example.ini's other [paths] keys, so an existing
# config.ini from before this was added still works unchanged, at this same default value
CUSTOM_CONNECTIONS_PATH = _resolve(_config.get("paths", "custom_connections_path", fallback="custom_connections.txt"))

LOCAL_SCAN_IGNORED_FILE_PATTERNS = [p.strip() for p in _config["local_scan"]["ignored_file_patterns"].split(",")]

SCRAPE_DELAY = _config.getint("scraping", "delay")
SCRAPE_MAX_COUNT = _config.getint("scraping", "max_count")
SCRAPE_RECOVER_MISSING_COVERS = _config.getboolean("scraping", "recover_missing_covers")
SCRAPE_HEADLESS = _config.getboolean("scraping", "headless")
SCRAPE_PAGE_LOAD_WAIT = _config.getint("scraping", "page_load_wait")
# fallback=, not required: newer than config.example.ini's other [scraping] keys, so an existing
# config.ini from before this was added still works unchanged, at these same default values, until
# the user opts to add them (see config.example.ini for what each one does)
SCRAPE_PAGE_LOAD_TIMEOUT = _config.getint("scraping", "page_load_timeout", fallback=60)
SCRAPE_NETWORK_RETRY_MAX_WAIT = _config.getint("scraping", "network_retry_max_wait", fallback=600)
SCRAPE_NETWORK_RETRY_DELAY = _config.getint("scraping", "network_retry_delay", fallback=30)

BACKUP_AUTO_ENABLED = _config.getboolean("backup", "auto_backup")
BACKUP_DIR = _resolve(_config["backup"]["backup_dir"])
BACKUP_FREQUENCY_DAYS = _config.getint("backup", "backup_frequency_days")
BACKUP_MAX_COUNT = _config.getint("backup", "backup_max_count")

HELPER_DB_AUTO_UPDATE_ENABLED = _config.getboolean("helper_db", "auto_update")
HELPER_DB_UPDATE_FREQUENCY_DAYS = _config.getint("helper_db", "update_frequency_days")
HELPER_DB_AUTO_REFRESH_ENABLED = _config.getboolean("helper_db", "auto_refresh")

MEDIA_AUTO_UPDATE_ENABLED = _config.getboolean("media_update", "auto_update_media")

CROPPING_BURST_FRAME_COUNT = _config.getint("cropping", "burst_frame_count")
CROPPING_RUNTIME_PERCENTAGES = [int(p) for p in _config["cropping"]["runtime_percentages"].split(",")]
CROPPING_CLUSTER_TOLERANCE = _config.getint("cropping", "cluster_tolerance")
CROPPING_SYMMETRY_TOLERANCE = _config.getint("cropping", "symmetry_tolerance")
CROPPING_MINIMUM_CLUSTER_SIZE = _config.getint("cropping", "minimum_cluster_size")
CROPPING_WINDOWBOXING_TOLERANCE = _config.getint("cropping", "windowboxing_tolerance")
CROPPING_MINIMUM_DEVIATION = _config.getint("cropping", "minimum_deviation")
CROPPING_CACHE_ENABLED = _config.getboolean("cropping", "cropping_cache_enabled", fallback=True)
CROPPING_CACHE_PATH = _resolve(_config.get("cropping", "cropping_cache_path", fallback="cropping_cache.json"))

VERBOSITY = _config.getint("output", "verbosity")

WEB_PROVIDERS = dict(_config.items("web_providers"))
