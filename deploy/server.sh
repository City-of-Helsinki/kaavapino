#!/bin/bash

echo "NOTICE: Get static files for serving"
./manage.py collectstatic --no-input

# Apply database migrations
echo "Applying database migrations"
python ./manage.py migrate --noinput

# Have gzipped versions ready for direct serving by uwsgi
gzip --keep --best --force --recursive /code/static/

if test "$1" = "start_production"; then
    echo "Starting production"
    exec uwsgi --ini /code/deploy/uwsgi.ini
fi
