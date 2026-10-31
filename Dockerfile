# Image for the web UI (web/server.py) only -- scanning, scraping, MediaInfo and ffmpeg all stay on the
# machine that owns the media library. The image holds code only: the database, covers and
# hidden_interests.txt are mounted at /data at run time (see compose.yaml), so updating them never
# needs a rebuild.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements-server.txt .
RUN pip install --no-cache-dir -r requirements-server.txt

# exactly what web/server.py (transitively) imports -- web/ with its templates and static files, and the
# three model modules it uses -- plus serverconfig.py
COPY serverconfig.py ./
COPY model/__init__.py model/media.py model/imdbinterestid.py model/exceptions.py model/
COPY web/ web/
# serverconfig.py refuses to start without a config.ini; this one points the data paths at /data
COPY deploy/config.docker.ini config.ini

RUN useradd --system --no-create-home app
USER app

# host, port and worker count: web/gunicorn.conf.py, reading config.ini's [server] section
CMD ["gunicorn", "-c", "web/gunicorn.conf.py", "web.server:server"]
