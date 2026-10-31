import json
import os

class CroppingCache:
    """A persistent, on-disk cache of ScrapeCropping's auto-detected (non-override) cropping
    results, keyed on (imdb_id, filename, mtime, detection parameters) -- all four must match for a
    cached result to be reused, so a changed file, a renamed file, or a changed [cropping] config
    setting all correctly miss rather than serve a stale answer. Exists because detectCropping is
    only ever called for a title going through the full remove-and-re-add cycle (see
    DBControl.determineMediaNeedingUpdate), which applies to every one of a medium's mediaVersions
    at once even when only one of them actually changed -- without this cache, an untouched sibling
    file would have its (CPU-expensive) cropping re-detected from scratch every single time.

    Lives entirely outside myMovieDB.db, as a single JSON file -- the access pattern here (loaded
    once per sync run, read/written/pruned many times in memory, saved once at the end) doesn't need
    SQLite's indexed-query machinery, and a plain file is easy to inspect or delete by hand. Lazily
    loaded on first use, same reasoning as ScrapeIMDbOffline's helper DB connection.

    Pruning is scoped to exactly the ids actually processed in a given run (see pruneUnused) -- a
    title removed from the library entirely (e.g. folder prefixed with "!" to temporarily hide it)
    simply leaves its entries untouched indefinitely, ready to be reused immediately if it's restored
    unchanged later, rather than being cleaned up proactively.

    pruneUnused keeps exactly the entries lookup confirmed as a hit or store just wrote THIS run --
    not merely "this filename still belongs to the medium". A file whose cropping.txt now covers it
    never calls either (detectCropping's override branch returns before touching the cache at all),
    so a stale entry left over from before it gained that override is correctly pruned even though
    the file itself didn't go anywhere -- the cache was simply never consulted for it this run."""

    def __init__(self, cache_path, burst_frame_count, runtime_percentages, cluster_tolerance,
                 symmetry_tolerance, minimum_cluster_size, windowboxing_tolerance, minimum_deviation):
        self.cache_path = cache_path
        # a single opaque fingerprint string for the whole parameter set, rather than storing each
        # parameter as its own field -- simpler to compare, and nothing ever needs to query by an
        # individual parameter's value
        self.__parametersFingerprint = "|".join(str(v) for v in (
            burst_frame_count,
            ",".join(str(p) for p in runtime_percentages),
            cluster_tolerance, symmetry_tolerance, minimum_cluster_size,
            windowboxing_tolerance, minimum_deviation,
        ))
        self.__data = None # {str(imdb_id): {filename: {"mtime": int, "params": str, "cropping": [t, b, l, r]}}}
        self.__dirty = False # avoids rewriting the file on a run that never actually changed anything
        self.__touched = set() # {(imdb_id, filename)} confirmed hit (lookup) or written (store) this run

    def __load(self):
        if self.__data is not None:
            return
        if os.path.isfile(self.cache_path):
            with open(self.cache_path, "r") as f:
                self.__data = json.load(f)
        else:
            self.__data = {}

    def lookup(self, imdb_id, filename, mtime):
        """Returns the cached [(top, bottom, left, right)] cropping result for this exact
        (imdb_id, filename, mtime, current detection parameters), or None if there's no entry or any
        of those four don't match. A hit marks (imdb_id, filename) as touched this run -- see
        pruneUnused."""
        self.__load()
        entry = self.__data.get(str(imdb_id), {}).get(filename)
        if entry is None or entry["mtime"] != mtime or entry["params"] != self.__parametersFingerprint:
            return None
        self.__touched.add((imdb_id, filename))
        return [tuple(entry["cropping"])]

    def store(self, imdb_id, filename, mtime, cropping):
        """Records a freshly auto-detected cropping result (cropping: a [(top, bottom, left, right)]
        single-element list, same shape ScrapeCropping.detectCropping sets on mediaVersion.cropping)
        under the current detection parameters, and marks (imdb_id, filename) as touched this run --
        see pruneUnused. Written immediately as each version succeeds, not deferred until its whole
        title finishes -- so one sibling version failing later doesn't discard an already-valid
        result for this one."""
        self.__load()
        self.__data.setdefault(str(imdb_id), {})[filename] = {
            "mtime": mtime,
            "params": self.__parametersFingerprint,
            "cropping": list(cropping[0]),
        }
        self.__touched.add((imdb_id, filename))
        self.__dirty = True

    def pruneUnused(self, imdb_id):
        """Removes every cached entry for imdb_id except ones lookup confirmed as a hit or store just
        wrote during this run (see __touched) -- not "every filename still in the medium", since a
        file now covered by a cropping.txt override never calls either one and must still have its
        stale entry (if any) removed. Only call this once imdb_id's mediaVersions for this run are
        fully known -- i.e. never for a title excluded mid-run by a sibling version's analysis
        failure, since __touched wouldn't reflect its true current state yet."""
        self.__load()
        key = str(imdb_id)
        if key not in self.__data:
            return
        filtered = {filename: entry for filename, entry in self.__data[key].items() if (imdb_id, filename) in self.__touched}
        if filtered == self.__data[key]:
            return # nothing actually pruned -- no need to mark dirty
        if filtered:
            self.__data[key] = filtered
        else:
            del self.__data[key]
        self.__dirty = True

    def save(self):
        """Writes the cache to disk if anything actually changed this run. Safe to call even if
        __load was never triggered (nothing to save yet)."""
        if not self.__dirty:
            return
        with open(self.cache_path, "w") as f:
            json.dump(self.__data, f)
        self.__dirty = False
