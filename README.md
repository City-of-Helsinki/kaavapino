# kaavapino
Project management system for city planning projects.

## Prerequisites

* PostgreSQL (>= 9.3)
* Python (>= 3.6)

## Development

It is possible to either use `docker-compose` or set up the development environment manually
as described below.

### Using docker-compose

Development environment can be initialized using `docker-compose`.
You need to have `docker` and `docker-compose` available on your system.

To bring up the dev environment run:

    docker-compose up

To manage docker-compose setup:

    docker-compose build                # Builds project container from the Dockerfile
    docker-compose up -d                # Start all required services in the background
    docker-compose stop                 # Stop services
    docker exec -it kaavapino-api bash  # Open bash into the django container

### Install required system packages


#### PostgreSQL and PostGIS

Install PostgreSQL and PostGIS.

    # Ubuntu 16.04
    sudo apt-get install python3-dev libpq-dev postgresql postgis

#### GeoDjango extra packages

    # Ubuntu 16.04
    sudo apt-get install binutils libproj-dev gdal-bin

### Creating a Python virtualenv

Create a Python >=3.6 virtualenv either using the [`venv`](https://docs.python.org/3/library/venv.html) tool or using
the great [virtualenvwrapper](https://virtualenvwrapper.readthedocs.io/en/latest/) toolset. Assuming the latter,
once installed, simply do:

    mkvirtualenv -p /usr/bin/python3 kaavapino

The virtualenv will automatically activate. To activate it in the future, just do:

    workon kaavapino

### Creating Python requirements files

* Run `prequ compile`

### Updating Python requirements files

* Run `prequ update`

### Installing Python requirements

* Run `prequ sync`
* For development run `prequ sync requirements.txt requirements-dev.txt`

### Database

To setup a database compatible with the default database settings:

Create user and database

    sudo -u postgres createuser -P -R -S kaavapino  # use password `kaavapino`
    sudo -u postgres createdb -O kaavapino kaavapino

Enable PostGIS

    sudo -u postgres psql -d "kaavapino" -c "CREATE EXTENSION IF NOT EXISTS postgis;"

Allow the kaavapino user to create databases when running tests

    sudo -u postgres psql -c "ALTER USER kaavapino CREATEDB;"

Tests also require that PostGIS extension is installed on the test database. This can be achieved most easily by
adding PostGIS extension to the default template which is then used when the test databases are created:

    sudo -u postgres psql -d template1 -c "CREATE EXTENSION IF NOT EXISTS postgis;"

### Django configuration

Environment variables are used to customize configuration in `kaavapino/settings.py`. If you wish to override any
settings, you can place them in a local `.env` file which will automatically be sourced when Django imports
the settings file.

Alternatively you can create a `local_settings.py` which is executed at the end of the `kaavapino/settings.py` in the
same context so that the variables defined in the settings are available.

### Running development environment

* Enable debug `echo 'DEBUG=True' >> .env`
* Run `python manage.py migrate`
* Run `python manage.py runserver 0.0.0.0:8000`

## Running tests

* Run `pytest`

## Importing attributes

* Run `python manage.py import_attributes <attribute excel file> [--sheet sheet name] [--overwrite]`
