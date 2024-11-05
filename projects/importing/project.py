import csv
import logging

from datetime import datetime
from django.db import transaction
from projects.models import Attribute, Project

logger = logging.getLogger(__name__)

IGNORED_ATTRIBUTES = ["projektin_nimi"]

IMPORT_DATE_FORMAT = "%d.%m.%Y"
EXPORT_DATE_FORMAT = "%Y-%m-%d"

class ProjectImporterException(Exception):
    pass


class ProjectImporter:
    def __init__(self, options=None):
        self.options = options

    @transaction.atomic
    def run(self):
        file = self.options['filename']
        projects = {project.attribute_data["hankenumero"]: project for project in Project.objects.all() if project.attribute_data.get("hankenumero", None) is not None}
        attributes = {attribute.identifier: attribute for attribute in Attribute.objects.all()}

        def create_row_indexes(row):
            row_indexes = { index: value for index, value in enumerate(row) if value in attributes }

            invalid_values = [value for value in row if value not in row_indexes.values()]
            if invalid_values:
                raise ProjectImporterException(f"Attributes ({', '.join(invalid_values)}) are not valid")

            return row_indexes

        def create_attribute_data(row_indexes, row):
            return {row_indexes[index]: sanitize(row_indexes[index], row[index]) for index, value in enumerate(row) if row_indexes[index] not in IGNORED_ATTRIBUTES}

        def sanitize(identifier, value):
            if not value:
                return None

            attribute = attributes.get(identifier, None)
            if not attribute:
                raise ProjectImporterException(f"Attribute {identifier} not found")

            value_type = attribute.value_type

            try:
                if value_type == Attribute.TYPE_BOOLEAN:
                    return True if value.lower() == "true" else False if value.lower() == "false" else None
                elif value_type == Attribute.TYPE_INTEGER:
                    return int(value)
                elif value_type == Attribute.TYPE_CHOICE:
                    return str(value)
                elif value_type == Attribute.TYPE_RICH_TEXT or value_type == Attribute.TYPE_RICH_TEXT_SHORT:
                    return { "ops": [ { "insert": value } ] }
                elif value_type == Attribute.TYPE_DATE:
                    return datetime.strptime(value, IMPORT_DATE_FORMAT).strftime(EXPORT_DATE_FORMAT)
                elif value_type == Attribute.TYPE_SHORT_STRING:
                    return str(value)
                else:
                    logger.warning(f"Unhandled type {value_type} for identifier {identifier}")
                    return str(value)
            except Exception as exc:
                logger.error(f"Error sanitizing value '{value}' for type '{value_type}'")
                raise exc

        with open(file, mode='r', newline='', encoding="utf-8") as file:
            reader = csv.reader(file, delimiter=";")
            for i, row in enumerate(reader):
                if i == 0:
                    row_indexes = create_row_indexes(row)
                    continue

                attribute_data = create_attribute_data(row_indexes, row)
                hankenumero = attribute_data["hankenumero"]

                project = projects.get(hankenumero, None)
                if not project:
                    logger.error(f"Project with hankenumero {hankenumero} not found")
                    continue

                try:
                    logger.info(f"Importing data for project: {project.name} ({hankenumero})")
                    project.attribute_data.update(attribute_data)
                    project.update_deadlines()
                    project.save()
                except Exception as exc:
                    logger.error(f"Error importing project {project.name} ({hankenumero}) data")
                    raise exc