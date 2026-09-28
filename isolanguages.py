"""Loads the ISO 639-3 code tables and seeds iso_language_enum from them. Shared between
DBControl.createMediaDB (a fresh DB) and tools/migrate_language_codes_to_iso639_3.py (an existing
one), so both stay based on the exact same data and logic.

The two tab-delimited source files (see _ensureLocalDataFiles) are downloaded on demand from
iso639-3.sil.org, the standard's maintenance agency, into a local iso639-3/ cache -- deliberately
NOT checked into version control (see .git/info/exclude). Per SIL's published Terms of Use,
attribution to iso639-3.sil.org is given here, the codes are used unmodified, and "the product,
system, or device does not provide a means to redistribute the code set" -- since this repo is
public, committing the raw files would itself be exactly that redistribution channel, so they're
fetched fresh per machine instead (same reasoning as imdb_offline.db never being committed either,
just for a different, license-driven reason rather than sheer size).
"""
import csv
import os
import requests

_BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "iso639-3")
_CODE_SET_FILENAME = "iso-639-3.tab"
_MACROLANGUAGES_FILENAME = "iso-639-3-macrolanguages.tab"
_DOWNLOAD_BASE_URL = "https://iso639-3.sil.org/sites/iso639-3/files/downloads/"


def _ensureLocalDataFiles():
    """Downloads both source files into _BASE_DIR if either is missing -- always both together, so
    a stale leftover from a much earlier run can never end up paired with a freshly-fetched one.
    No retry of its own, unlike ScrapeIMDbOnline's network handling: this only ever runs once, the
    first time a DB is created on a given machine (the whole point of iso_language_enum is that
    it's fixed thereafter), so a transient failure here just means re-running createMediaDB."""
    codeSetPath = os.path.join(_BASE_DIR, _CODE_SET_FILENAME)
    macroPath = os.path.join(_BASE_DIR, _MACROLANGUAGES_FILENAME)
    if os.path.isfile(codeSetPath) and os.path.isfile(macroPath):
        return
    os.makedirs(_BASE_DIR, exist_ok=True)
    for filename in (_CODE_SET_FILENAME, _MACROLANGUAGES_FILENAME):
        response = requests.get(_DOWNLOAD_BASE_URL + filename, timeout=(10, 30))
        response.raise_for_status()
        with open(os.path.join(_BASE_DIR, filename), "wb") as f:
            f.write(response.content)

# A handful of codes IMDb itself uses that aren't resolvable against the standard's own tables --
# either one of IMDb's private-use codes (ISO reserves qaa-qtz for exactly this, so these can never
# collide with a real future assignment), or a genuine ISO 639-2 collective/family code that 639-3
# deliberately excludes from its individual-language table. Deliberately kept out of
# iso_language_enum itself (which stays a clean, unmodified mirror of the standard) and applied only
# here, in the lookup every caller already resolves through -- see DBControl.getIsoLanguageLookup.
# Not a data problem to "fix": some of these are inherently approximate (flagged below), a best
# real-world choice rather than a fact from the standard.
NON_STANDARD_ALIASES = {
    "qad": "wuu",  # IMDb's "Shanghainese" -> Wu Chinese; no finer individual code exists
    "qbn": "nld",  # IMDb's "Flemish" -> Dutch; the standard makes no distinction at all
    "qbo": "hbs",  # IMDb's "Serbo-Croatian" -> ISO's own code for the same concept; IMDb just never adopted it
    "qae": "sme",  # IMDb's "Saami" -> Northern Sami, the most-spoken Sami language: APPROXIMATE, not exact --
                   # the standard has no generic "Saami" individual code, only specific ones
    "tup": "tpn",  # IMDb's "Tupi" -> Tupinambá: APPROXIMATE, not exact -- "tup" is a ~70-language family in
                   # ISO 639-2/5, not one language; Tupinambá is the historically dominant one fiction usually means
}


def seedIsoLanguageEnum(cursor):
    """Populates an already-created, empty iso_language_enum table. Idempotent only in the sense
    that re-running it against a non-empty table raises (UNIQUE/PRIMARY KEY violation) rather than
    silently duplicating or overwriting -- callers run this exactly once per table, same as
    DBControl.createMediaDB's other pre-seeded enums."""
    _ensureLocalDataFiles()
    with open(os.path.join(_BASE_DIR, _CODE_SET_FILENAME), encoding="utf-8") as f:
        codeRows = list(csv.DictReader(f, delimiter="\t"))
    with open(os.path.join(_BASE_DIR, _MACROLANGUAGES_FILENAME), encoding="utf-8") as f:
        macroRows = list(csv.DictReader(f, delimiter="\t"))

    # only active (non-deprecated) individual-member rows -- a deprecated I_Id has no row of its
    # own in codeRows to attach a macrolanguage to
    macrolanguageByMember = {row["I_Id"]: row["M_Id"] for row in macroRows if row["I_Status"] == "A"}

    for row in codeRows:
        cursor.execute(
            "INSERT INTO iso_language_enum (iso639_3, iso639_1, iso639_2b, iso639_2t, name) VALUES (?, ?, ?, ?, ?)",
            (row["Id"], row["Part1"] or None, row["Part2b"] or None, row["Part2t"] or None, row["Ref_Name"]),
        )
    # a second pass -- rather than setting macrolanguage inline above -- since a member can be
    # listed before its macrolanguage's own row exists yet, and the FK is checked immediately
    for member_id, macro_id in macrolanguageByMember.items():
        cursor.execute("UPDATE iso_language_enum SET macrolanguage = ? WHERE iso639_3 = ?", (macro_id, member_id))


def buildLookup(cursor):
    """{raw_code: canonical iso639_3 code} covering every ISO 639-1, 639-2 (bibliographic and
    terminologic), and 639-3 code in iso_language_enum, plus NON_STANDARD_ALIASES -- for resolving
    a language code from either IMDb's or MediaInfo's own code conventions to one canonical key.
    See DBControl.getIsoLanguageLookup."""
    cursor.execute("SELECT iso639_3, iso639_1, iso639_2b, iso639_2t FROM iso_language_enum")
    lookup = {}
    for iso639_3, iso639_1, iso639_2b, iso639_2t in cursor.fetchall():
        lookup[iso639_3] = iso639_3
        if iso639_1:
            lookup[iso639_1] = iso639_3
        if iso639_2b:
            lookup[iso639_2b] = iso639_3
        if iso639_2t:
            lookup[iso639_2t] = iso639_3
    lookup.update(NON_STANDARD_ALIASES)
    return lookup
