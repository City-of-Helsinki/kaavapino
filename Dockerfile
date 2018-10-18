FROM python:3.6.6-slim-stretch

ENV PYTHONUNBUFFERED 1
ENV DEBIAN_FRONTEND noninteractive

RUN mkdir /code
RUN mkdir /entrypoint
WORKDIR /code

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
    netcat

# Upgrade pip
RUN pip install -U pip

# Install python dependencies
ADD requirements.txt /code/
ADD requirements-dev.txt /code/

RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir -r requirements-dev.txt

# Add entrypoint script
ADD docker-entrypoint.sh /entrypoint/
RUN chmod +x /entrypoint/docker-entrypoint.sh
