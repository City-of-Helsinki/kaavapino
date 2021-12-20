#!/bin/bash

if test "$IS_DJANGO_Q" = "yes"; then
  echo "starting in django q..."
  python /$APP_NAME/manage.py qcluster
  exit 0
fi

echo "NOTICE: Get static files for serving"
python /$APP_NAME/manage.py collectstatic --no-input

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
