#!/bin/bash

echo "Checking for database on host 'db', port 5432"
until nc -z -v -w30 "db" 5432
do
  echo "Waiting for postgres database connection..."
  sleep 1
done
echo "Database found!"

# Create cache table
python manage.py createcachetable

# Apply database migrations
echo "Applying database migrations"
python manage.py migrate --noinput

set -e
# Start server
echo "Starting server"
python manage.py runserver 0.0.0.0:8000
