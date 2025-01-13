##### Compile image #####
FROM registry.access.redhat.com/ubi8/python-39 AS compile-image

USER root
ENV APP_NAME kaavapino

RUN dnf -y install https://dl.fedoraproject.org/pub/epel/epel-release-latest-8.noarch.rpm

RUN cd /tmp
RUN wget http://download.osgeo.org/geos/geos-3.9.2.tar.bz2
RUN tar -xjf geos-3.9.2.tar.bz2
RUN cd geos-3.9.2 && \
./configure && make && make install && cd ..

RUN cd /tmp
RUN wget https://download.osgeo.org/proj/proj-7.2.1.tar.gz
RUN tar -xvf proj-7.2.1.tar.gz
RUN cd proj-7.2.1 && \
./configure && make && make install && cd ..

RUN wget https://github.com/OSGeo/gdal/releases/download/v3.2.2/gdal-3.2.2.tar.gz
RUN tar -xvf gdal-3.2.2.tar.gz
RUN cd gdal-3.2.2 && \
./configure --with-python && \
make && \
make install


##### Base image #####
FROM registry.access.redhat.com/ubi8/python-39 AS base

ENV PYTHONUNBUFFERED 1
ENV DEBIAN_FRONTEND noninteractive
ENV APP_NAME kaavapino
# Set defaults for Django paths as appropriate for this container
# ENV STATIC_ROOT /srv/static
# ENV MEDIA_ROOT /srv/media

USER root

# Name the workdir after the project, makes it easier to
# know where you are when troubleshooting
RUN mkdir /$APP_NAME
WORKDIR /$APP_NAME

#GDAL dependencies
COPY --from=compile-image /usr/local/bin /usr/local/bin
COPY --from=compile-image /usr/local/include /usr/local/include
COPY --from=compile-image /usr/local/lib /usr/local/lib
COPY --from=compile-image /usr/local/share/gdal /usr/local/share/gdal
COPY --from=compile-image /usr/local/share/proj /usr/local/share/proj
COPY --from=compile-image /usr/lib64 /usr/lib64

ENV LD_LIBRARY_PATH=/usr/local/lib:$LD_LIBRARY_PATH
ENV PROJ_LIB=/usr/local/share/proj

RUN dnf install -y \
    git \
    binutils \
    nc \
    vim

# Upgrade pip
RUN pip install -U pip

# Install Poetry
RUN pip install poetry==1.8.5

RUN groupadd -g 1003 kaavapinogroup && useradd -u 1002 -g kaavapinogroup kaavapinouser


##### Test image #####
FROM base AS test

# Install python dependencies
COPY poetry.lock pyproject.toml /$APP_NAME/
RUN poetry export -f requirements.txt --output requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Add entrypoint script
ADD docker-entrypoint.sh /
RUN chmod +x /docker-entrypoint.sh


##### Server image #####
FROM base AS deploy

# Install python dependencies
COPY poetry.lock pyproject.toml ./
ADD deploy/requirements.txt ./deploy/requirements.txt
RUN poetry export --without dev -f requirements.txt --output requirements.txt
RUN pip install --no-cache-dir -r ./deploy/requirements.txt

COPY . .

#RUN chown -Rh kaavapinouser:kaavapinogroup /$APP_NAME

USER kaavapinouser

CMD deploy/server.sh
