from flask import Flask, render_template, request, jsonify, send_from_directory
import sqlite3

server = Flask(__name__)

def query_media(search_query, sort_by, order,
                year_from, year_to,
                rating_from, rating_to,
                votes_from, votes_to,
                selected_genres,
                limit, offset):
    conn = sqlite3.connect('myMovieDB.db')
    cursor = conn.cursor()
    
    sql = """
    SELECT m.imdb_id, m.originalTitle, m.startYear, m.rating_mul10, m.numVotes,
    (
        SELECT GROUP_CONCAT(ge.genre_name, ', ')
        FROM genres g_show
        JOIN genre_enum ge ON g_show.genre_id = ge.genre_id
        WHERE g_show.imdb_id = m.imdb_id
        ORDER BY ge.genre_name
    ) as tags
    FROM media m
    """
    params = []
    
    # filter genres
    if selected_genres:
        sql += " JOIN genres g_filter ON m.imdb_id = g_filter.imdb_id"

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
    
    # filter genres (AND)
    if selected_genres:
        placeholders = ",".join("?" for _ in selected_genres)
        sql += f" AND g_filter.genre_id IN ({placeholders})"
        params.extend(selected_genres)

    sql += " GROUP BY m.imdb_id"
    
    if selected_genres:
        sql += f" HAVING COUNT(DISTINCT g_filter.genre_id) = {len(selected_genres)}"
    
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
    
    sql += " ORDER BY COALESCE(" + column + ", 0) " + order
    
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
    conn = sqlite3.connect('myMovieDB.db')
    cursor = conn.cursor()

    cursor.execute("SELECT genre_id, genre_name FROM genre_enum ORDER BY genre_name")
    genres = cursor.fetchall()

    conn.close()
    return render_template('index.html', genres=genres)

@server.route('/search')
def search():
    args = request.args
    selected_genres = args.getlist('genres[]')
    
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
        selected_genres,
        limit,
        offset
    )
    return jsonify(media)

@server.route('/cover_small/<filename>')
def cover_small(filename):
    return send_from_directory('covers_small', filename)

if __name__ == '__main__':
    server.run(debug=True)