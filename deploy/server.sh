#!/bin/bash

if test "$IS_DJANGO_Q" = "yes"; then
  echo "starting in django q..."
  python /code/manage.py qcluster
  exit 0
fi

echo "NOTICE: Get static files for serving"
./manage.py collectstatic --no-input

# Create cache table
python /code/manage.py createcachetable

# Apply database migrations
# TODO: run migrations only within one instance
echo "Applying database migrations"
python ./manage.py migrate --noinput

# Have gzipped versions ready for direct serving by uwsgi
gzip --keep --best --force --recursive /code/static/

echo "Starting uwsgi..."
exec uwsgi --ini /code/deploy/uwsgi.ini --wsgi-file deploy/wsgi.py --check-static $WWW_ROOT
