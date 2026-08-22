from flask import Flask, render_template, request, jsonify, send_from_directory
import sqlite3
import config

server = Flask(__name__)

def query_media(search_query, sort_by, order,
                year_from, year_to,
                rating_from, rating_to,
                votes_from, votes_to,
                selected_interest_ids,
                selected_language_id,
                limit, offset):
    conn = sqlite3.connect(config.DB_PATH)
    cursor = conn.cursor()

    sql = """
    SELECT m.imdb_id, m.originalTitle, m.startYear, m.rating_mul10, m.numVotes,
    (
        SELECT GROUP_CONCAT(ie.name, ', ')
        FROM media_interests mi_show
        JOIN interest_enum ie ON mi_show.imdb_interest_id = ie.imdb_interest_id
        WHERE mi_show.imdb_id = m.imdb_id
        ORDER BY ie.name
    ) as tags
    FROM media m
    """
    params = []

    # filter genres/interests (selected_interest_ids may mix genre and subgenre ids)
    if selected_interest_ids:
        sql += " JOIN media_interests mi_filter ON m.imdb_id = mi_filter.imdb_id"

    sql += " WHERE m.subdir IS NOT NULL"
    
    # text search
    if search_query:
        words = search_query.split()
        for word in words:
            sql += " AND originalTitle LIKE ? COLLATE NOCASE"
            params.append(f"%{word}%")
    
    # filter years
    if year_from:
        sql += " AND startYear >= ?"
        params.append(year_from)
    if year_to:
        sql += " AND startYear <= ?"
        params.append(year_to)

    # filter ratings
    if rating_from:
        sql += " AND rating_mul10 >= ?"
        params.append(int(float(rating_from) * 10))
    if rating_to:
        sql += " AND rating_mul10 <= ?"
        params.append(int(float(rating_to) * 10))

    # filter num votes
    if votes_from:
        sql += " AND numVotes >= ?"
        params.append(votes_from)
    if votes_to:
        sql += " AND numVotes <= ?"
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
        column = "numVotes"
    elif sort_by == "year":
        column = "startYear"
    else:
        column = "originalTitle"
    
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
    return render_template('index.html', genres=genres, interestGroups=interestGroups, languages=languages)

@server.route('/search')
def search():
    args = request.args
    selected_interest_ids = [int(x) for x in args.getlist('genres[]') + args.getlist('interests[]')]
    selected_language_id = int(args.get('language')) if args.get('language') else None

    page = int(args.get('page', 1))
    limit = 50
    offset = (page - 1) * limit

    media = query_media(
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
        limit,
        offset
    )
    return jsonify(media)

@server.route('/cover_small/<filename>')
def cover_small(filename):
    return send_from_directory(config.COVERS_SMALL_DIR, filename)

if __name__ == '__main__':
    server.run(host=config.SERVER_HOST, port=config.SERVER_PORT)