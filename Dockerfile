# Image for the web UI (server.py) only -- scanning, scraping, MediaInfo and ffmpeg all stay on the
# machine that owns the media library. The image holds code only: the database, covers and
# hidden_interests.txt are mounted at /data at run time (see compose.yaml), so updating them never
# needs a rebuild.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements-server.txt .
RUN pip install --no-cache-dir -r requirements-server.txt

# exactly what server.py (transitively) imports, plus its templates and static files
COPY server.py serverconfig.py media.py imdbinterestid.py exceptions.py gunicorn.conf.py ./
COPY templates/ templates/
COPY static/ static/
# serverconfig.py refuses to start without a config.ini; this one points the data paths at /data
COPY docker/config.docker.ini config.ini

RUN useradd --system --no-create-home app
USER app

# host, port and worker count: gunicorn.conf.py, reading config.ini's [server] section
CMD ["gunicorn", "-c", "gunicorn.conf.py", "server:server"]
