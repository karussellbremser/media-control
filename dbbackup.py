import os
import re
import shutil
from datetime import datetime, timedelta
from verbosity import printAlways

class DBBackup:
    """Creates and prunes timestamped copies of the main DB file in a dedicated backup directory.
    A plain shutil.copy2 is enough here (rather than e.g. SQLite's VACUUM INTO) -- this project
    never enables WAL mode, and every backup call happens before the sync/refresh pipeline that's
    about to run opens its own connection, so there's never a concurrent writer to race against
    (the only other thing that ever touches the DB, server.py, is read-only)."""

    # ties a backup's filename to the DB's own basename, so multiple DBs (or a renamed db_path)
    # never collide, and so pruning only ever considers files this exact code created -- never a
    # wildcard/glob delete, never anything else a user might keep in the same directory. The
    # trailing (_N)? disambiguator handles two backups landing in the same second (e.g. -s
    # immediately followed by an explicit -b) -- without it the second would silently overwrite
    # the first instead of becoming its own backup, see _createBackup
    _TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"

    def __init__(self, db_path, backup_dir, max_count):
        self.db_path = db_path
        self.backup_dir = backup_dir
        self.max_count = max_count
        self.db_basename = os.path.splitext(os.path.basename(db_path))[0]
        self._pattern = re.compile(r"^" + re.escape(self.db_basename) + r"_(\d{8}_\d{6})(?:_\d+)?\.db$")

    def ensureBackup(self, frequency_days):
        """Creates a new backup if the newest existing one is older than frequency_days (or none
        exist yet), then prunes down to max_count. Never raises -- any failure (permission error,
        disk full, backup_dir unreachable, ...) is printed as a warning and swallowed instead, since
        a missed backup shouldn't block the sync/refresh it was meant to protect. No-op if db_path
        doesn't exist yet (e.g. before the first -c)."""
        try:
            if not os.path.isfile(self.db_path):
                return
            backups = self._listBackups()
            if backups and datetime.now() - backups[-1][0] < timedelta(days=frequency_days):
                return
            self._createBackup()
            self._prune()
        except Exception as e:
            printAlways("WARNING: DB backup failed: " + str(e))

    def forceBackup(self):
        """Creates a new backup unconditionally (ignoring frequency_days), then prunes down to
        max_count -- for an explicit, on-demand backup (-b/--backup). Unlike ensureBackup, this lets
        any failure propagate: an explicit request to back up the DB should say so loudly if it
        didn't actually happen, not fail silently."""
        if not os.path.isfile(self.db_path):
            raise FileNotFoundError("DB not found at " + self.db_path + " -- nothing to back up")
        self._createBackup()
        self._prune()

    def _listBackups(self):
        """Returns [(timestamp, path), ...] for every file in backup_dir matching this DB's backup
        naming pattern, oldest first. Timestamp is parsed from the filename itself, not the file's
        mtime, so a copy/touch that changes mtime can't disturb the ordering."""
        if not os.path.isdir(self.backup_dir):
            return []
        matches = []
        for name in os.listdir(self.backup_dir):
            m = self._pattern.fullmatch(name)
            if m:
                timestamp = datetime.strptime(m.group(1), self._TIMESTAMP_FORMAT)
                matches.append((timestamp, os.path.join(self.backup_dir, name)))
        matches.sort(key=lambda pair: pair[0])
        return matches

    def _createBackup(self):
        os.makedirs(self.backup_dir, exist_ok=True)
        stem = self.db_basename + "_" + datetime.now().strftime(self._TIMESTAMP_FORMAT)
        backup_path = os.path.join(self.backup_dir, stem + ".db")
        # disambiguate a same-second collision -- see _TIMESTAMP_FORMAT's comment
        suffix = 1
        while os.path.exists(backup_path):
            backup_path = os.path.join(self.backup_dir, stem + "_" + str(suffix) + ".db")
            suffix += 1
        shutil.copy2(self.db_path, backup_path)
        printAlways("Created DB backup: " + backup_path)

    def _prune(self):
        backups = self._listBackups()
        while len(backups) > self.max_count:
            _, oldest_path = backups.pop(0)
            os.remove(oldest_path)
            printAlways("Removed old DB backup: " + oldest_path)
