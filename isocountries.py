"""Loads the ISO 3166-1 (current) and ISO 3166-3 (formerly used) country code tables and seeds
iso_country_enum from them. Shared between DBControl.createMediaDB (a fresh DB) and
tools/migrate_country_codes_to_iso3166.py (an existing one), so both stay based on the exact same
data and logic. Mirrors isolanguages.py -- see that module for the fuller design rationale.

The two JSON source files are downloaded on demand (see _ensureLocalDataFiles) from pycountry's
GitHub repo, which mirrors Debian's iso-codes project verbatim -- LGPL-2.1 licensed (unlike ISO
639-3's SIL terms, LGPL explicitly permits redistribution, so checking these in wouldn't actually
be a licensing problem; they're still fetched on demand into a local, gitignored cache purely for
consistency with isolanguages.py's pattern, not because it's legally required here). There's no
single official free download page for ISO 3166 the way SIL runs one for ISO 639-3, so this uses
the same data the wider Python ecosystem (pycountry) already relies on.
"""
import json
import os
import requests

_BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "iso3166")
_CURRENT_FILENAME = "iso3166-1.json"
_FORMER_FILENAME = "iso3166-3.json"
_DOWNLOAD_BASE_URL = "https://raw.githubusercontent.com/pycountry/pycountry/main/src/pycountry/databases/"

# IMDb's own private-use country code(s) that aren't resolvable against the standard's own tables
# -- ISO 3166-1's "X*" range is reserved for exactly this kind of local/private assignment.
# Deliberately kept out of iso_country_enum itself (which stays a clean, unmodified mirror of the
# standard) and applied only here, in the lookup every caller already resolves through -- see
# DBControl.getIsoCountryLookup. Mirrors isolanguages.NON_STANDARD_ALIASES.
NON_STANDARD_ALIASES = {
    "XWG": "DE",  # IMDb's "West Germany" -> Germany; the standard never distinguished it from
                  # unified Germany in the first place (only East Germany got its own historical
                  # code, DDDE) -- IMDb drew a distinction the standard doesn't make
}


def _ensureLocalDataFiles():
    """Downloads both source files into _BASE_DIR if either is missing -- always both together,
    same reasoning as isolanguages._ensureLocalDataFiles. No retry of its own: this only ever runs
    once, the first time a DB is created on a given machine."""
    currentPath = os.path.join(_BASE_DIR, _CURRENT_FILENAME)
    formerPath = os.path.join(_BASE_DIR, _FORMER_FILENAME)
    if os.path.isfile(currentPath) and os.path.isfile(formerPath):
        return
    os.makedirs(_BASE_DIR, exist_ok=True)
    for filename in (_CURRENT_FILENAME, _FORMER_FILENAME):
        response = requests.get(_DOWNLOAD_BASE_URL + filename, timeout=(10, 30))
        response.raise_for_status()
        with open(os.path.join(_BASE_DIR, filename), "wb") as f:
            f.write(response.content)


def seedIsoCountryEnum(cursor):
    """Populates an already-created, empty iso_country_enum table. Idempotent only in the sense
    that re-running it against a non-empty table raises (UNIQUE/PRIMARY KEY violation) rather than
    silently duplicating or overwriting. country_code (the primary key) is the current alpha_2 for
    a current country, or the ISO 3166-3 alpha_4 (e.g. "SUHH") for a formerly-used one.

    alpha_2/alpha_3/numeric_code are deliberately NOT unique across the table: ISO 3166 itself
    reuses them -- a country that changed name without changing its alpha_2 (e.g. Belarus, still
    "BY", also has a historical "Byelorussian SSR" entry under the same alpha_2), or a retired
    code later reassigned to an unrelated new country (e.g. "SK" was once Sikkim, is now Slovakia;
    "CS" was assigned to both Czechoslovakia and, decades later, Serbia and Montenegro). See
    buildLookup for how this ambiguity is resolved in practice."""
    _ensureLocalDataFiles()
    with open(os.path.join(_BASE_DIR, _CURRENT_FILENAME), encoding="utf-8") as f:
        current = json.load(f)["3166-1"]
    with open(os.path.join(_BASE_DIR, _FORMER_FILENAME), encoding="utf-8") as f:
        former = json.load(f)["3166-3"]

    for row in current:
        cursor.execute(
            "INSERT INTO iso_country_enum (country_code, alpha_2, alpha_3, numeric_code, name, is_historical) VALUES (?, ?, ?, ?, ?, 0)",
            (row["alpha_2"], row["alpha_2"], row.get("alpha_3"), row.get("numeric"), row["name"]),
        )
    for row in former:
        cursor.execute(
            "INSERT INTO iso_country_enum (country_code, alpha_2, alpha_3, numeric_code, name, is_historical) VALUES (?, ?, ?, ?, ?, 1)",
            (row["alpha_4"], row.get("alpha_2"), row.get("alpha_3"), row.get("numeric"), row["name"]),
        )


def buildLookup(cursor):
    """{raw_code: canonical country_code} covering every current alpha_2/alpha_3/numeric code and
    every formerly-used alpha_2/alpha_3/alpha_4/numeric code in iso_country_enum, plus
    NON_STANDARD_ALIASES -- for resolving a country code from IMDb's own code conventions to one
    canonical key. See DBControl.getIsoCountryLookup.

    Processes historical rows first, current rows second, so that on the handful of genuine,
    standards-documented alpha_2/alpha_3/numeric collisions between a current and a historical
    entry (see seedIsoCountryEnum), the CURRENT country always wins -- e.g. "BY" resolves to
    Belarus, never the historical Byelorussian SSR entry that happens to share its alpha_2. A
    movie's country is essentially always meant in present-day terms; IMDb has no titles credited
    to the Byelorussian SSR specifically."""
    cursor.execute("SELECT country_code, alpha_2, alpha_3, numeric_code FROM iso_country_enum ORDER BY is_historical DESC")
    lookup = {}
    for country_code, alpha_2, alpha_3, numeric_code in cursor.fetchall():
        lookup[country_code] = country_code
        if alpha_2:
            lookup[alpha_2] = country_code
        if alpha_3:
            lookup[alpha_3] = country_code
        if numeric_code:
            lookup[numeric_code] = country_code
    lookup.update(NON_STANDARD_ALIASES)
    return lookup
