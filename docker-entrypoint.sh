#!/bin/bash

if test "$IS_DJANGO_Q" = "yes"; then
  echo "starting in django q... entry point won't do anything"
  exit 0
fi

echo "Checking for database on host 'db', port 5432"
until nc -z -v -w30 "db" 5432
do
  echo "Waiting for postgres database connection..."
  sleep 1
done
echo "Database found!"

# Create cache table
echo "Creating cache table"
python manage.py createcachetable

# Apply database migrations
echo "Applying database migrations"
python manage.py migrate --noinput

# Create missing default task schedules
echo "Creating task schedules"
python manage.py schedule_tasks

set -e
# Start server
echo "Starting server"
python manage.py runserver 0.0.0.0:8000

exit 0
