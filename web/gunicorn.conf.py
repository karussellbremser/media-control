# gunicorn settings for the docker image (see Dockerfile). Host and port come from config.ini's
# [server] section, like when running `python -m web.server`, so the port is set in exactly one place --
# compose.yaml only maps a host port to it.
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # the project root, where serverconfig.py is
import serverconfig

bind = serverconfig.SERVER_HOST + ":" + str(serverconfig.SERVER_PORT)
workers = 2
accesslog = "-"  # to stdout, i.e. `docker compose logs`
