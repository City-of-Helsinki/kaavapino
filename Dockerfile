FROM registry.access.redhat.com/ubi8/python-39 as base

ENV PYTHONUNBUFFERED 1
ENV DEBIAN_FRONTEND noninteractive
ENV APP_NAME kaavapino

USER root

RUN mkdir /code
RUN mkdir /entrypoint
WORKDIR /code

ARG LOCAL_REDHAT_USERNAME
ARG LOCAL_REDHAT_PASSWORD
ARG BUILD_MODE

RUN if [ "x$BUILD_MODE" = "xlocal" ] ;\
    then \
        subscription-manager register --username $LOCAL_REDHAT_USERNAME --password $LOCAL_REDHAT_PASSWORD --auto-attach; \
    else \
        subscription-manager register --username ${REDHAT_USERNAME} --password ${REDHAT_PASSWORD} --auto-attach; \
    fi
# TODO POISTA
# RUN subscription-manager register --username eskenu --password mPawxi23hmzad9C --auto-attach

RUN subscription-manager repos --enable codeready-builder-for-rhel-8-x86_64-rpms

RUN yum -y update

RUN rpm -Uvh https://download.fedoraproject.org/pub/epel/epel-release-latest-8.noarch.rpm

RUN yum install -y \
    git \
    binutils \
    gdal \
    nc \
    vim

# Upgrade pip
RUN pip install -U pip

RUN useradd kaavapinouser && groupadd kaavapinogroup
FROM base AS test

# Install python dependencies
ADD requirements.txt /code/
ADD requirements-dev.txt /code/

RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir -r requirements-dev.txt

# Add entrypoint script
ADD docker-entrypoint.sh /entrypoint/
RUN chmod +x /entrypoint/docker-entrypoint.sh

FROM base AS deploy
ADD requirements.txt /code/
ADD deploy/requirements.txt ./deploy/requirements.txt
RUN pip install --no-cache-dir -r ./deploy/requirements.txt

COPY . .
COPY deploy/mime.types /etc/

USER kaavapinouser:kaavapinogroup
CMD deploy/server.sh
