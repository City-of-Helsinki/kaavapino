FROM python:3.6.6-slim-stretch AS base

ENV PYTHONUNBUFFERED 1
ENV DEBIAN_FRONTEND noninteractive
ENV APP_NAME kaavapino
# Set defaults for paths as appropriate for this container
ENV STATIC_ROOT /srv/static
ENV MEDIA_ROOT /srv/media

# Name the workdir after the project, makes it easier to
# know where you are when troubleshooting
RUN mkdir /$APP_NAME
RUN mkdir /entrypoint
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

FROM base AS test

# Install python dependencies for test image
ADD requirements.txt /$APP_NAME/
ADD requirements-dev.txt /$APP_NAME/

RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir -r requirements-dev.txt

# Add entrypoint script
ADD docker-entrypoint.sh /entrypoint/
RUN chmod +x /entrypoint/docker-entrypoint.sh

FROM base AS deploy
# Install python dependencies for production image
ADD requirements.txt /$APP_NAME/
ADD deploy/requirements.txt ./deploy/requirements.txt
RUN pip install --no-cache-dir -r ./deploy/requirements.txt

# Application code layer
COPY . .
# FIXME, document why this exists
COPY deploy/mime.types /etc/

CMD deploy/server.sh
