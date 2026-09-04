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

def queryMedia(search_query, sort_by, order,
                year_from, year_to,
                rating_from, rating_to,
                votes_from, votes_to,
                selected_interest_ids,
                selected_language_id,
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

    sql = """
    SELECT m.imdb_id, m.original_title, m.start_year, m.end_year, m.rating_mul10, m.num_votes,
    (
        SELECT GROUP_CONCAT(ie.name, ', ')
        FROM media_interests mi_show
        JOIN interest_enum ie ON mi_show.imdb_interest_id = ie.imdb_interest_id
        WHERE mi_show.imdb_id = m.imdb_id
        ORDER BY ie.name
    ) as tags,
    (
        SELECT COUNT(*) FROM media me WHERE me.series_imdb_id = m.imdb_id
    ) as total_episodes,
    (
        SELECT COUNT(*) FROM media me WHERE me.series_imdb_id = m.imdb_id AND me.subdir IS NOT NULL
    ) as owned_episodes,
    CASE WHEN tt.title_type_name IN (""" + ",".join("?" for _ in Media.seriesTitleTypes) + """) THEN 1 ELSE 0 END as is_series
    FROM media m
    JOIN title_type_enum tt ON m.title_type_id = tt.title_type_id
    """
    params = list(Media.seriesTitleTypes)

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

    # filter language
    if selected_language_id is not None:
        sql += " AND m.language_id = ?"
        params.append(selected_language_id)

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
    else:
        column = "original_title"
    
    if order == "asc":
        direction = "ASC"
    else:
        direction = "DESC"
    
    sql += " ORDER BY COALESCE(" + column + ", 0) " + direction
    
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

    # English (id 0) first, since it's the default/most common; the rest alphabetically
    cursor.execute("""
        SELECT imdb_interest_id, name, description
        FROM language_enum
        ORDER BY CASE WHEN imdb_interest_id = 0 THEN 0 ELSE 1 END, name
    """)
    languages = cursor.fetchall()

    conn.close()
    return render_template('index.html', genres=genres, interestGroups=interestGroups, languages=languages,
                            curtain_enabled=config.CURTAIN_ANIMATION_ENABLED, curtain_style=config.CURTAIN_STYLE)

@server.route('/search')
def search():
    args = request.args
    selected_interest_ids = [int(x) for x in args.getlist('genres[]') + args.getlist('interests[]')]
    selected_language_id = int(args.get('language')) if args.get('language') else None
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
            selected_language_id,
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

if __name__ == '__main__':
    server.run(host=config.SERVER_HOST, port=config.SERVER_PORT)