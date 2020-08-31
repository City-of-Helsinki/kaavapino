#!/bin/bash

echo "NOTICE: Get static files for serving"
./manage.py collectstatic --no-input

# Apply database migrations
echo "Applying database migrations"
python ./manage.py migrate --noinput

# Have gzipped versions ready for direct serving by uwsgi
gzip --keep --best --force --recursive /code/static/

# Restart the application
echo "Restarting the application..."
touch deploy/uwsgi.ini

#echo -e "NOTICE: Start the uwsgi web server \n static files require WWW_ROOT env var"
#exec uwsgi --http :8000 --wsgi-file deploy/wsgi.py --check-static $WWW_ROOT -b 32768
