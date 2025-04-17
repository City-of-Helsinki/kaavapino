# This wrapper is copied from django\contrib\gis\db\backends\postgis\base.py
# and is supposed to work exactly as the default postgis backend. The only change is
# an additional check for if postgis extension is already installed (was causing errors in migrate)
# This same fix is included in Django versions 4.2 and newer. If upgrading Django to 4.2+, this file
# should be deleted and the default database backend used.

from django.db.backends.base.base import NO_DB_ALIAS
from django.db.backends.postgresql.base import (
    DatabaseWrapper as Psycopg2DatabaseWrapper,
)

from django.contrib.gis.db.backends.postgis.features import DatabaseFeatures
from django.contrib.gis.db.backends.postgis.introspection import PostGISIntrospection
from django.contrib.gis.db.backends.postgis.operations import PostGISOperations
from django.contrib.gis.db.backends.postgis.schema import PostGISSchemaEditor


class DatabaseWrapper(Psycopg2DatabaseWrapper):
    SchemaEditorClass = PostGISSchemaEditor

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if kwargs.get('alias', '') != NO_DB_ALIAS:
            self.features = DatabaseFeatures(self)
            self.ops = PostGISOperations(self)
            self.introspection = PostGISIntrospection(self)

    def prepare_database(self):
        super().prepare_database()
        # CHANGE TO ORIGINAL: Return if extension already installed
        with self.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_extension WHERE extname = %s", ["postgis"])
            if bool(cursor.fetchone()):
                return
        with self.cursor() as cursor:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis")
