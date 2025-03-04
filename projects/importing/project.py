import csv
import logging

from datetime import datetime
from django.db import transaction
from projects.models import Attribute, Project, ProjectDeadline, Deadline

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
            return {row_indexes[index]: sanitize(row_indexes[index], row[index]) for index, value in enumerate(row) if row[index] and row_indexes[index] not in IGNORED_ATTRIBUTES}

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

                import_attribute_data = create_attribute_data(row_indexes, row)
                hankenumero = import_attribute_data["hankenumero"]

                if not hankenumero:
                    logger.error("Import attribute data missing hankenumero")
                    continue

                project = projects.get(hankenumero, None)
                if not project:
                    logger.error(f"Project with hankenumero {hankenumero} not found")
                    continue

                project_attribute_data = project.attribute_data

                logger.info(f"Importing data for project: {project.name} (size: {project.subtype.name}) (hankenumero: {hankenumero})")
                for key, value in import_attribute_data.items():
                    attribute = attributes.get(key)
                    if not attribute:
                        logger.warning(f"Attribute {key} not found")

                    if attribute.value_type == Attribute.TYPE_DATE:
                        # Update ProjectDeadline
                        try:
                            deadline = Deadline.objects.get(attribute=attribute, subtype=project.subtype)
                            project_deadline = project.deadlines.get(deadline=deadline)
                            if not project_deadline.generated:
                                continue  # Don't update value if it has been manually modified

                            project_deadline.date = value
                            project_deadline.generated = False
                            project_deadline.save()
                            project_attribute_data[key] = value
                            logger.info(f"Updated ProjectDeadline {project_deadline} with {value}")
                        except Deadline.DoesNotExist:
                            logger.warning(f"Deadline not found for attribute {key}", )
                        except ProjectDeadline.DoesNotExist:
                            logger.warning(f"ProjectDeadline not found for deadline {deadline}")
                        except Exception as exc:
                            logger.error("Error", exc)


                attribute_data = {**import_attribute_data, **project_attribute_data}

                try:
                    project.attribute_data = attribute_data
                    project.update_deadlines()
                    project.save()
                except Exception as exc:
                    logger.error(f"Error importing project {project.name} ({hankenumero}) data")
                    raise exc