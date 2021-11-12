#!/bin/bash

echo "NOTICE: Get static files for serving"
./manage.py collectstatic --no-input

# Create cache table
python /$APP_NAME/manage.py createcachetable

# Apply database migrations
# TODO: run migrations only within one instance
echo "Applying database migrations"
python ./manage.py migrate --noinput

# Have gzipped versions ready for direct serving by uwsgi
gzip --keep --best --force --recursive $STATIC_ROOT

echo "Starting uwsgi..."
exec uwsgi --ini /$APP_NAME/deploy/uwsgi.ini --wsgi-file deploy/wsgi.py
