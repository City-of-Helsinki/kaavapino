FROM python:3.6.6-slim-stretch AS base

ENV PYTHONUNBUFFERED 1
ENV DEBIAN_FRONTEND noninteractive
ENV APP_NAME kaavapino
# Set defaults for Django paths as appropriate for this container
ENV STATIC_ROOT /srv/static
ENV MEDIA_ROOT /srv/media

# Name the workdir after the project, makes it easier to
# know where you are when troubleshooting
RUN mkdir /$APP_NAME
WORKDIR /$APP_NAME

RUN mkdir -p /srv/static /srv/media
RUN chgrp 0 /srv/static /srv/media && chmod g+w /srv/static /srv/media

# Install the appropriate Ubuntu packages
RUN apt-get update && apt-get install -y \
    build-essential \
    libyaml-dev \
    libxml2-dev \
    libxslt1-dev \
    libpq-dev \
    git \
    libgeos-dev \
    binutils \
    libproj-dev \
    gdal-bin \
    netcat \
    vim

# Upgrade pip
RUN pip install -U pip

##### Test image #####
FROM base AS test

ADD requirements.txt /$APP_NAME/
ADD requirements-dev.txt /$APP_NAME/

RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir -r requirements-dev.txt

ADD docker-entrypoint.sh /
RUN chmod +x /docker-entrypoint.sh

##### Server image #####
FROM base AS deploy

ADD requirements.txt .
ADD deploy/requirements.txt ./deploy/requirements.txt
RUN pip install --no-cache-dir -r ./deploy/requirements.txt

COPY . .

RUN python manage.py collectstatic --noinput

CMD deploy/server.sh
