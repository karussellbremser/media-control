from flask import Flask, Response, render_template, request, jsonify, send_from_directory
from werkzeug.security import check_password_hash, generate_password_hash
import sqlite3, os, sys, hashlib, hmac, codecs, re, collections
import serverconfig
from model.imdbinterestid import parseInterestID
from model.media import Media
from web import authfile

server = Flask(__name__)

def _readAuthFile(path):
    """{username: werkzeug password hash} from the login file at path (one "username:hash" line per user, see
    authfile.py and README.md, "Hosting the web UI with Docker"). Fails closed: a missing or malformed file
    stops the server from starting at all, rather than leaving it open."""
    try:
        return authfile.read(path)
    except OSError as e:
        sys.exit("config.ini's [server] auth_file is set, but " + path + " can't be read: " + str(e))
    except authfile.AuthFileError as e:
        sys.exit(str(e))

# optional HTTP basic auth for the whole site (pages, API and covers alike) -- only active when
# config.ini's [server] auth_file names a credentials file, so running the server locally needs no
# login. Meant for hosting it behind a reverse proxy that provides the HTTPS
AUTH_CREDENTIALS = _readAuthFile(serverconfig.SERVER_AUTH_FILE) if serverconfig.SERVER_AUTH_FILE else None
_verifiedCredentialsDigests = {}  # see requireLogin
_UNKNOWN_USER_HASH = generate_password_hash("not a password anybody has")  # see requireLogin

@server.before_request
def requireLogin():
    if AUTH_CREDENTIALS is None:
        return None

    auth = request.authorization
    if auth is not None and auth.type == "basic":
        username = auth.username or ""
        presented = username + "\0" + (auth.password or "")
        presentedDigest = hashlib.sha256(presented.encode("utf-8")).digest()
        # the browser repeats its credentials on every request, a coverwall page easily making dozens
        # in a burst, and checking a scrypt hash costs ~100ms each -- so once a full check has
        # succeeded, the SHA-256 of those exact credentials is remembered (in memory only, one per
        # user) and later requests are compared against it instead
        verified = _verifiedCredentialsDigests.get(username)
        if verified is not None and hmac.compare_digest(presentedDigest, verified):
            return None
        # an unknown user costs one hash check too (against a hash nobody can match), so a response's timing
        # doesn't tell which names exist
        passwordHash = AUTH_CREDENTIALS.get(username)
        if check_password_hash(passwordHash or _UNKNOWN_USER_HASH, auth.password or "") and passwordHash is not None:
            _verifiedCredentialsDigests[username] = presentedDigest
            return None

    return Response("Login required", 401, {"WWW-Authenticate": 'Basic realm="media-control", charset="UTF-8"'})

def _readHiddenInterestIDs(path):
    """Reads serverconfig.HIDDEN_INTEREST_IDS_PATH: subgenres never shown/selectable in the UI, though
    still scraped and stored normally (e.g. "Tragedy" spoilers a movie's ending). One imdb interest
    id (e.g. in0000090) per line, blank lines ignored. Read once at server start -- restart the
    server to pick up changes. A missing file is treated as an empty list."""
    if not os.path.exists(path):
        return set()
    with open(path, "r") as f:
        return {parseInterestID(line.strip()) for line in f if line.strip()}

HIDDEN_INTEREST_IDS = _readHiddenInterestIDs(serverconfig.HIDDEN_INTEREST_IDS_PATH)

def _excludeHiddenInterests(column):
    """(sql, params) appending "AND <column> NOT IN (...)" for every hidden interest id -- empty when
    none are configured -- for any query that lists a title's interests to the UI (the list view's
    genre line, the detail overlay's chips), so a hidden interest never shows up anywhere, not just
    in the filter sidebar (see the interest-group loop in index())."""
    if not HIDDEN_INTEREST_IDS:
        return "", []
    hidden = sorted(HIDDEN_INTEREST_IDS)
    return " AND " + column + " NOT IN (" + ",".join("?" for _ in hidden) + ")", hidden

def _randomKey(imdb_id, seed):
    """Sort key for the "random" sort: a well-mixed pseudo-random number that depends ONLY on the
    title's id and the seed. Because a title's key never depends on which other titles are in the
    result, one seed means one fixed order for the whole library: paging and infinite scroll stay
    consistent, and adding or removing filters only removes or re-adds titles without ever
    reshuffling the rest. A different seed gives an unrelated order. (A hash rather than SQLite's own
    random(), which can't be seeded, or an arithmetic scramble, whose neighbouring ids would follow
    visible patterns.)"""
    digest = hashlib.blake2b((str(seed) + ":" + str(imdb_id)).encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big") >> 1 # keep it within SQLite's signed 64-bit integers

def _buildFilter(search_query, year_from, year_to,
                 rating_from, rating_to,
                 votes_from, votes_to,
                 selected_interest_ids,
                 excluded_interest_ids,
                 selected_language_code,
                 show_movies, show_series,
                 series_ended=False, series_fully_owned=False,
                 series_not_ended=False, series_not_fully_owned=False,
                 series_mini=False, series_not_mini=False,
                 person_id=None, person_roles=()):
    """The part of the media query that decides WHICH titles match the current filter selection,
    shared by queryMedia (the list) and countMedia (the total shown above it) so the two can never
    disagree. Returns (joinSql, whereSql, havingSql, params) to be appended after "FROM media m JOIN
    title_type_enum tt ON ..." and before the caller's GROUP BY m.imdb_id / ORDER BY -- or None when
    no media type is selected at all (nothing can match)."""
    if not (show_movies or show_series):
        return None

    joinSql = ""
    params = []

    # filter genres/interests (selected_interest_ids may mix genre and subgenre ids)
    if selected_interest_ids:
        joinSql = " JOIN media_interests mi_filter ON m.imdb_id = mi_filter.imdb_id"

    sql = " WHERE m.subdir IS NOT NULL"

    # media types to include -- episodes never appear here (episodeTitleTypes is never added), since they
    # were never meant to have their own top-level browsing entry. The two series options narrow the SERIES
    # only (movies are unaffected): "ended" = IMDb gives the series an end year; "all episodes available" = it has
    # episodes and every one of them is locally owned -- the same test as the list's complete-episodes badge.
    # Each also exists as its NOT (right-click in the UI): still running / not all episodes available.
    # A third option separates the two series types: "mini series" = tvMiniSeries, its NOT = regular tvSeries
    typeBranches = []
    if show_movies:
        typeBranches.append("tt.title_type_name IN (" + ",".join("?" for _ in Media.movieTitleTypes) + ")")
        params.extend(Media.movieTitleTypes)
    if show_series:
        seriesCond = "tt.title_type_name IN (" + ",".join("?" for _ in Media.seriesTitleTypes) + ")"
        params.extend(Media.seriesTitleTypes)
        if series_mini:
            seriesCond += " AND tt.title_type_name = 'tvMiniSeries'"
        if series_not_mini:
            seriesCond += " AND tt.title_type_name != 'tvMiniSeries'"
        if series_ended:
            seriesCond += " AND m.end_year IS NOT NULL"
        if series_not_ended:
            seriesCond += " AND m.end_year IS NULL"
        if series_fully_owned:
            seriesCond += (" AND EXISTS (SELECT 1 FROM media me WHERE me.series_imdb_id = m.imdb_id)"
                           " AND NOT EXISTS (SELECT 1 FROM media me WHERE me.series_imdb_id = m.imdb_id AND me.subdir IS NULL)")
        if series_not_fully_owned:
            seriesCond += (" AND (NOT EXISTS (SELECT 1 FROM media me WHERE me.series_imdb_id = m.imdb_id)"
                           " OR EXISTS (SELECT 1 FROM media me WHERE me.series_imdb_id = m.imdb_id AND me.subdir IS NULL))")
        typeBranches.append("(" + seriesCond + ")")
    sql += " AND (" + " OR ".join(typeBranches) + ")"

    # text search -- each word must match either the original or the primary (localized) title
    if search_query:
        words = search_query.split()
        for word in words:
            sql += " AND (original_title LIKE ? COLLATE NOCASE OR primary_title LIKE ? COLLATE NOCASE)"
            params.append(f"%{word}%")
            params.append(f"%{word}%")

    # filter years -- movies match on an exact start_year range; series match if the filter range
    # overlaps the series' production span (start_year..end_year, or start_year..currentYear if the
    # series is still running, i.e. end_year is NULL). Cast to int explicitly rather than relying on
    # SQLite's column-affinity coercion of the raw query-string values: that coercion only applies
    # to a bare column reference, not to COALESCE(m.end_year, ...) below (a function call has no
    # affinity), so an uncast string parameter there would silently never match (SQLite's storage-
    # class ordering puts every INTEGER below every TEXT value).
    if year_from or year_to:
        year_from = int(year_from) if year_from else None
        year_to = int(year_to) if year_to else None
        yearBranches = []
        if show_movies:
            movieCond = "tt.title_type_name IN (" + ",".join("?" for _ in Media.movieTitleTypes) + ")"
            params.extend(Media.movieTitleTypes)
            if year_from:
                movieCond += " AND m.start_year >= ?"
                params.append(year_from)
            if year_to:
                movieCond += " AND m.start_year <= ?"
                params.append(year_to)
            yearBranches.append("(" + movieCond + ")")
        if show_series:
            seriesCond = "tt.title_type_name IN (" + ",".join("?" for _ in Media.seriesTitleTypes) + ")"
            params.extend(Media.seriesTitleTypes)
            if year_from:
                seriesCond += " AND COALESCE(m.end_year, CAST(strftime('%Y', 'now') AS INTEGER)) >= ?"
                params.append(year_from)
            if year_to:
                seriesCond += " AND m.start_year <= ?"
                params.append(year_to)
            yearBranches.append("(" + seriesCond + ")")
        sql += " AND (" + " OR ".join(yearBranches) + ")"

    # filter ratings
    if rating_from:
        sql += " AND rating_mul10 >= ?"
        params.append(int(float(rating_from) * 10))
    if rating_to:
        sql += " AND rating_mul10 <= ?"
        params.append(int(float(rating_to) * 10))

    # filter num votes
    if votes_from:
        sql += " AND num_votes >= ?"
        params.append(votes_from)
    if votes_to:
        sql += " AND num_votes <= ?"
        params.append(votes_to)

    # filter language -- by primary language only (the first one IMDb lists, media_languages ordering 1)
    if selected_language_code is not None:
        sql += " AND EXISTS (SELECT 1 FROM media_languages ml WHERE ml.imdb_id = m.imdb_id AND ml.ordering = 1 AND ml.language_code = ?)"
        params.append(selected_language_code)

    # filter genres/interests (AND across all selected)
    if selected_interest_ids:
        placeholders = ",".join("?" for _ in selected_interest_ids)
        sql += f" AND mi_filter.imdb_interest_id IN ({placeholders})"
        params.extend(selected_interest_ids)

    # NOT filter -- a title with ANY of the excluded genres/subgenres is dropped (a title with no
    # interests at all passes). A separate EXISTS rather than part of the join above: that join
    # only ever sees the selected interests' rows, which is exactly what's wrong for "has none of these"
    if excluded_interest_ids:
        placeholders = ",".join("?" for _ in excluded_interest_ids)
        sql += f" AND NOT EXISTS (SELECT 1 FROM media_interests mi_excl WHERE mi_excl.imdb_id = m.imdb_id AND mi_excl.imdb_interest_id IN ({placeholders}))"
        params.extend(excluded_interest_ids)

    # person filter -- the titles the person is credited on in any of the ticked kinds (person_roles, a subset
    # of CREDIT_KINDS: a union, like the movies/series boxes; none ticked matches nothing). A movie has the credits
    # itself, a series only through its episodes' credits (classified as series credits, see _creditRole). Written
    # as a set of title ids computed up front rather than a per-title EXISTS: that lets SQLite seek the person's
    # few credits in idx_credits_person instead of probing credits once per media row (50x slower in a test).
    if person_id is not None:
        if not person_roles:
            return None
        kinds = [k for k in CREDIT_KINDS if k in person_roles]
        kindSql = ""
        kindParams = []
        if len(kinds) < len(CREDIT_KINDS): # all ticked = any credit at all, no need to classify them
            kindSql = " AND credit_kind(c.role_id, c.details, {}) IN (" + ",".join("?" for _ in kinds) + ")"
            kindParams = kinds
        sql += (" AND m.imdb_id IN (SELECT c.imdb_id FROM credits c WHERE c.person_id = ?" + kindSql.format(0)
                + " UNION SELECT e.series_imdb_id FROM credits c JOIN media e ON e.imdb_id = c.imdb_id"
                  " WHERE c.person_id = ? AND e.series_imdb_id IS NOT NULL" + kindSql.format(1) + ")")
        params.extend([person_id] + kindParams + [person_id] + kindParams)

    havingSql = ""
    if selected_interest_ids:
        havingSql = f" HAVING COUNT(DISTINCT mi_filter.imdb_interest_id) = {len(selected_interest_ids)}"

    return joinSql, sql, havingSql, params

def countMedia(filters):
    """How many titles match filters (the same tuple queryMedia takes) -- the number the list would
    reach if scrolled to its end, regardless of sort order and paging."""
    built = _buildFilter(*filters)
    if built is None:
        return 0
    joinSql, whereSql, havingSql, params = built

    conn = _connect()
    try:
        return conn.execute("SELECT COUNT(*) FROM (SELECT m.imdb_id FROM media m JOIN title_type_enum tt ON m.title_type_id = tt.title_type_id"
                            + joinSql + whereSql + " GROUP BY m.imdb_id" + havingSql + ")", params).fetchone()[0]
    finally:
        conn.close()

def queryMedia(filters, sort_by, order, limit, offset, random_seed=0):
    """One page of the titles matching filters, a tuple of the arguments of _buildFilter (search
    string, year/rating/votes ranges, selected and excluded interests, language, movies/series)."""
    built = _buildFilter(*filters)
    if built is None:
        return []
    joinSql, whereSql, havingSql, filterParams = built

    conn = _connect()
    cursor = conn.cursor()

    # the list view's genre line must not show hidden interests either (its params come first: this
    # subquery's placeholders precede the CASE ... IN (...) ones further down the statement)
    hiddenSql, hiddenParams = _excludeHiddenInterests("mi_show.imdb_interest_id")
    # only a series can have episodes, so the two episode counts are only evaluated for series rows
    # (CASE branches are lazy): media has no index on series_imdb_id, so each count is a full table
    # scan, and running them for every movie too made the default query ~100x slower (~800ms vs ~10ms
    # at ~650 owned titles) for counts that are always 0 there. Each CASE below carries its own copy
    # of the series-type placeholders, in statement order, hence the repeated params further down.
    seriesTypePlaceholders = ",".join("?" for _ in Media.seriesTitleTypes)
    sql = """
    SELECT m.imdb_id, m.original_title, m.start_year, m.end_year, m.rating_mul10, m.num_votes,
    (
        SELECT GROUP_CONCAT(ie.name, ', ')
        FROM media_interests mi_show
        JOIN interest_enum ie ON mi_show.imdb_interest_id = ie.imdb_interest_id
        WHERE mi_show.imdb_id = m.imdb_id""" + hiddenSql + """
        ORDER BY ie.name
    ) as tags,
    CASE WHEN tt.title_type_name IN (""" + seriesTypePlaceholders + """) THEN (
        SELECT COUNT(*) FROM media me WHERE me.series_imdb_id = m.imdb_id
    ) ELSE 0 END as total_episodes,
    CASE WHEN tt.title_type_name IN (""" + seriesTypePlaceholders + """) THEN (
        SELECT COUNT(*) FROM media me WHERE me.series_imdb_id = m.imdb_id AND me.subdir IS NOT NULL
    ) ELSE 0 END as owned_episodes,
    CASE WHEN tt.title_type_name IN (""" + seriesTypePlaceholders + """) THEN 1 ELSE 0 END as is_series
    FROM media m
    JOIN title_type_enum tt ON m.title_type_id = tt.title_type_id
    """
    params = hiddenParams + list(Media.seriesTitleTypes) * 3

    sql += joinSql + whereSql
    params.extend(filterParams)

    sql += " GROUP BY m.imdb_id" + havingSql

    # sorting
    if sort_by == "random":
        column = None # ordered by _randomKey below instead of by a column
    elif sort_by == "rating":
        column = "rating_mul10"
    elif sort_by == "votes":
        column = "num_votes"
    elif sort_by == "year":
        column = "start_year"
    elif sort_by == "modified":
        # the newest file modification date of the medium (media_versions.mtime, whole seconds): the
        # newest of a movie's version files, or -- for a series, which has no files of its own -- the
        # newest file of any of its episodes. The CASE keeps the per-row lookup to the one branch
        # that applies (its placeholders come after everything above and before LIMIT/OFFSET below).
        column = ("CASE WHEN tt.title_type_name IN (" + seriesTypePlaceholders + ") "
                  "THEN (SELECT MAX(mv.mtime) FROM media me JOIN media_versions mv ON mv.imdb_id = me.imdb_id WHERE me.series_imdb_id = m.imdb_id) "
                  "ELSE (SELECT MAX(mv.mtime) FROM media_versions mv WHERE mv.imdb_id = m.imdb_id) END")
        params.extend(Media.seriesTitleTypes)
    else:
        column = "original_title"

    if order == "asc":
        direction = "ASC"
    else:
        direction = "DESC"

    if sort_by == "random":
        # direction doesn't apply: the client sends a fresh seed when the option is selected, and keeps
        # sending the same one for as long as it stays selected (see _randomKey)
        conn.create_function("randomkey", 2, _randomKey, deterministic=True)
        sql += " ORDER BY randomkey(m.imdb_id, ?), m.imdb_id"
        params.append(random_seed)
    else:
        sql += " ORDER BY COALESCE(" + column + ", 0) " + direction
        if sort_by == "modified":
            sql += ", m.imdb_id " + direction # many files can share a modification second; keep paging deterministic
    
    # pagination
    sql += " LIMIT ? OFFSET ?"
    params.append(limit)
    params.append(offset)
    
    cursor.execute(sql, params)
    media = cursor.fetchall()
    conn.close()
    return media

@server.route('/')
def index():
    conn = sqlite3.connect(serverconfig.DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT imdb_interest_id, name, description
        FROM interest_enum
        WHERE parent_imdb_interest_id IS NULL
        ORDER BY name
    """)
    genres = cursor.fetchall()

    # subgenres grouped by parent genre; interestRows is ordered by parent name so rows for
    # the same parent are contiguous, letting this be grouped in one pass below
    cursor.execute("""
        SELECT p.imdb_interest_id, p.name, i.imdb_interest_id, i.name, i.description
        FROM interest_enum i
        JOIN interest_enum p ON i.parent_imdb_interest_id = p.imdb_interest_id
        ORDER BY p.name, i.name
    """)
    interestGroups = []
    currentGroup = None
    for parent_id, parent_name, interest_id, interest_name, interest_desc in cursor.fetchall():
        if interest_id in HIDDEN_INTEREST_IDS:
            continue
        if currentGroup is None or currentGroup[0] != parent_id:
            currentGroup = (parent_id, parent_name, [])
            interestGroups.append(currentGroup)
        currentGroup[2].append((interest_id, interest_name, interest_desc))

    # only languages that are some title's PRIMARY language -- the filter matches on that alone, so a
    # language that only ever appears further down a title's list would be an option with no results.
    # IMDb's "None" (code zxx, a silent/dialogue-free title) is shown as "Silent". Ordered by how many
    # titles have that language as their primary one, most first (English is just another language
    # here, no longer pinned to the top); ties alphabetically by displayed name
    cursor.execute("""
        SELECT le.iso639_3, le.name, COUNT(*)
        FROM iso_language_enum le
        JOIN media_languages ml ON ml.language_code = le.iso639_3 AND ml.ordering = 1
        GROUP BY le.iso639_3
    """)
    languages = [(code, name) for code, name, _ in sorted(
        ((code, "Silent" if code == "zxx" else name, count) for code, name, count in cursor.fetchall()),
        key=lambda language: (-language[2], language[1]))]

    conn.close()
    return render_template('index.html', genres=genres, interestGroups=interestGroups, languages=languages,
                            curtain_enabled=serverconfig.CURTAIN_ANIMATION_ENABLED, curtain_style=serverconfig.CURTAIN_STYLE)

@server.route('/search')
def search():
    args = request.args
    selected_interest_ids = [int(x) for x in args.getlist('genres[]') + args.getlist('interests[]')]
    excluded_interest_ids = [int(x) for x in args.getlist('notGenres[]') + args.getlist('notInterests[]')]
    selected_language_code = args.get('language') or None
    show_movies = args.get('movies', '1') == '1'
    show_series = args.get('series', '0') == '1'
    series_ended = args.get('series_ended', '0') == '1'
    series_fully_owned = args.get('series_full', '0') == '1'
    series_not_ended = args.get('series_not_ended', '0') == '1'
    series_not_fully_owned = args.get('series_not_full', '0') == '1'
    series_mini = args.get('series_mini', '0') == '1'
    series_not_mini = args.get('series_not_mini', '0') == '1'
    # person filter: person = a person's imdb id, person_roles = the ticked kinds of credit, comma separated (absent
    # = all of them, empty = none ticked, which matches nothing)
    try:
        person_id = int(args['person']) if args.get('person') else None
    except ValueError:
        person_id = None
    person_roles = tuple(k for k in args.get('person_roles', ','.join(CREDIT_KINDS)).split(',') if k in CREDIT_KINDS)

    page = int(args.get('page', 1))
    limit = 50
    offset = (page - 1) * limit
    try:
        random_seed = int(args.get('seed', 0)) % (2 ** 31) # only used by sort=random; bounded so a silly value can't overflow SQLite's integers
    except ValueError:
        random_seed = 0

    # a plain sqlite3.Error here (most plausibly "database is locked", from a sync running
    # concurrently in another terminal -- see DBControl's default 5s busy timeout) is reported to
    # the client as a clean JSON error instead of Flask's default HTML 500 page, which search.js
    # can't parse as JSON and would otherwise fail on invisibly (see fetchResults's error handling)
    try:
        filters = (
            args.get('q', ''),
            args.get('year_from'),
            args.get('year_to'),
            args.get('rating_from'),
            args.get('rating_to'),
            args.get('votes_from'),
            args.get('votes_to'),
            selected_interest_ids,
            excluded_interest_ids,
            selected_language_code,
            show_movies,
            show_series,
            series_ended,
            series_fully_owned,
            series_not_ended,
            series_not_fully_owned,
            series_mini,
            series_not_mini,
            person_id,
            person_roles
        )
        media = queryMedia(filters, args.get('sort', 'year'), args.get('order', 'desc'), limit, offset, random_seed)
        # the total only changes with the filters, not with the page, so only the first page asks for it
        total = countMedia(filters) if page == 1 else None
    except sqlite3.Error as e:
        return jsonify({"error": str(e)}), 503
    response = jsonify(media)
    if total is not None:
        response.headers['X-Total-Count'] = str(total)
    return response

# covers rarely change, so the browser may keep using its stored copy for a week without asking the server
# (Flask's default is "no-cache", i.e. one revalidating request per cover on every page visit -- dozens per
# screen). A cover replaced under the same file name shows up after at most a week, or at once on a hard refresh.
COVER_MAX_AGE = 7 * 24 * 3600

@server.route('/cover_small/<filename>')
def coverSmall(filename):
    return send_from_directory(serverconfig.COVERS_SMALL_DIR, filename, max_age=COVER_MAX_AGE)

@server.route('/cover/<filename>')
def coverFull(filename):
    return send_from_directory(serverconfig.COVERS_DIR, filename, max_age=COVER_MAX_AGE)

# A writer credit that belongs to the SERIES rather than to the episode: IMDb repeats it on every
# episode's credits ("created by", "developed for television by", "co-created by", "creator", ...).
# "based on characters created by" and the like don't match -- they credit source material.
_CREATOR_DETAILS = re.compile(r"(series |co-)?(created|developed)( for television)? by\b|(co-)?creator\b|developer\b", re.IGNORECASE)

# A writer credit for the SOURCE MATERIAL rather than for writing: "based on the novel by", "inspired by",
# "suggested by the motion picture written by", "book", "novel", "characters created by", "original
# creator", ... (shown as "Based on"). "story by", "screenplay", "teleplay" and "adaptation" are writing.
_SOURCE_DETAILS = re.compile(
    r"(loosely |partly |partially )?(based|inspired|suggested)\b"
    r"|(original )?(novels?|novellas?|books?|plays?|short stories|short story|comics?|graphic novels?|characters?)\b"
    r"|original creator\b"
    r"|stories\b"
    r"|(original )?(story|screenplay):? \"" # a quoted title right after: the earlier work (story "Children of the Corn", screenplay "Yojimbo")
    r"|from the (novel|book|story|play|comic)\b|adapted from\b|this work contains material from\b"
    r"|\(?(\d{4} )?(short )?(film|motion picture)\b" # film "Fright Night", motion picture "Rec", (1970 film "...")
    r"|memoirs?\b|(epic )?poem\b|song \"|musical book\b", re.IGNORECASE)

def _creditRole(role_id, details, isSeries):
    """The key a credit is listed under: its role id, except that a writer credit may really be a
    series-wide creator credit ("creators", series only) or a source-material credit ("source")."""
    if role_id == 2 and details:
        if isSeries and _CREATOR_DETAILS.match(details):
            return "creators"
        if _SOURCE_DETAILS.match(details):
            return "source"
    return role_id

# the kinds of credit a person can have in the library, in the order the overlay lists them: the five lists of
# the "Cast & crew" block. "created" only exists for series (see _creditRole), the rest for movies and series alike.
CREDIT_KINDS = ("created", "directed", "written", "basedon", "cast")

def _creditKind(role_id, details, isSeries):
    """Which of CREDIT_KINDS a credit belongs to -- decided by _creditRole, so the person filter and the
    lists of the detail view can never disagree about it."""
    return {1: "directed", 2: "written", 3: "cast", "creators": "created", "source": "basedon"}[_creditRole(role_id, details, isSeries)]

def _connect():
    """A connection to the DB with credit_kind(role_id, details, is_series) available to SQL (the person filter)."""
    conn = sqlite3.connect(serverconfig.DB_PATH)
    conn.create_function("credit_kind", 3, lambda role_id, details, isSeries: _creditKind(role_id, details, bool(isSeries)), deterministic=True)
    return conn

def _sourceDetails(details):
    """A source credit's wording as shown behind the person's name: without "(as <alias>)", the
    trailing "&"/"and" IMDb adds when a credit is shared and the dangling "by" ("based on the novel
    by" -> "based on the novel"; also "written by", "created by"). None if nothing is left."""
    details = re.sub(r"\s*\(as [^)]*\)", "", details)
    while True:
        cleaned = re.sub(r"\s+(&|and|(written |created )?by)$", "", details.strip())
        if cleaned == details:
            return details or None
        details = cleaned

# how strongly a prominent position outweighs a middle one when ranking a series' people -- a
# credit's weight is (1 - relative position) ** exponent, see _seriesCredits
_POSITION_EXPONENT = 3

def _seriesCredits(cursor, series_imdb_id):
    """Cast & crew of a series, compiled from the credits of its episodes (a series has none of its
    own, see ScrapeIMDbOnline.scrapeFullCredits), as {1: directors, 2: writers, 3: actors,
    "creators": creators, "source": source material}, each a ranked list of {name, birthYear,
    deathYear, details}.

    Each appearance of a person in a role counts with the weight (1 - relative position) **
    _POSITION_EXPONENT, where the relative position is the credit's place within that episode's list
    of that role (0 for the first entry, towards 1 for the last, so cast lists of different
    lengths are comparable). A person's score is the sum over their episodes, so it rewards both
    frequent appearances and prominent slots; ties go to more episodes, then the better average
    position. No episode counts are exposed, they might give away more than wanted.

    The series-wide creator credits (see _CREATOR_DETAILS) and the source-material credits (see
    _SOURCE_DETAILS) are pulled out of the writers into "creators" and "source", ranked by the
    number of episodes carrying the credit; anyone with actual writing credits too still appears
    under writers. An actor's details are the character name that appears most often (a person
    may also be credited as other characters or "uncredited"); a source credit's, its wording."""
    cursor.execute("""
        SELECT c.imdb_id, c.role_id, c.person_id, p.name, p.birth_year, p.death_year, c.ordering, c.details,
               COUNT(*) OVER (PARTITION BY c.imdb_id, c.role_id)
        FROM credits c
        JOIN media e ON c.imdb_id = e.imdb_id
        JOIN people p ON c.person_id = p.imdb_id
        WHERE e.series_imdb_id = ?
    """, (series_imdb_id,))

    # (role key, person) -> [score, episodes, sum of relative positions, details counter]
    people = {}
    for episode_id, role_id, person_id, name, birth_year, death_year, ordering, details, listLength in cursor.fetchall():
        role = _creditRole(role_id, details, True)
        if role == "source":
            details = _sourceDetails(details)
        relativePosition = (ordering - 1) / listLength
        entry = people.setdefault((role, person_id), {
            "person": {"personId": person_id, "name": name, "birthYear": birth_year, "deathYear": death_year},
            "score": 0.0, "episodes": set(), "positionSum": 0.0, "credits": 0, "details": collections.Counter()})
        entry["score"] += (1 - relativePosition) ** _POSITION_EXPONENT
        entry["episodes"].add(episode_id)
        entry["positionSum"] += relativePosition
        entry["credits"] += 1
        entry["details"][details] += 1

    result = {1: [], 2: [], 3: [], "creators": [], "source": []}
    ranked = sorted(people.items(), key=lambda kv: (
        -len(kv[1]["episodes"]) if kv[0][0] in ("creators", "source") else -kv[1]["score"],
        -len(kv[1]["episodes"]), kv[1]["positionSum"] / kv[1]["credits"], kv[1]["person"]["name"]))
    for (role, _), entry in ranked:
        result[role].append(dict(entry["person"], details=entry["details"].most_common(1)[0][0]))
    return result

def _addTitleCounts(cursor, credits):
    """Adds "titleCount" -- how many library titles (movies and series, an episode counting for its series) the
    person is credited on -- to every person of a credits dict as built for the detail view."""
    people = [p for kind in credits.values() for p in kind]
    counts = {}
    ids = sorted({p["personId"] for p in people})
    for i in range(0, len(ids), 500):
        batch = ids[i:i + 500]
        cursor.execute("""
            SELECT c.person_id, COUNT(DISTINCT CASE WHEN e.series_imdb_id IS NULL THEN e.imdb_id ELSE e.series_imdb_id END)
            FROM credits c JOIN media e ON e.imdb_id = c.imdb_id
            WHERE c.person_id IN (""" + ",".join("?" for _ in batch) + """)
            GROUP BY c.person_id
        """, batch)
        counts.update(cursor.fetchall())
    for p in people:
        p["titleCount"] = counts.get(p["personId"], 0)

def _connections(cursor, imdb_id, isSeries):
    """The connections shown for a title, as a list of {type, imdbId, title, year, owned, seriesTitle,
    seriesId, seriesTitle, season, episode, origins}. A series also takes over the connections of its owned episodes: a
    target reached from several episodes is listed once, with those episodes as "origins" ({season,
    episode, title}, in episode order) -- the series' own connections have none, and win when the
    same target is reached both ways.
    seriesId/seriesTitle/season/episode say where a target is when that target is itself an episode
    (else None) -- an episode has no overlay of its own, the UI opens its series instead. Ordered by connection type, then the series' own connections (by year, title) before the
    episode-derived ones (the more episodes reach a target, the earlier; then year, title)."""
    cursor.execute("""
        SELECT ct.connection_type_id, ct.connection_type_name, m2.imdb_id, m2.original_title, m2.start_year,
               m2.subdir IS NOT NULL, s2.original_title, m2.season_number, m2.episode_number,
               mc.imdb_id, e.season_number, e.episode_number, e.original_title, m2.series_imdb_id
        FROM media_connections mc
        JOIN connection_type_enum ct ON mc.connection_type_id = ct.connection_type_id
        JOIN media m2 ON mc.foreign_imdb_id = m2.imdb_id
        LEFT JOIN media s2 ON m2.series_imdb_id = s2.imdb_id
        JOIN media e ON mc.imdb_id = e.imdb_id
        WHERE mc.imdb_id = :id""" + (" OR (e.series_imdb_id = :id AND e.subdir IS NOT NULL)" if isSeries else ""),
        {"id": imdb_id})

    targets = {} # (connection type id, target id) -> connection
    for (typeId, typeName, targetId, title, year, owned, seriesTitle, season, episode,
         originId, originSeason, originEpisode, originTitle, seriesId) in cursor.fetchall():
        target = targets.setdefault((typeId, targetId), {
            "type": typeName, "imdbId": targetId, "title": title, "year": year, "owned": bool(owned),
            "seriesId": seriesId, "seriesTitle": seriesTitle, "season": season, "episode": episode,
            "own": False, "origins": [], "typeId": typeId})
        if originId == imdb_id:
            target["own"] = True
        else:
            target["origins"].append({"season": originSeason, "episode": originEpisode, "title": originTitle})

    for target in targets.values():
        if target["own"]:
            target["origins"] = []
        target["origins"].sort(key=lambda o: (o["season"] is None, o["season"], o["episode"] is None, o["episode"], o["title"]))
    ordered = sorted(targets.values(), key=lambda t: (
        t["typeId"], not t["own"], -len(t["origins"]), t["year"] is None, t["year"], t["title"]))
    for target in ordered:
        del target["own"], target["typeId"]
    return ordered

@server.route('/people')
def people():
    """Name search for the person filter: up to 8 people whose name contains every word of q (at least 2
    characters). Names in which every typed word starts a word (first or last name alike, a half-typed word
    counts: "nola" finds "Christopher Nolan") come before names that only contain the text inside a word
    ("Manola"); within each group the ones with the most library titles come first."""
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])
    words = q.split()
    # a word starts after a space or a hyphen (the leading space makes the name's first word count too)
    startsWordSql = "(' ' || p.name LIKE ? COLLATE NOCASE OR p.name LIKE ? COLLATE NOCASE)"
    startsWordParams = [param for w in words for param in ("% " + w + "%", "%-" + w + "%")]
    try:
        conn = _connect()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT p.imdb_id, p.name, p.birth_year, p.death_year,
                   COUNT(DISTINCT CASE WHEN e.series_imdb_id IS NULL THEN e.imdb_id ELSE e.series_imdb_id END) AS titles,
                   (""" + " AND ".join(startsWordSql for _ in words) + """) AS startsWords
            FROM people p
            JOIN credits c ON c.person_id = p.imdb_id
            JOIN media e ON e.imdb_id = c.imdb_id
            WHERE """ + " AND ".join("p.name LIKE ? COLLATE NOCASE" for _ in words) + """
            GROUP BY p.imdb_id
            ORDER BY startsWords DESC, titles DESC, p.name
            LIMIT 8
        """, startsWordParams + ["%" + w + "%" for w in words])
        result = [{"id": i, "name": name, "birthYear": birth, "deathYear": death, "titles": titles}
                  for i, name, birth, death, titles, _ in cursor.fetchall()]
        conn.close()
    except sqlite3.Error as e:
        return jsonify({"error": str(e)}), 503
    return jsonify(result)

@server.route('/person/<int:person_id>')
def person(person_id):
    """A person for the filter chip: name, years and how many library titles they are credited on in each kind of
    credit (CREDIT_KINDS; a title counts once per kind, an episode for its series) and overall."""
    try:
        conn = _connect()
        cursor = conn.cursor()
        cursor.execute("SELECT name, birth_year, death_year FROM people WHERE imdb_id = ?", (person_id,))
        row = cursor.fetchone()
        if row is None:
            conn.close()
            return jsonify({"error": "not found"}), 404
        cursor.execute("""
            SELECT c.imdb_id, c.role_id, c.details, e.series_imdb_id
            FROM credits c JOIN media e ON e.imdb_id = c.imdb_id
            WHERE c.person_id = ?
        """, (person_id,))
        titlesByKind = {kind: set() for kind in CREDIT_KINDS}
        allTitles = set()
        for imdb_id, role_id, details, series_imdb_id in cursor.fetchall():
            title = series_imdb_id if series_imdb_id is not None else imdb_id
            titlesByKind[_creditKind(role_id, details, series_imdb_id is not None)].add(title)
            allTitles.add(title)
        conn.close()
    except sqlite3.Error as e:
        return jsonify({"error": str(e)}), 503
    return jsonify({"id": person_id, "name": row[0], "birthYear": row[1], "deathYear": row[2],
                    "titles": len(allTitles), "roles": {kind: len(titles) for kind, titles in titlesByKind.items()}})

@server.route('/detail/<int:imdb_id>')
def detail(imdb_id):
    """Everything the title detail overlay shows, for one locally-owned movie/series: basics, plot
    summary, genres/subgenres, credits (only ever stored for movies and episodes, so a series' are
    compiled from its episodes, see _seriesCredits), and connections to other titles, each flagged
    with whether the target is itself locally owned (=> the overlay can open it in place) or only
    referenced (=> links out to IMDb)."""
    try:
        conn = sqlite3.connect(serverconfig.DB_PATH)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT m.original_title, m.primary_title, m.start_year, m.end_year, m.rating_mul10, m.num_votes,
                   m.plot_summary, tt.title_type_name
            FROM media m
            JOIN title_type_enum tt ON m.title_type_id = tt.title_type_id
            WHERE m.imdb_id = ? AND m.subdir IS NOT NULL
        """, (imdb_id,))
        row = cursor.fetchone()
        if row is None:
            conn.close()
            return jsonify({"error": "not found"}), 404
        original_title, primary_title, start_year, end_year, rating_mul10, num_votes, plot_summary, title_type_name = row

        # an episode has no overlay of its own (no cover, no plot, nothing browsable): say where it sits in its
        # series, which the UI opens instead, on that episode. (An episode whose series isn't owned -- not
        # expected -- keeps the plain answer below.)
        if title_type_name in Media.episodeTitleTypes:
            cursor.execute("""
                SELECT e.series_imdb_id, e.season_number, e.episode_number
                FROM media e JOIN media s ON e.series_imdb_id = s.imdb_id
                WHERE e.imdb_id = ? AND s.subdir IS NOT NULL
            """, (imdb_id,))
            episodeRow = cursor.fetchone()
            if episodeRow is not None:
                conn.close()
                return jsonify({"episodeOf": {"seriesId": episodeRow[0], "season": episodeRow[1], "episode": episodeRow[2]}})

        # genres (no parent) first, then subgenres, each alphabetical; hidden interests left out, same
        # as everywhere else the UI lists interests
        hiddenSql, hiddenParams = _excludeHiddenInterests("mi.imdb_interest_id")
        cursor.execute("""
            SELECT ie.imdb_interest_id, ie.name, ie.parent_imdb_interest_id IS NULL
            FROM media_interests mi
            JOIN interest_enum ie ON mi.imdb_interest_id = ie.imdb_interest_id
            WHERE mi.imdb_id = ?""" + hiddenSql + """
            ORDER BY (ie.parent_imdb_interest_id IS NOT NULL), ie.name
        """, [imdb_id] + hiddenParams)
        interests = [{"id": interestId, "name": name, "isGenre": bool(isGenre)} for interestId, name, isGenre in cursor.fetchall()]

        allEpisodesOwned = False
        seasons = []
        if title_type_name in Media.seriesTitleTypes:
            credits = _seriesCredits(cursor, imdb_id)
            # episodes per season, how many of them are owned and the years they came out (season None = episodes IMDb
            # gives no season number)
            cursor.execute("""
                SELECT season_number, COUNT(*), SUM(subdir IS NOT NULL), MIN(start_year), MAX(start_year)
                FROM media
                WHERE series_imdb_id = ?
                GROUP BY season_number
                ORDER BY season_number IS NULL, season_number
            """, (imdb_id,))
            seasons = [{"season": season, "total": total, "owned": owned, "firstYear": firstYear, "lastYear": lastYear}
                       for season, total, owned, firstYear, lastYear in cursor.fetchall()]
            # a season that is only partly owned also says which of its episodes are (only those: the others stay unnamed)
            if any(0 < s["owned"] < s["total"] for s in seasons):
                cursor.execute("""
                    SELECT season_number, episode_number, original_title
                    FROM media
                    WHERE series_imdb_id = ? AND subdir IS NOT NULL
                    ORDER BY episode_number IS NULL, episode_number, original_title
                """, (imdb_id,))
                ownedBySeason = collections.defaultdict(list)
                for season, episode, title in cursor.fetchall():
                    ownedBySeason[season].append({"number": episode, "title": title})
                for s in seasons:
                    if 0 < s["owned"] < s["total"]:
                        s["ownedEpisodes"] = ownedBySeason[s["season"]]
            # the same test as the list's complete-episodes badge and the "All episodes available" filter; the overlay
            # only points out that the credits are compiled from the available episodes when some are missing
            cursor.execute("""
                SELECT EXISTS (SELECT 1 FROM media WHERE series_imdb_id = ?),
                       NOT EXISTS (SELECT 1 FROM media WHERE series_imdb_id = ? AND subdir IS NULL)
            """, (imdb_id, imdb_id))
            hasEpisodes, noneMissing = cursor.fetchone()
            allEpisodesOwned = bool(hasEpisodes and noneMissing)
        else:
            cursor.execute("""
                SELECT c.role_id, c.person_id, p.name, p.birth_year, p.death_year, c.details
                FROM credits c
                JOIN people p ON c.person_id = p.imdb_id
                WHERE c.imdb_id = ?
                ORDER BY c.role_id, c.ordering
            """, (imdb_id,))
            credits = {1: [], 2: [], 3: [], "creators": [], "source": []}
            listed = set()
            for role_id, person_id, name, birth_year, death_year, details in cursor.fetchall():
                role = _creditRole(role_id, details, False)
                # a person is listed once per list, at their first credit: IMDb often credits one person twice in a
                # role ("story" and "screenplay", "characters" and "novel") and the lists don't show the qualifier
                if (role, person_id) in listed:
                    continue
                listed.add((role, person_id))
                if role == "source":
                    details = _sourceDetails(details)
                credits[role].append({"personId": person_id, "name": name, "birthYear": birth_year, "deathYear": death_year, "details": details})

        _addTitleCounts(cursor, credits)
        connections = _connections(cursor, imdb_id, title_type_name in Media.seriesTitleTypes)
        conn.close()
    except sqlite3.Error as e:
        return jsonify({"error": str(e)}), 503

    return jsonify({
        "imdbId": imdb_id,
        "title": original_title,
        "primaryTitle": primary_title,
        "startYear": start_year,
        "endYear": end_year,
        "titleType": title_type_name,
        "isSeries": title_type_name in Media.seriesTitleTypes,
        "rating": rating_mul10 / 10 if rating_mul10 else None,
        "votes": num_votes,
        "plotSummary": plot_summary,
        "interests": interests,
        "allEpisodesOwned": allEpisodesOwned,
        "seasons": seasons,
        "creators": credits["creators"],
        "sources": credits["source"],
        "directors": credits[1],
        "writers": credits[2],
        "actors": credits[3],
        "connections": connections,
    })

if __name__ == '__main__':
    server.run(host=serverconfig.SERVER_HOST, port=serverconfig.SERVER_PORT)