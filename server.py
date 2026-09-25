from flask import Flask, render_template, request, jsonify, send_from_directory
import sqlite3, os
import config
from imdbinterestid import parseInterestID
from media import Media

server = Flask(__name__)

def _readHiddenInterestIDs(path):
    """Reads config.HIDDEN_INTEREST_IDS_PATH: subgenres never shown/selectable in the UI, though
    still scraped and stored normally (e.g. "Tragedy" spoilers a movie's ending). One imdb interest
    id (e.g. in0000090) per line, blank lines ignored. Read once at server start -- restart the
    server to pick up changes. A missing file is treated as an empty list."""
    if not os.path.exists(path):
        return set()
    with open(path, "r") as f:
        return {parseInterestID(line.strip()) for line in f if line.strip()}

HIDDEN_INTEREST_IDS = _readHiddenInterestIDs(config.HIDDEN_INTEREST_IDS_PATH)

def _excludeHiddenInterests(column):
    """(sql, params) appending "AND <column> NOT IN (...)" for every hidden interest id -- empty when
    none are configured -- for any query that lists a title's interests to the UI (the list view's
    genre line, the detail overlay's chips), so a hidden interest never shows up anywhere, not just
    in the filter sidebar (see the interest-group loop in index())."""
    if not HIDDEN_INTEREST_IDS:
        return "", []
    hidden = sorted(HIDDEN_INTEREST_IDS)
    return " AND " + column + " NOT IN (" + ",".join("?" for _ in hidden) + ")", hidden

def queryMedia(search_query, sort_by, order,
                year_from, year_to,
                rating_from, rating_to,
                votes_from, votes_to,
                selected_interest_ids,
                selected_language_code,
                show_movies, show_series,
                limit, offset):
    # media types to include -- episodes never appear here (episodeTitleTypes is never added),
    # since they were never meant to have their own top-level browsing entry
    allowedTypeNames = []
    if show_movies:
        allowedTypeNames += Media.movieTitleTypes
    if show_series:
        allowedTypeNames += Media.seriesTitleTypes
    if not allowedTypeNames:
        return []

    conn = sqlite3.connect(config.DB_PATH)
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

    # filter genres/interests (selected_interest_ids may mix genre and subgenre ids)
    if selected_interest_ids:
        sql += " JOIN media_interests mi_filter ON m.imdb_id = mi_filter.imdb_id"

    sql += " WHERE m.subdir IS NOT NULL"

    sql += " AND tt.title_type_name IN (" + ",".join("?" for _ in allowedTypeNames) + ")"
    params.extend(allowedTypeNames)

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

    sql += " GROUP BY m.imdb_id"

    if selected_interest_ids:
        sql += f" HAVING COUNT(DISTINCT mi_filter.imdb_interest_id) = {len(selected_interest_ids)}"
    
    # sorting
    if sort_by == "rating":
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
    conn = sqlite3.connect(config.DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT imdb_interest_id, name, description
        FROM interest_enum
        WHERE parent_imdb_interest_id IS NULL AND imdb_interest_id > 0
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
        SELECT le.language_code, le.name, COUNT(*)
        FROM language_enum le
        JOIN media_languages ml ON ml.language_code = le.language_code AND ml.ordering = 1
        GROUP BY le.language_code
    """)
    languages = [(code, name) for code, name, _ in sorted(
        ((code, "Silent" if code == "zxx" else name, count) for code, name, count in cursor.fetchall()),
        key=lambda language: (-language[2], language[1]))]

    conn.close()
    return render_template('index.html', genres=genres, interestGroups=interestGroups, languages=languages,
                            curtain_enabled=config.CURTAIN_ANIMATION_ENABLED, curtain_style=config.CURTAIN_STYLE)

@server.route('/search')
def search():
    args = request.args
    selected_interest_ids = [int(x) for x in args.getlist('genres[]') + args.getlist('interests[]')]
    selected_language_code = args.get('language') or None
    show_movies = args.get('movies', '1') == '1'
    show_series = args.get('series', '0') == '1'

    page = int(args.get('page', 1))
    limit = 50
    offset = (page - 1) * limit

    # a plain sqlite3.Error here (most plausibly "database is locked", from a sync running
    # concurrently in another terminal -- see DBControl's default 5s busy timeout) is reported to
    # the client as a clean JSON error instead of Flask's default HTML 500 page, which search.js
    # can't parse as JSON and would otherwise fail on invisibly (see fetchResults's error handling)
    try:
        media = queryMedia(
            args.get('q', ''),
            args.get('sort', 'year'),
            args.get('order', 'desc'),
            args.get('year_from'),
            args.get('year_to'),
            args.get('rating_from'),
            args.get('rating_to'),
            args.get('votes_from'),
            args.get('votes_to'),
            selected_interest_ids,
            selected_language_code,
            show_movies,
            show_series,
            limit,
            offset
        )
    except sqlite3.Error as e:
        return jsonify({"error": str(e)}), 503
    return jsonify(media)

@server.route('/cover_small/<filename>')
def coverSmall(filename):
    return send_from_directory(config.COVERS_SMALL_DIR, filename)

@server.route('/cover/<filename>')
def coverFull(filename):
    return send_from_directory(config.COVERS_DIR, filename)

@server.route('/detail/<int:imdb_id>')
def detail(imdb_id):
    """Everything the title detail overlay shows, for one locally-owned movie/series: basics, plot
    summary, genres/subgenres, credits (only ever stored for movies and episodes, so a series has
    none), and connections to other titles, each flagged with whether the target is itself locally
    owned (=> the overlay can open it in place) or only referenced (=> links out to IMDb)."""
    try:
        conn = sqlite3.connect(config.DB_PATH)
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

        # genres (no parent) first, then subgenres, each alphabetical; hidden interests left out, same
        # as everywhere else the UI lists interests
        hiddenSql, hiddenParams = _excludeHiddenInterests("mi.imdb_interest_id")
        cursor.execute("""
            SELECT ie.name, ie.parent_imdb_interest_id IS NULL
            FROM media_interests mi
            JOIN interest_enum ie ON mi.imdb_interest_id = ie.imdb_interest_id
            WHERE mi.imdb_id = ?""" + hiddenSql + """
            ORDER BY (ie.parent_imdb_interest_id IS NOT NULL), ie.name
        """, [imdb_id] + hiddenParams)
        interests = [{"name": name, "isGenre": bool(isGenre)} for name, isGenre in cursor.fetchall()]

        cursor.execute("""
            SELECT c.role_id, p.name, p.birth_year, p.death_year, c.details
            FROM credits c
            JOIN people p ON c.person_id = p.imdb_id
            WHERE c.imdb_id = ?
            ORDER BY c.role_id, c.ordering
        """, (imdb_id,))
        credits = {1: [], 2: [], 3: []}
        for role_id, name, birth_year, death_year, details in cursor.fetchall():
            credits[role_id].append({"name": name, "birthYear": birth_year, "deathYear": death_year, "details": details})

        cursor.execute("""
            SELECT ct.connection_type_name, m2.imdb_id, m2.original_title, m2.start_year, m2.subdir IS NOT NULL
            FROM media_connections mc
            JOIN connection_type_enum ct ON mc.connection_type_id = ct.connection_type_id
            JOIN media m2 ON mc.foreign_imdb_id = m2.imdb_id
            WHERE mc.imdb_id = ?
            ORDER BY ct.connection_type_id, m2.start_year, m2.original_title
        """, (imdb_id,))
        connections = [{"type": type_name, "imdbId": foreign_id, "title": title, "year": year, "owned": bool(owned)}
                       for type_name, foreign_id, title, year, owned in cursor.fetchall()]
        conn.close()
    except sqlite3.Error as e:
        return jsonify({"error": str(e)}), 503

    return jsonify({
        "imdbId": imdb_id,
        "title": original_title,
        "primaryTitle": primary_title,
        "startYear": start_year,
        "endYear": end_year,
        "isSeries": title_type_name in Media.seriesTitleTypes,
        "rating": rating_mul10 / 10 if rating_mul10 else None,
        "votes": num_votes,
        "plotSummary": plot_summary,
        "interests": interests,
        "directors": credits[1],
        "writers": credits[2],
        "actors": credits[3],
        "connections": connections,
    })

if __name__ == '__main__':
    server.run(host=config.SERVER_HOST, port=config.SERVER_PORT)