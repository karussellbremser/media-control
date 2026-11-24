from flask import Flask, Response, redirect, render_template, request, jsonify, send_from_directory
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash
import sqlite3, os, sys, hashlib, codecs, re, collections, datetime, unicodedata, functools
import serverconfig
from model.imdbinterestid import parseInterestID
from model.media import Media
from web import authfile, login

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

# optional login for the whole site (pages, API and covers alike) -- only active when config.ini's [server]
# auth_file names a credentials file, so running the server locally needs no login. The login form (/login) sets
# a signed cookie that lasts 30 days (see login.py). Meant for hosting it behind a reverse proxy that provides the HTTPS
AUTH_CREDENTIALS = _readAuthFile(serverconfig.SERVER_AUTH_FILE) if serverconfig.SERVER_AUTH_FILE else None
_UNKNOWN_USER_HASH = generate_password_hash("not a password anybody has")  # see loginPage
_loginFailures = login.FailureThrottle()

if AUTH_CREDENTIALS is not None:
    # behind the proxy, the client's address (for the throttle of failed logins) and the scheme (for the cookie's
    # Secure flag) are what the proxy forwards: the one value its own hop added
    server.wsgi_app = ProxyFix(server.wsgi_app, x_for=1, x_proto=1)

def _loggedInUser():
    """The user the request's login cookie belongs to, or None (also when no login is configured)."""
    if AUTH_CREDENTIALS is None:
        return None
    return login.userOfCookie(request.cookies.get(login.COOKIE_NAME), AUTH_CREDENTIALS)

@server.before_request
def requireLogin():
    if AUTH_CREDENTIALS is None or request.endpoint in ("loginPage", "logout") or _loggedInUser() is not None:
        return None
    if request.path == "/":
        return redirect("/login") # the page itself leads to the login form
    # everything else is the page's own requests (API, covers): a plain 401, which search.js answers by reloading the page
    return Response("Login required", 401)

def _loginPage(error=None, username="", status=200):
    response = Response(render_template('login.html', title=serverconfig.SERVER_TITLE, error=error, username=username,
                                        curtain_enabled=serverconfig.CURTAIN_ANIMATION_ENABLED, curtain_style=serverconfig.CURTAIN_STYLE), status)
    response.headers["Cache-Control"] = "no-store"
    return response

@server.route('/login', methods=['GET', 'POST'])
def loginPage():
    if AUTH_CREDENTIALS is None or (request.method == 'GET' and _loggedInUser() is not None):
        return redirect("/")
    if request.method == 'GET':
        return _loginPage()
    address = request.remote_addr or ""
    username = request.form.get("username", "")
    if _loginFailures.blocked(address):
        return _loginPage("Too many failed attempts. Try again in a few minutes.", username, 429)
    passwordHash = AUTH_CREDENTIALS.get(username)
    # an unknown user costs one hash check too (against a hash nobody can match), so the answer's timing doesn't
    # tell which names exist
    if not (check_password_hash(passwordHash or _UNKNOWN_USER_HASH, request.form.get("password", "")) and passwordHash is not None):
        _loginFailures.failed(address)
        return _loginPage("Wrong username or password.", username, 401)
    _loginFailures.succeeded(address)
    response = redirect("/")
    response.set_cookie(login.COOKIE_NAME, login.makeCookie(username, passwordHash), max_age=login.COOKIE_MAX_AGE,
                        httponly=True, samesite="Lax", secure=request.is_secure)
    return response

@server.route('/logout', methods=['POST'])
def logout():
    response = redirect("/login")
    response.delete_cookie(login.COOKIE_NAME, httponly=True, samesite="Lax", secure=request.is_secure)
    return response

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

# what the 3D filters look for, in the alias "t" of media_versions / media_audio_tracks: a second view (MVC), and
# object-based audio -- Dolby Atmos and DTS:X (whose "X" feature is also on IMAX Enhanced tracks)
_VIDEO_3D_CONDITION = "t.multiview_count > 1"
_AUDIO_3D_CONDITION = ("(t.format_commercial LIKE '%Atmos%' OR t.format_commercial LIKE '%DTS:X%'"
                       " OR instr(' ' || COALESCE(t.format_additional_features, '') || ' ', ' X ') > 0)")

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
                 person_id=None, person_roles=(),
                 video_3d=False, not_video_3d=False, audio_3d=False, not_audio_3d=False):
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

    # text search -- each word must match either the original or the primary (localized) title, regardless of case and
    # accents (fold, see _connect): "meduses" finds "L'année des méduses"
    if search_query:
        words = search_query.split()
        for word in words:
            sql += " AND (fold(original_title) LIKE ? OR fold(primary_title) LIKE ?)"
            params.append(f"%{_fold(word)}%")
            params.append(f"%{_fold(word)}%")

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

    # 3D video / 3D audio -- titles with a 3D version / an object-based audio track in any of their versions, a series
    # through its episodes; each also as its NOT (right-click in the UI): none of them has one
    for table, condition, wanted, unwanted in (("media_versions", _VIDEO_3D_CONDITION, video_3d, not_video_3d),
                                               ("media_audio_tracks", _AUDIO_3D_CONDITION, audio_3d, not_audio_3d)):
        if wanted or unwanted:
            sql += (" AND m.imdb_id " + ("IN" if wanted else "NOT IN")
                    + " (SELECT t.imdb_id FROM " + table + " t WHERE " + condition
                    + " UNION SELECT e.series_imdb_id FROM " + table + " t JOIN media e ON e.imdb_id = t.imdb_id"
                      " WHERE e.series_imdb_id IS NOT NULL AND " + condition + ")")

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
                            curtain_enabled=serverconfig.CURTAIN_ANIMATION_ENABLED, curtain_style=serverconfig.CURTAIN_STYLE,
                            title=serverconfig.SERVER_TITLE, login_user=_loggedInUser())

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
    video_3d = args.get('video_3d', '0') == '1'
    not_video_3d = args.get('not_video_3d', '0') == '1'
    audio_3d = args.get('audio_3d', '0') == '1'
    not_audio_3d = args.get('not_audio_3d', '0') == '1'
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
            person_roles,
            video_3d,
            not_video_3d,
            audio_3d,
            not_audio_3d
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

# letters that unicodedata can't take apart into a base letter and an accent, as they fold to plain letters
_FOLD_EXTRA = str.maketrans({"ø": "o", "ł": "l", "đ": "d", "ð": "d", "æ": "ae", "œ": "oe", "þ": "th"})

@functools.lru_cache(maxsize=None) # a search folds every name in the DB, over and over: remember them (about 70,000, a few MB)
def _fold(text):
    """text as it is compared in searches: lower case and without accents ("L'année des méduses" ->
    "l'annee des meduses"), so that "meduses" finds it. None stays None."""
    if text is None:
        return None
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).translate(_FOLD_EXTRA)

def _connect():
    """A connection to the DB with credit_kind(role_id, details, is_series) and fold(text) available to SQL (the
    person filter and the accent-insensitive name searches)."""
    conn = sqlite3.connect(serverconfig.DB_PATH)
    conn.create_function("credit_kind", 3, lambda role_id, details, isSeries: _creditKind(role_id, details, bool(isSeries)), deterministic=True)
    conn.create_function("fold", 1, _fold, deterministic=True)
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

# ---- versions: the files a title is available as (one per row of media_versions), for the detail view of movies

_SOURCE_LABELS = {"dvd": "DVD", "br": "Blu-ray", "uhd": "UHD Blu-ray", "web-dl": "WEB-DL", "webrip": "WEBRip", "tv": "TV",
                  "vhs": "VHS", "hifivhs": "Hi-Fi VHS", "ld": "LaserDisc", "di": "DI", "kscape": "Kaleidescape", "hddvd": "HD DVD"}
# the discs blu-ray.com knows, by their id in media_version_sources.disc_id: Blu-rays and UHD Blu-rays have a page under
# /movies/, DVDs one under /dvd/ (the /movies/ address doesn't work for them)
_BLURAY_COM_URLS = {"br": "https://www.blu-ray.com/movies/movies.php?id=%d",
                    "uhd": "https://www.blu-ray.com/movies/movies.php?id=%d",
                    "dvd": "https://www.blu-ray.com/dvd/link-to-DVD/%d/"}
# how a source's role in a version reads in front of it (a version made from one source has role "main": no prefix)
_SOURCE_ROLE_LABELS = {"main": "", "video": "Video", "audio": "Audio", "video_base": "Base video", "video_dynhdr": "Dynamic HDR",
                       "video_base_audio": "Base video & audio"}
_SOURCE_ROLE_ORDER = {"main": 0, "video": 1, "video_base": 2, "video_base_audio": 2, "video_dynhdr": 3, "audio": 4}
_HDR_LABELS = {"Dolby Vision": "Dolby Vision", "SMPTE ST 2086": "HDR10", "SMPTE ST 2094 App 4": "HDR10+"}

def _runtimeText(seconds):
    minutes = round(seconds / 60)
    return str(minutes // 60) + "h " + "%02d" % (minutes % 60) + "m" if minutes >= 60 else str(minutes) + "m"

def _resolutionLabel(width, height, scanType):
    """"4K", "1080p", "720p", or for standard definition the nominal lines ("480p", "576i"); the width decides for
    HD and up, since letterboxed encodes are cropped in height (3840x1600 is 4K, 1920x1040 is 1080p)."""
    if width >= 7000:
        return "8K"
    if width >= 3000:
        return "4K"
    if width >= 1800:
        return "1080p"
    if width >= 1200:
        return "720p"
    lines = 480 if height <= 480 else 576 if height <= 576 else height
    return str(lines) + ("i" if scanType == "Interlaced" else "p")

def _hdrLabel(hdrFormat, transfer):
    """"Dolby Vision", "HDR10", "HDR10+" or a combination ("Dolby Vision + HDR10") from MediaInfo's HDR format
    string ("Dolby Vision / SMPTE ST 2086"); None for SDR. An unknown part is kept as MediaInfo spells it.
    Without an HDR format a PQ transfer curve still means HDR -- PQ10, HDR10 without its static metadata (no mastering
    display, MaxCLL, MaxFALL): MediaInfo leaves the HDR format empty then, but no SDR file is ever PQ -- shown as "HDR"."""
    if not hdrFormat:
        return "HDR" if transfer == "PQ" else None
    return " + ".join(_HDR_LABELS.get(part.strip(), part.strip()) for part in hdrFormat.split("/"))

def _aspectRatios(width, height, aspect, pixelAspect, croppings):
    """The aspect ratios of the picture itself, as "2.40:1" labels -- not the frame's: a 1920x1080 file with black bars
    above and below holds a 2.40:1 picture. One label per cropping the version has (its black bars as top, bottom,
    left, right pixel counts); a version with several has a variable aspect ratio (IMAX-expansion scenes and the
    like), and its ratios come out in the order they are stored in. Without any cropping the frame's own ratio."""
    pixel = pixelAspect or (aspect / (width / height) if aspect else 1.0)
    labels = []
    for top, bottom, left, right in croppings or [(0, 0, 0, 0)]:
        pictureWidth, pictureHeight = width - left - right, height - top - bottom
        if pictureWidth <= 0 or pictureHeight <= 0:
            continue
        label = "%.2f:1" % (pictureWidth / pictureHeight * pixel)
        if label not in labels:
            labels.append(label)
    return labels

def _channelsLabel(channels, layout):
    if channels is None:
        return None
    if layout and "LFE" in layout.split():
        return str(channels - 1) + ".1"
    return str(channels) + ".0"

_TRIVIAL_TRACK_TITLE = re.compile(r"(mono|stereo|surround [\d.]+)|.*\b\d\.\d", re.IGNORECASE)
# A track title written by a disc-analysis tool, describing the stream: "DTS-HD Master Audio / 5.1 / 48 kHz / 3408 kbps /
# 24-bit", "FLAC Audio", "DTS-HD.MA5.1". Its parts are told apart by their " / " (a codec name like "TrueHD/Atmos" has
# none around its slash).
_STREAM_PART = re.compile(r"\d\.\d|\d+(\.\d+)?\s*kHz|\d+\s*kbps|\d+\s*-?\s*bits?"
                          r"|(FLAC|DTS|Dolby|PCM|LPCM|AAC|AC-?3|E-?AC-?3|TrueHD|MLP|MP3|Opus|Vorbis)[\w .\-/+]*Audio"
                          r"|(DTS|DD|DDP|TrueHD|Atmos|FLAC|PCM|LPCM|AAC|AC-?3|MA)[\w.\-+ ]*\d\.\d", re.IGNORECASE)

def _describesStream(title):
    """True if any part of the title is a stream description -- such a title is boilerplate as a whole, whatever else it
    says ("Original Stereo / FLAC Audio / 2.0 / 48 kHz / 530 kbps / 16-bit")."""
    return any(_STREAM_PART.fullmatch(part.strip()) for part in re.split(r"\s+/\s+|^/\s*", title.strip()))

# how a track title spells a source type, once lower-cased and stripped of everything but letters and digits
_SOURCE_TYPE_SPELLINGS = {"br": "br", "bd": "br", "bluray": "br", "3dbluray": "br", "uhd": "uhd", "uhdbd": "uhd", "uhdbluray": "uhd",
                          "dvd": "dvd", "web": "web-dl", "webdl": "web-dl", "webrip": "webrip", "ld": "ld", "laserdisc": "ld",
                          "tv": "tv", "vhs": "vhs", "hifivhs": "hifivhs", "hddvd": "hddvd"}
# when a track names only a disc type ("from dvd"), the disc of that type in the version's own source description is meant;
# if there are several, the one in the most fitting role
_DISC_ROLE_PREFERENCE = ("audio", "main", "video", "video_base", "video_dynhdr")

def _splitTrackSource(title):
    """(label, source text) of an audio track's title that names where the track comes from -- "from DVD", "from br-164692",
    "src-br-300821", "70mm Soundtrack (from UHD)" -- else (title, None). The label is what is left besides the source."""
    title = title.strip()
    match = re.fullmatch(r"src-(.+)", title, re.IGNORECASE) or re.fullmatch(r"from\s+(.+)", title, re.IGNORECASE)
    if match:
        return "", match.group(1).strip()
    match = re.fullmatch(r"(.*?)\s*\(from\s+(.+)\)", title, re.IGNORECASE)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return title, None

def _audioSource(sourceText, generalSources, providers):
    """A track's source, as {"text": "from DVD", "url": ...}: a disc (Blu-ray, UHD Blu-ray, DVD) links to blu-ray.com, by the
    disc id the track names ("br-164692") or, when it names only the type ("from dvd"), by that of the disc of this type
    in the version's general source description (generalSources: its (role, type, disc id, provider, ...) tuples). Spellings
    are read leniently ("BR", "Blu-ray", "UHD BD", "3D-Blu-ray", "WEB"); a provider abbreviation ("AMZN") reads as its
    name, and a web source named without a provider ("from WEB") gets that of the version's own web source; anything
    else stays as it is written, without a link."""
    base, remark = sourceText, ""
    match = re.fullmatch(r"(.*?)\s*(\(.*\))", sourceText)
    if match:
        base, remark = match.group(1), match.group(2)

    sourceType, discId, text = None, None, None
    idMatch = re.fullmatch(r"(br|uhd|dvd)-(\d+)", base, re.IGNORECASE)
    webMatch = re.fullmatch(r"(web-dl|webrip)(?:-(\w+))?", base, re.IGNORECASE)
    if idMatch:
        sourceType, discId = idMatch.group(1).lower(), int(idMatch.group(2))
    elif webMatch: # "WEB-DL-NF": the web-dl, from this provider
        sourceType = webMatch.group(1).lower()
        provider = providers.get((webMatch.group(2) or "").upper())
        text = _SOURCE_LABELS[sourceType] + (" \u00B7 " + provider if provider else "")
    else:
        sourceType = _SOURCE_TYPE_SPELLINGS.get(re.sub(r"[^a-z0-9]", "", base.lower()))
        if sourceType is None and base.upper() in providers: # "AMZN" -> "Amazon"
            text = providers[base.upper()]

    if sourceType in ("web-dl", "webrip") and (text is None or "\u00B7" not in text):
        # a web source named without its provider ("from WEB"): the provider of the version's own web source of this type
        providersByRole = {role: provider for role, type_, disc, provider, *_ in generalSources if type_ == sourceType and provider}
        provider = next((providersByRole[role] for role in _DISC_ROLE_PREFERENCE if role in providersByRole), None)
        if provider:
            text = _SOURCE_LABELS[sourceType] + " \u00B7 " + provider

    # whether the track says more than a plain source type, disc or provider (which the version's general source description
    # says as well): free text, or a remark on a type ("LD (Dolby Stereo)")
    informative = (sourceType is None and text is None) or bool(remark)

    url = None
    if sourceType in _BLURAY_COM_URLS:
        text = _SOURCE_LABELS[sourceType]
        if discId is None:
            candidates = {role: disc for role, type_, disc, *_ in generalSources if type_ == sourceType and disc is not None}
            discId = next((candidates[role] for role in _DISC_ROLE_PREFERENCE if role in candidates), None)
        if discId is not None:
            url = _BLURAY_COM_URLS[sourceType] % discId
    elif text is None:
        text = sourceText # as written
    elif remark:
        text += " " + remark
    return {"text": "from " + text, "url": url, "informative": informative}

def _trackNote(title, language):
    """A track's own title when it says something beyond the language and the channels ("Commentary", "from DVD",
    "SDH"); a leading language name is dropped ("English Complete" -> "Complete"). None if nothing is left."""
    if not title:
        return None
    remainder = re.sub("^" + re.escape(language) + r"\b[\s:-]*", "", title.strip(), flags=re.IGNORECASE).strip()
    if _describesStream(remainder):
        return None
    if remainder[:1] + remainder[-1:] in ("()", "[]", "{}") and not any(ch in remainder[1:-1] for ch in "()[]{}"): # "(Forced)" -> "Forced"
        remainder = remainder[1:-1].strip()
    if not remainder or _TRIVIAL_TRACK_TITLE.fullmatch(remainder):
        return None
    return "forced" if remainder.lower() == "forced" else remainder

# words that qualify subtitles in a video track's title ("hardcoded English subtitles") rather than name their language
_SUBTITLE_QUALIFIERS = {"hardcoded", "hard-coded", "burned-in", "burnt-in", "burned", "burnt", "forced", "english-language"}

def _hardcodedSubtitleLanguage(cursor, videoTitle, videoLanguage):
    """The language of subtitles burned into a version's picture, from the video track's title ("hardcoded English
    subtitles", "forced English subtitles" -- on the video track they can only be burned in); None when the title doesn't
    speak of subtitles, or says there are none. A title that names no language ("hardcoded subtitles") falls back to
    the video track's own."""
    if not videoTitle or not re.search(r"\bsubtitles?\b", videoTitle, re.IGNORECASE):
        return None
    match = re.search(r"([^\W\d_][\w'-]*)\s+subtitles?\b", videoTitle, re.IGNORECASE)
    word = match.group(1) if match else None
    if word and word.lower() in ("no", "without", "non"):
        return None
    if not word or word.lower() in _SUBTITLE_QUALIFIERS:
        return videoLanguage or "Subtitles"
    cursor.execute("SELECT name FROM iso_language_enum WHERE name = ? COLLATE NOCASE LIMIT 1", (word,))
    row = cursor.fetchone()
    return row[0] if row else word.capitalize()

def _versions(cursor, imdb_id, internal=False):
    """The versions of a title as a list of dicts ready to display, sorted by version name (unnamed first):
    {name, runtime, modified, sources: [{text, url}], video: [{text, kind}], audio: [{text, note}], subtitles: [{text, note}]}.
    sources link to blu-ray.com for discs (dvd/br/uhd); a source that is a fan restoration out of several (a role with
    several fanres sources) is one {label, title, parts: [{text, url}]} instead. Text strings are final, built here so there
    is one place that decides how a version reads. internal=True keeps the keys that start with "_" (_seconds, the runtime,
    and _facets, the video values the chips are made of), which a season's aggregation needs; otherwise they are dropped."""
    cursor.execute("SELECT filename, top, bottom, left, right FROM cropping WHERE imdb_id = ? ORDER BY filename, ordering", (imdb_id,))
    croppings = collections.defaultdict(list)
    for filename, top, bottom, left, right in cursor.fetchall():
        croppings[filename].append((top, bottom, left, right))

    cursor.execute("""
        SELECT filename, version, mtime, duration, format, hdr_format, transfer_characteristics, bitrate, width, height,
               display_aspect_ratio, pixel_aspect_ratio, frame_rate, scan_type, multiview_count, title, language
        FROM media_versions WHERE imdb_id = ?
    """, (imdb_id,))
    versions = {}
    videoTracks = {} # filename -> (the video track's title, its language's name): subtitles burned in are noted there
    for (filename, name, mtime, duration, codec, hdrFormat, transfer, bitrate, width, height, aspect, pixelAspect, frameRate,
         scanType, multiviewCount, videoTitle, videoLanguage) in cursor.fetchall():
        videoTracks[filename] = (videoTitle, videoLanguage)
        resolution = _resolutionLabel(width, height, scanType)
        video = [{"text": resolution, "kind": "video"}]
        stereoscopic = bool(multiviewCount and multiviewCount > 1) # one view per eye
        if stereoscopic:
            video.append({"text": "3D", "kind": "3d"})
        codecText = None
        if codec:
            # MediaInfo calls a Blu-ray 3D file's video AVC (its profile says "Stereo High"), but two views in AVC are MVC
            codecText = "MVC" if stereoscopic and codec == "AVC" else {"MPEG Video": "MPEG-2", "MPEG-4 Visual": "MPEG-4"}.get(codec, codec)
            video.append({"text": codecText, "kind": "video"})
        hdr = _hdrLabel(hdrFormat, transfer)
        if hdr:
            video.append({"text": hdr, "kind": "hdr"})
        ratios = _aspectRatios(width, height, aspect, pixelAspect, croppings.get(filename))
        if len(ratios) == 1:
            video.append({"text": ratios[0], "kind": "video"})
        elif ratios: # a variable aspect ratio
            video.append({"text": "Variable " + " / ".join(ratios), "kind": "video"})
        if bitrate:
            mbps = bitrate / 1000000
            video.append({"text": ("%.0f" if mbps >= 10 else "%.1f") % mbps + " Mbps", "kind": "video"})
        fpsText = None
        if frameRate and abs(frameRate - 24) > 0.4: # only an unusual rate is worth saying (23.976 and the like read as 24)
            fpsText = ("%.3f" % frameRate).rstrip("0").rstrip(".") + " fps"
            video.append({"text": fpsText, "kind": "video"})
        versions[filename] = {"name": name, "runtime": _runtimeText(duration),
                              "modified": datetime.date.fromtimestamp(mtime).isoformat() if mtime else None, # the file's modification date
                              "sources": [], "video": video, "audio": [], "subtitles": [], "_filename": filename,
                              "_seconds": duration,
                              "_facets": {"resolution": resolution, "stereo": stereoscopic, "codec": codecText, "hdr": hdr, "ratios": ratios,
                                          "bitrate": bitrate / 1000000 if bitrate else None, "fps": fpsText}}

    # sources: one chip per source, prefixed with its role when a version is put together from several; a video
    # and an audio source that are one and the same (the same disc) read as one, and so do a hybrid's base video and
    # its audio when it names no audio source of its own (the audio then comes from the base video's source). The several
    # sources of a role that a fan restoration blends are one chip, with a part (and its own link) per source.
    cursor.execute("""
        SELECT ms.filename, r.role_name, st.source_type_name, ms.disc_id, w.full_name, ms.base_layer, ms.downmixed, ms.core,
               ms.disc_corrected, ms.fanres
        FROM media_version_sources ms
        JOIN source_role_enum r ON ms.role_id = r.role_id
        JOIN source_type_enum st ON ms.source_type_id = st.source_type_id
        LEFT JOIN source_web_provider_enum w ON ms.web_provider_id = w.web_provider_id
        WHERE ms.imdb_id = ?
        ORDER BY ms.filename, ms.seq
    """, (imdb_id,))
    sourcesByFile = collections.defaultdict(list)
    for filename, role, sourceType, discId, provider, baseLayer, downmixed, core, corrected, fanres in cursor.fetchall():
        sourcesByFile[filename].append((role, sourceType, discId, provider, baseLayer, downmixed, core, corrected, fanres))
    for filename, sources in sourcesByFile.items():
        if filename not in versions:
            continue
        sources.sort(key=lambda source: _SOURCE_ROLE_ORDER.get(source[0], 9))
        # the same source: the same disc (a corrected pressing of it is another one) or web provider
        keyOf = lambda source: source[1:4] + source[7:8]
        def merged(role, first, second):
            """first and second, one source in the end under role: what is said of either of them (base layer, downmixed,
            core) stays said"""
            return (role,) + first[1:4] + tuple(a or b for a, b in zip(first[4:], second[4:]))
        if len(sources) == 2 and {sources[0][0], sources[1][0]} == {"video", "audio"} and keyOf(sources[0]) == keyOf(sources[1]):
            sources = [merged("main", sources[0], sources[1])]
        byRole = {source[0]: source for source in sources}
        roleCounts = collections.Counter(source[0] for source in sources)
        base, audio = byRole.get("video_base"), byRole.get("audio")
        if (base is not None and "video_dynhdr" in byRole and roleCounts["video_base"] == 1 and roleCounts["audio"] <= 1
                and (audio is None or keyOf(audio) == keyOf(base))):
            # a hybrid (base video plus another source's dynamic HDR) has its audio from the base video's source, unless it
            # names an audio source of its own that differs
            both = merged("video_base_audio", base, audio or base)
            sources = [both if source is base else source for source in sources if source is not audio]
        chips, groups = [], {} # (role, chip) in display order; a role's fanres group by role
        fanresCounts = collections.Counter(source[0] for source in sources if source[8])
        for role, sourceType, discId, provider, baseLayer, downmixed, core, corrected, fanres in sources:
            grouped = fanres and fanresCounts[role] > 1 # a fan restoration of one source only is a plain chip that says so
            text = _SOURCE_LABELS.get(sourceType, sourceType) + (" \u00B7 " + provider if provider else "")
            qualifiers = [word for word, flag in (("corrected disc", corrected), ("base layer", baseLayer), ("downmixed", downmixed),
                                                  ("core", core), ("fan restoration", fanres and not grouped)) if flag]
            if qualifiers:
                text += " (" + ", ".join(qualifiers) + ")"
            part = {"text": text, "url": _BLURAY_COM_URLS[sourceType] % discId if sourceType in _BLURAY_COM_URLS and discId is not None else None}
            if not grouped:
                chips.append((role, part))
            elif role in groups:
                groups[role]["parts"].append(part)
            else:
                groups[role] = {"title": "fan restoration: put together from several sources", "parts": [part]}
                chips.append((role, groups[role]))
        for role, chip in chips:
            prefix = _SOURCE_ROLE_LABELS.get(role, role)
            if "parts" in chip:
                chip["label"] = prefix + " \u00B7 combined" if prefix else "Combined"
            elif prefix and len(chips) > 1:
                chip["text"] = prefix + ": " + chip["text"]
            versions[filename]["sources"].append(chip)

    cursor.execute("""
        SELECT a.filename, a.format, a.format_commercial, a.channels, a.channel_layout, e.name, a.title
        FROM media_audio_tracks a JOIN iso_language_enum e ON a.language = e.iso639_3
        WHERE a.imdb_id = ? ORDER BY a.filename, a.track_id
    """, (imdb_id,))
    audioTracks = [track for track in cursor.fetchall() if track[0] in versions]
    audioCounts = collections.Counter(track[0] for track in audioTracks)
    cursor.execute("SELECT abbreviation, full_name FROM source_web_provider_enum")
    providers = {abbreviation.upper(): fullName for abbreviation, fullName in cursor.fetchall()}
    for filename, audioFormat, commercial, channels, layout, language, title in audioTracks:
        name = (commercial or audioFormat).replace(" with Dolby Atmos", " Atmos").replace(" with DTS:X", " DTS:X")
        channelsText = _channelsLabel(channels, layout)
        # where a track comes from is said for a file with several tracks; with a single one, the version's general source
        # description is that source, so only what the title says beyond it (a LaserDisc edition, say) is shown. A title
        # that names a source but is also a label keeps the label as its note.
        label, sourceText = _splitTrackSource(title) if title else (title, None)
        source = _audioSource(sourceText, sourcesByFile.get(filename, []), providers) if sourceText else None
        if source:
            informative = source.pop("informative")
            if audioCounts[filename] == 1 and not informative:
                source = None
        versions[filename]["audio"].append({"text": name + (" " + channelsText if channelsText else "") + " \u00B7 " + language,
                                            "note": _trackNote(label if sourceText else title, language), "source": source})

    cursor.execute("""
        SELECT s.filename, e.name, s.title, s.forced_track
        FROM media_subtitle_tracks s JOIN iso_language_enum e ON s.language = e.iso639_3
        WHERE s.imdb_id = ? ORDER BY s.filename, s.track_id
    """, (imdb_id,))
    for filename, language, title, forced in cursor.fetchall():
        if filename not in versions:
            continue
        note = _trackNote(title, language)
        if forced and "forced" not in (note or "").lower():
            note = (note + ", " if note else "") + "forced"
        versions[filename]["subtitles"].append({"text": language, "note": note})

    for filename, (videoTitle, videoLanguage) in videoTracks.items():
        languageName = None
        if videoLanguage:
            cursor.execute("SELECT name FROM iso_language_enum WHERE iso639_3 = ?", (videoLanguage,))
            row = cursor.fetchone()
            languageName = row[0] if row else None
        hardcoded = _hardcodedSubtitleLanguage(cursor, videoTitle, languageName)
        if hardcoded and filename in versions:
            versions[filename]["subtitles"].append({"text": hardcoded, "note": "hardcoded"})

    ordered = sorted(versions.values(), key=lambda v: (v["name"] is not None, (v["name"] or "").casefold(), v["_filename"].casefold()))
    if not internal:
        for version in ordered:
            for key in [key for key in version if key.startswith("_")]:
                del version[key] # the file name and the like are internal: they only tie the tables together
    return ordered

# ---- seasons: the technical data of a season's episodes, aggregated, for the card a season tile opens

# a short extra file an episode comes with (a recap, a title sequence), not a version of the episode: left out of the card
_IGNORED_EPISODE_VERSION = re.compile(r"Intro\d*", re.IGNORECASE)

def _isForcedSubtitle(note):
    """Whether a subtitle track is a forced one, by its note: the forced flag (which _versions has put in the note), the
    word "forced", "foreign" (subtitles for the foreign-language parts only), or "for English", "for Foreign" and the like
    -- but not "for English audio", which is a full track that goes with that audio."""
    if not note:
        return False
    lowered = note.lower()
    return "forced" in lowered or "foreign" in lowered or (lowered.startswith("for ") and not lowered.endswith("audio"))

def _coverage(episodes):
    """The episodes as text, "E1, E4, E8, E9": a run of three or more consecutive numbers is written "E5\u2013E7", and a
    missing number always breaks a run. episodes is [(number, title)] in order; one without a number goes by its title."""
    episodes = list(dict.fromkeys(episodes))
    parts, i = [], 0
    while i < len(episodes):
        number, title = episodes[i]
        if number is None:
            parts.append(title)
            i += 1
            continue
        j = i
        while j + 1 < len(episodes) and episodes[j + 1][0] is not None and episodes[j + 1][0] == episodes[j][0] + 1:
            j += 1
        if j - i >= 2:
            parts.append("E%d\u2013E%d" % (number, episodes[j][0]))
        else:
            parts.extend("E%d" % episodes[k][0] for k in range(i, j + 1))
        i = j + 1
    return ", ".join(parts)

def _runtimeRange(shortest, longest):
    low, high = round(shortest / 60), round(longest / 60)
    if low == high:
        return _runtimeText(shortest)
    if high < 60:
        return "%d\u2013%dm" % (low, high)
    return _runtimeText(shortest) + " \u2013 " + _runtimeText(longest)

def _sourceKey(source):
    if "parts" in source:
        return ("group", source["label"], tuple((part["text"], part["url"]) for part in source["parts"]))
    return ("plain", source["text"], source["url"])

def _sourceParts(sources):
    """The sources as the pieces of one line of text, [{text, url}], so that the discs in it stay links: "Video: UHD
    Blu-ray, Audio: Blu-ray", a fan restoration "Combined: Blu-ray + DVD"."""
    parts = []
    for source in sources:
        if parts:
            parts.append({"text": ", ", "url": None})
        if "parts" in source:
            parts.append({"text": source["label"] + ": ", "url": None})
            for i, part in enumerate(source["parts"]):
                if i:
                    parts.append({"text": " + ", "url": None})
                parts.append({"text": part["text"], "url": part["url"]})
        else:
            parts.append({"text": source["text"], "url": source["url"]})
    return parts or [{"text": "no source", "url": None}]

def _seasonBlock(name, members):
    """The episodes of a season that have a version of this name (members: [((number, title), version as _versions gives it
    with internal=True)]) as one card: what most of them have is shown as it is, what only some have as a note naming those
    episodes. The bitrate is always a range, the runtime a range and a total; forced subtitle tracks are the union of all
    episodes' (one lacking a forced track is not worth a note), the other tracks follow the most common set."""
    episodes = [member[0] for member in members]
    versions = [member[1] for member in members]
    facets = [version["_facets"] for version in versions]

    def commonest(values):
        return collections.Counter(values).most_common(1)[0][0]

    def notes(values, common, show):
        """one note per differing value, naming the episodes that have it: ["E1, E4: 4K"]"""
        groups = {}
        for episode, value in zip(episodes, values):
            if value != common:
                groups.setdefault(value, []).append(episode)
        return [_coverage(group) + ": " + show(value) for value, group in groups.items()]

    # the chips: the common value of each facet, and a note for the episodes that differ
    differences, video = [], []
    resolutions = [facet["resolution"] for facet in facets]
    common = commonest(resolutions)
    video.append({"text": common, "kind": "video"})
    differences += notes(resolutions, common, lambda value: value)
    stereo = [facet["stereo"] for facet in facets]
    common = commonest(stereo)
    if common:
        video.append({"text": "3D", "kind": "3d"})
    differences += notes(stereo, common, lambda value: "3D" if value else "2D")
    codecs = [facet["codec"] for facet in facets]
    common = commonest(codecs)
    if common:
        video.append({"text": common, "kind": "video"})
    differences += notes(codecs, common, lambda value: value or "no codec")
    hdrs = [facet["hdr"] for facet in facets]
    common = commonest(hdrs)
    if common:
        video.append({"text": common, "kind": "hdr"})
    differences += notes(hdrs, common, lambda value: value or "SDR")

    # aspect ratios within 0.02 of each other are the same (1.99:1 and 2.00:1 are one picture shape)
    ratios = [tuple(float(ratio[:-2]) for ratio in facet["ratios"]) for facet in facets]
    close = lambda a, b: len(a) == len(b) and all(abs(x - y) <= 0.02 for x, y in zip(a, b))
    candidates = list(dict.fromkeys(ratios))
    commonRatios = max(candidates, key=lambda candidate: (sum(close(candidate, other) for other in ratios), ratios.count(candidate)))
    ratioLabel = lambda facet: facet["ratios"][0] if len(facet["ratios"]) == 1 else "Variable " + " / ".join(facet["ratios"]) if facet["ratios"] else None
    labels = [ratioLabel(facet) for facet in facets]
    common = labels[ratios.index(commonRatios)]
    if common:
        video.append({"text": common, "kind": "video"})
    groups = {}
    for episode, shape, label in zip(episodes, ratios, labels):
        if not close(commonRatios, shape):
            groups.setdefault(label, []).append(episode)
    differences += [_coverage(group) + ": " + (label or "no aspect ratio") for label, group in groups.items()]

    bitrates = [facet["bitrate"] for facet in facets if facet["bitrate"]]
    if bitrates:
        mbps = lambda value: ("%.0f" if value >= 10 else "%.1f") % value
        low, high = mbps(min(bitrates)), mbps(max(bitrates))
        video.append({"text": (low if low == high else low + "\u2013" + high) + " Mbps", "kind": "video"})
    rates = [facet["fps"] for facet in facets]
    common = commonest(rates)
    if common:
        video.append({"text": common, "kind": "video"})
    differences += notes(rates, common, lambda value: value or "24 fps")

    sourceKeys = [tuple(_sourceKey(source) for source in version["sources"]) for version in versions]
    common = commonest(sourceKeys)
    sources = versions[sourceKeys.index(common)]["sources"]
    # a differing source is not a text like the other notes but {episodes, parts}: the discs in it stay links
    sourceGroups = {}
    for episode, key in zip(episodes, sourceKeys):
        if key != common:
            sourceGroups.setdefault(key, []).append(episode)
    differences += [{"episodes": _coverage(group), "parts": _sourceParts(versions[sourceKeys.index(key)]["sources"])}
                    for key, group in sourceGroups.items()]

    audioKeys = [tuple(track["text"] for track in version["audio"]) for version in versions]
    common = commonest(audioKeys)
    audio = versions[audioKeys.index(common)]["audio"]
    audioDifferences = notes(audioKeys, common, lambda value: " + ".join(value) or "no audio")

    tracksOf = lambda version: [(track["text"], track["note"]) for track in version["subtitles"]]
    plain = [collections.Counter(track for track in tracksOf(version) if not _isForcedSubtitle(track[1])) for version in versions]
    plainKeys = [tuple(sorted(counter.items(), key=repr)) for counter in plain]
    common = commonest(plainKeys)
    commonCounter = plain[plainKeys.index(common)]
    subtitleGroups = {}
    for episode, counter in zip(episodes, plain):
        if counter == commonCounter:
            continue
        label = lambda track: track[0] + (" (" + track[1] + ")" if track[1] else "")
        text = ", ".join(["no " + label(track) for track in (commonCounter - counter).elements()]
                         + ["+ " + label(track) for track in (counter - commonCounter).elements()])
        subtitleGroups.setdefault(text, []).append(episode)
    subtitleDifferences = [_coverage(group) + ": " + text for text, group in subtitleGroups.items()]
    forced = list(dict.fromkeys(track for version in versions for track in tracksOf(version) if _isForcedSubtitle(track[1])))
    representative = versions[plainKeys.index(common)]
    subtitles = [{"text": track["text"], "note": track["note"]} for track in representative["subtitles"] if not _isForcedSubtitle(track["note"])]
    subtitles += [{"text": text, "note": note} for text, note in forced]

    seconds = [version["_seconds"] for version in versions]
    if len(seconds) == 1:
        runtime = _runtimeText(seconds[0])
    else:
        runtime = _runtimeRange(min(seconds), max(seconds)) + " per episode \u00B7 " + _runtimeText(sum(seconds)) + " total"
    runtimeTitle = "\n".join(_coverage([episode]) + " " + _runtimeText(second) for episode, second in zip(episodes, seconds))

    return {"name": name, "episodes": _coverage(episodes), "sources": sources, "video": video, "differences": differences,
            "runtime": runtime, "runtimeTitle": runtimeTitle, "audio": audio, "audioDifferences": audioDifferences,
            "subtitles": subtitles, "subtitleDifferences": subtitleDifferences}

def _seasonCard(cursor, series_id, season):
    """What the card of a season tile shows: the owned episodes' versions grouped by version name (unnamed first, then
    alphabetical; the extras that _IGNORED_EPISODE_VERSION names are left out), each group aggregated by _seasonBlock, and
    the latest modification date of any episode file. None if the season has no owned episode. Everything is counted per
    episode: a file that holds several episodes (S01E01_S01E02.mkv) gives each of them its runtime divided by their number,
    so the totals count the file once."""
    cursor.execute("""
        SELECT imdb_id, episode_number, original_title FROM media
        WHERE series_imdb_id = ? AND season_number IS ? AND subdir IS NOT NULL
        ORDER BY episode_number IS NULL, episode_number, original_title
    """, (series_id, season))
    owned = cursor.fetchall()
    if not owned:
        return None
    cursor.execute("""
        SELECT v.filename, COUNT(DISTINCT v.imdb_id) FROM media_versions v JOIN media m ON m.imdb_id = v.imdb_id
        WHERE m.series_imdb_id = ? GROUP BY v.filename HAVING COUNT(DISTINCT v.imdb_id) > 1
    """, (series_id,))
    episodesInFile = dict(cursor.fetchall())
    byName = {}
    for imdbId, number, title in owned:
        for version in _versions(cursor, imdbId, internal=True):
            if _IGNORED_EPISODE_VERSION.fullmatch(version["name"] or ""):
                continue
            version["_seconds"] /= episodesInFile.get(version["_filename"], 1)
            byName.setdefault(version["name"], []).append(((number, title), version))
    cursor.execute("""
        SELECT MAX(v.mtime) FROM media_versions v JOIN media m ON m.imdb_id = v.imdb_id
        WHERE m.series_imdb_id = ? AND m.season_number IS ? AND m.subdir IS NOT NULL
    """, (series_id, season))
    latest = cursor.fetchone()[0]
    names = sorted(byName, key=lambda name: (name is not None, (name or "").casefold()))
    return {"season": season, "modified": datetime.date.fromtimestamp(latest).isoformat() if latest else None,
            "blocks": [_seasonBlock(name, byName[name]) for name in names]}

@server.route('/season/<int:series_id>/<season>')
def seasonCard(series_id, season):
    """The card of a season tile of a series' overlay (season "none": the episodes without a season number)."""
    try:
        seasonNumber = None if season == "none" else int(season)
    except ValueError:
        return jsonify({"error": "not found"}), 404
    try:
        conn = sqlite3.connect(serverconfig.DB_PATH)
        card = _seasonCard(conn.cursor(), series_id, seasonNumber)
        conn.close()
    except sqlite3.Error as e:
        return jsonify({"error": str(e)}), 503
    if card is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(card)

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

# ---- connections: the group of titles that are connected to a title, as the map of the detail view draws it

# how a stored connection reads as one edge (a, b, type): "a follows b", "a is a spin-off of b", "a is a remake of b",
# "a is a version of b" (the two version types have no direction). The flag says whether the stored row has to be turned
# around: a title that is "followed by" another is what that other one "follows".
_EDGE_TYPES = {"follows": ("follows", False), "followed_by": ("follows", True),
               "spin_off_from": ("spin_off_from", False), "spin_off": ("spin_off_from", True),
               "remake_of": ("remake_of", False), "remade_as": ("remake_of", True),
               "version_of": ("version_of", None), "alternate_language_version_of": ("alternate_language_version_of", None)}

def _episodeCodes(episodes):
    """Episodes as text, [(season, episode)] -> "S1E1, S1E5" ("S3E101\u2013105" for a run of three or more)."""
    bySeason = collections.OrderedDict()
    for season, episode in sorted(set(episodes), key=lambda x: (x[0] is None, x[0] or 0, x[1] is None, x[1] or 0)):
        bySeason.setdefault(season, []).append(episode)
    parts = []
    for season, numbers in bySeason.items():
        prefix = "" if season is None else "S%d" % season
        i = 0
        while i < len(numbers):
            j = i
            while numbers[i] is not None and j + 1 < len(numbers) and numbers[j + 1] is not None and numbers[j + 1] == numbers[j] + 1:
                j += 1
            if numbers[i] is None:
                parts.append(prefix + "E?")
            elif j - i >= 2:
                parts.append("%sE%d\u2013%d" % (prefix, numbers[i], numbers[j]))
            else:
                parts.extend("%sE%d" % (prefix, numbers[k]) for k in range(i, j + 1))
            i = j + 1
    return ", ".join(parts)

def _connectionGraph(cursor, imdb_id, isSeries):
    """Every title that can be reached from a title through connections, in either direction, and the connections between
    them: {start, nodes: [{id, kind, title, year, yearText, owned, imdbId, current, ...}], edges: [{a, b, type, assumed?}]};
    a series (or miniseries) also has "isSeries", "mini", "startYear" and "endYear" (null: no end year known);
    an edge reads "a follows b" (likewise "is a spin-off of", "is a remake of", "is a version of"). Empty when the title has
    no connections.
    An episode is a title of its own: nothing connects two episodes just because they are of one series. The page of a
    series starts from the series and all its owned episodes, each a box of its own ("current": the boxes of the title
    shown; the series itself is a box only if it has connections of its own). Episodes of one series that are connected to
    exactly the same titles in the same way share one node ("kind": "group"). Titles that are not in the library and all follow exactly the same titles of
    the library, or are all followed by exactly the same titles of it, are chained in release order, same-year titles side
    by side ("assumed": the connections between titles that are not in the library are never stored, so this is the best
    guess)."""
    cursor.execute("""
        SELECT mc.imdb_id, mc.foreign_imdb_id, ct.connection_type_name
        FROM media_connections mc JOIN connection_type_enum ct ON mc.connection_type_id = ct.connection_type_id
    """)
    rows = cursor.fetchall()
    ownedEpisodes = []
    if isSeries:
        cursor.execute("SELECT imdb_id FROM media WHERE series_imdb_id = ? AND subdir IS NOT NULL", (imdb_id,))
        ownedEpisodes = [row[0] for row in cursor.fetchall()]
    start = {imdb_id, *ownedEpisodes} # what the page shows, and where the search for connected titles starts

    neighbours = collections.defaultdict(list)
    for a, b, _ in rows:
        neighbours[a].append(b)
        neighbours[b].append(a)
    reached, stack = set(start), list(start)
    while stack:
        for other in neighbours.get(stack.pop(), ()):
            if other not in reached:
                reached.add(other)
                stack.append(other)
    meta = {}
    ids = sorted(reached)
    for i in range(0, len(ids), 500):
        batch = ids[i:i + 500]
        cursor.execute("""
            SELECT m.imdb_id, m.original_title, m.start_year, m.subdir IS NOT NULL, m.series_imdb_id, m.season_number,
                   m.episode_number, s.original_title, tt.title_type_name, m.end_year
            FROM media m LEFT JOIN media s ON m.series_imdb_id = s.imdb_id
                 JOIN title_type_enum tt ON m.title_type_id = tt.title_type_id
            WHERE m.imdb_id IN (""" + ",".join("?" for _ in batch) + ")", batch)
        for row in cursor.fetchall():
            meta[row[0]] = row

    # one edge per connection (both directions of a pair are the same edge)
    edges = {}
    for a, b, typeName in rows:
        if a not in reached or a == b:
            continue
        kind, flip = _EDGE_TYPES[typeName]
        if flip:
            a, b = b, a
        if flip is None and a > b:
            a, b = b, a
        edges.setdefault((a, b, kind), {"a": a, "b": b, "type": kind})
    if not edges:
        return {"start": imdb_id, "nodes": [], "edges": []}

    # episodes of one series with exactly the same connections become one node
    episodeOf = lambda i: meta[i][4] if i in meta else None
    signature = collections.defaultdict(set)
    for (a, b, kind) in edges:
        if episodeOf(a) is not None:
            signature[a].add((kind, True, b))
        if episodeOf(b) is not None:
            signature[b].add((kind, False, a))
    merged = collections.defaultdict(list)
    for episode, sig in signature.items():
        merged[(episodeOf(episode), frozenset(sig))].append(episode)
    groupOf = {}
    for (seriesId, _), episodes in merged.items():
        if len(episodes) > 1:
            groupId = "g%d" % min(episodes)
            for episode in episodes:
                groupOf[episode] = groupId
    if groupOf:
        remapped = {}
        for (a, b, kind), edge in edges.items():
            a2, b2 = groupOf.get(a, a), groupOf.get(b, b)
            if kind in ("version_of", "alternate_language_version_of") and str(a2) > str(b2):
                a2, b2 = b2, a2
            remapped.setdefault((a2, b2, kind), {"a": a2, "b": b2, "type": kind})
        edges = remapped

    # the nodes
    nodes = {}
    def episodeTitle(i):
        _, title, year, owned, seriesId, season, episode, seriesTitle, _, _ = meta[i]
        code = "" if season is None or episode is None else " S%dE%d" % (season, episode)
        return "%s%s \"%s\"" % (seriesTitle, code, title)
    members = collections.defaultdict(list)
    for episode, groupId in groupOf.items():
        members[groupId].append(episode)
    used = {x for (a, b, _) in edges for x in (a, b)}
    if not isSeries or imdb_id in used:
        used.add(imdb_id) # a series is a box only if it has connections of its own
    for node in used:
        if isinstance(node, str):
            eps = sorted(members[node], key=lambda i: (meta[i][5] is None, meta[i][5] or 0, meta[i][6] is None, meta[i][6] or 0, i))
            years = [meta[i][2] for i in eps if meta[i][2]]
            first = meta[eps[0]]
            ownedOnes = [i for i in eps if meta[i][3]]
            lead = meta[ownedOnes[0] if ownedOnes else eps[0]]
            nodes[node] = {"id": node, "kind": "group", "title": "%s \u00B7 %s" % (first[7], _episodeCodes([(meta[i][5], meta[i][6]) for i in eps])),
                           "year": min(years) if years else None,
                           "yearText": ("%d" % min(years) if min(years) == max(years) else "%d\u2013%d" % (min(years), max(years))) if years else "",
                           "owned": bool(ownedOnes), "imdbId": lead[0], "seriesId": first[4], "seriesTitle": first[7], "season": lead[5], "episode": lead[6]}
            continue
        _, title, year, owned, seriesId, season, episode, seriesTitle, typeName, endYear = meta[node]
        entry = {"id": node, "kind": "title" if seriesId is None else "episode", "title": title, "year": year,
                 "yearText": str(year) if year else "", "owned": bool(owned), "imdbId": node}
        if typeName in Media.seriesTitleTypes: # the years a series ran; no end year: still running, or not known
            entry.update({"isSeries": True, "mini": typeName == "tvMiniSeries", "startYear": year, "endYear": endYear})
        if seriesId is not None:
            entry.update({"title": episodeTitle(node), "seriesId": seriesId, "seriesTitle": seriesTitle, "season": season, "episode": episode})
        nodes[node] = entry
    for node, entry in nodes.items():
        entry["current"] = node in start or (isinstance(node, str) and any(i in start for i in members[node]))

    # titles that are not in the library and follow exactly the same titles of the library -- or are followed by exactly the
    # same titles of it --: a chain in release order
    follows = [(a, b) for (a, b, kind) in edges if kind == "follows"] # a follows b
    for pairs in (follows, [(b, a) for a, b in follows]):
        neighbours = collections.defaultdict(set)
        for node, other in pairs:
            neighbours[node].add(other)
        siblings = collections.defaultdict(list)
        for node, others in neighbours.items():
            if not nodes[node]["owned"] and all(nodes[o]["owned"] for o in others):
                siblings[frozenset(others)].append(node)
        for group in siblings.values():
            byYear = collections.defaultdict(list)
            for node in group:
                byYear[nodes[node]["year"] or 9999].append(node)
            years = sorted(byYear)
            for earlier, later in zip(years, years[1:]):
                for a in byYear[later]:
                    for b in byYear[earlier]:
                        edges.setdefault((a, b, "follows"), {"a": a, "b": b, "type": "follows", "assumed": True})

    out = []
    for edge in edges.values():
        item = {"a": edge["a"], "b": edge["b"], "type": edge["type"]}
        if edge.get("assumed"):
            item["assumed"] = True
        out.append(item)
    return {"start": imdb_id, "nodes": list(nodes.values()), "edges": out}

@server.route('/people')
def people():
    """Name search for the person filter: up to 8 people whose name contains every word of q (at least 2
    characters). Names in which every typed word starts a word (first or last name alike, a half-typed word
    counts: "nola" finds "Christopher Nolan") come before names that only contain the text inside a word
    ("Manola"); within each group the ones with the most library titles come first."""
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])
    words = [_fold(w) for w in q.split()] # case and accents don't matter, see _fold
    # a word starts after a space or a hyphen (the leading space makes the name's first word count too)
    startsWordSql = "(' ' || fold(p.name) LIKE ? OR fold(p.name) LIKE ?)"
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
            WHERE """ + " AND ".join("fold(p.name) LIKE ?" for _ in words) + """
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
    compiled from its episodes, see _seriesCredits), and the graph of connected titles ("graph", see
    _connectionGraph), each node flagged with whether the title is itself locally owned (=> the overlay can
    open it in place) or only referenced (=> links out to IMDb)."""
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

        # languages and production countries as IMDb lists them (the primary one first), by name
        cursor.execute("""
            SELECT e.name FROM media_languages ml JOIN iso_language_enum e ON ml.language_code = e.iso639_3
            WHERE ml.imdb_id = ? ORDER BY ml.ordering
        """, (imdb_id,))
        languages = [row[0] for row in cursor.fetchall()]
        cursor.execute("""
            SELECT e.name FROM media_countries mc JOIN iso_country_enum e ON mc.country_code = e.country_code
            WHERE mc.imdb_id = ? ORDER BY mc.ordering
        """, (imdb_id,))
        countries = [row[0] for row in cursor.fetchall()]

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
                    SELECT season_number, episode_number, original_title, imdb_id
                    FROM media
                    WHERE series_imdb_id = ? AND subdir IS NOT NULL
                    ORDER BY episode_number IS NULL, episode_number, original_title
                """, (imdb_id,))
                ownedBySeason = collections.defaultdict(list)
                for season, episode, title, episodeId in cursor.fetchall():
                    ownedBySeason[season].append({"number": episode, "title": title, "imdbId": episodeId})
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
        # the versions (files) of a movie -- series and episodes have none to show for now
        versions = [] if title_type_name in Media.seriesTitleTypes + Media.episodeTitleTypes else _versions(cursor, imdb_id)
        graph = _connectionGraph(cursor, imdb_id, title_type_name in Media.seriesTitleTypes)
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
        "languages": languages,
        "versions": versions,
        "countries": countries,
        "allEpisodesOwned": allEpisodesOwned,
        "seasons": seasons,
        "creators": credits["creators"],
        "sources": credits["source"],
        "directors": credits[1],
        "writers": credits[2],
        "actors": credits[3],
        "graph": graph,
    })

if __name__ == '__main__':
    server.run(host=serverconfig.SERVER_HOST, port=serverconfig.SERVER_PORT)