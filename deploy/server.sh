#!/bin/bash

echo "NOTICE: Get static files for serving"
./manage.py collectstatic --no-input

echo -e "NOTICE: Start the uwsgi web server \n static files require WWW_ROOT env var"
exec uwsgi --http :8000 --wsgi-file deploy/wsgi.py --check-static $WWW_ROOT
