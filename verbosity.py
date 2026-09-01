import config

# config.VERBOSITY's three levels -- named here for readability at call sites/comments, though the
# helpers below just compare against the raw int (see config.example.ini's [output] section)
LEVEL_QUIET = 0   # warnings and top-level status only (which step is currently running)
LEVEL_NORMAL = 1  # + everything else currently printed, except individual person additions
LEVEL_VERBOSE = 2 # + individual "new person added" lines -- today's full output, unchanged

def printAlways(msg):
    """Always printed, regardless of config.VERBOSITY: warnings and top-level status/step
    announcements (see LEVEL_QUIET)."""
    print(msg)

def printDetail(msg):
    """Printed once config.VERBOSITY >= LEVEL_NORMAL -- per-item scraping progress, genre/
    interest/language/franchise additions, removals, and similar detail. This is the bulk of
    today's output; only individual person additions (see printPerson) stay held back further."""
    if config.VERBOSITY >= LEVEL_NORMAL:
        print(msg)

def printPerson(msg):
    """Printed only once config.VERBOSITY >= LEVEL_VERBOSE -- individual "new person added"
    lines, split out on their own since a single sync can discover dozens of new people at once,
    making this by far the noisiest single category of output."""
    if config.VERBOSITY >= LEVEL_VERBOSE:
        print(msg)
