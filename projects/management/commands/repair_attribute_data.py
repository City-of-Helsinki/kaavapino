import logging

from actstream import action
from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import json
from six.moves import input

from projects.actions import verbs
from projects.models import Attribute, AttributeValueChoice, Project

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Repair attribute_data for one or all projects"

    def add_arguments(self, parser):
        parser.add_argument("--id", nargs="?", type=int)
        parser.add_argument("--attribute", nargs="?", type=int)

    def handle(self, *args, **options):
        project_id = options.get("id")
        attr_identifier = options.get("attribute")

        if project_id:
            projects = Project.objects.filter(pk=project_id)
        else:
            projects = Project.objects.all()

        attributes = Attribute.objects.filter(static_property__isnull=True) \
            .exclude(identifier__in=["kaavan_vaihe", "kaavaprosessin_kokoluokka"])

        if project_id:
            attributes = attributes.filter(identifier=attr_identifier)
        else:
            pass

        changes = {}

        for project in Project.objects.all():
            changes[project] = []
            for attribute in attributes:
                value = project.attribute_data.get(attribute.identifier)
                if value and not isinstance(value, list) and attribute.multiple_choice:
                    value = [value]
                if value:
                    try:
                        converted = attribute.serialize_value(
                            attribute.deserialize_value(value)
                        )
                    except Exception:
                        converted = None

                    if isinstance(value, list):
                        try:
                            if sorted(value) == sorted(converted):
                                converted = value
                        except TypeError:
                            pass

                    if value != converted:
                        logger.info(f"\n{project.pino_number}/{attribute.identifier} ({attribute.value_type}):\n  {value} ({type(value)}) =>\n  {converted} ({type(converted)})")
                        changes[project].append({
                            "attribute": attribute,
                            "value": value,
                            "converted": converted,
                        })

        confirm = None
        while confirm not in ["y", "n"]:
            confirm = input(f"Apply above changes? Y/n ").lower()

        if confirm == "y":
            for project in projects:
                for change in changes.get(project, []):
                    project.attribute_data[change["attribute"].identifier] = \
                        change["converted"]
                    self._log_updates(
                        change["attribute"],
                        project,
                        change["value"],
                        change["converted"],
                        )

                project.save()

    def _log_updates(self, attribute, project, value, converted, prefix=""):
        if attribute.value_type == Attribute.TYPE_FIELDSET:
            for i, children in enumerate(converted):
                for key, child_converted in dict(children).items():
                    try:
                        child_value = value[i][key]
                    except (IndexError, TypeError):
                        child_value = None

                    try:
                        child_attr = Attribute.objects.get(identifier=key)
                    except Attribute.DoesNotExist:
                        continue

                    self._log_updates(
                        child_attr,
                        project,
                        child_value,
                        child_converted,
                        prefix=f"{prefix}{child_attr.identifier}[{i}].",
                    )

        self._log_update(attribute, project, value, converted, prefix)

    def _get_labels(self, values, attribute):
        labels = {}

        for val in values:
            try:
                labels[val] = attribute.value_choices.get(identifier=val).value
            except AttributeValueChoice.DoesNotExist:
                pass

        return labels

    def _log_update(self, attribute, project, value, converted, prefix):
        old_value = json.loads(json.dumps(value, default=str))
        new_value = json.loads(json.dumps(converted, default=str))
        labels = {}

        if attribute.value_type == Attribute.TYPE_CHOICE:
            if new_value:
                labels = {**labels, **self._get_labels(
                    new_value if isinstance(new_value, list) else [new_value],
                    attribute,
                )}

            if old_value:
                labels = {**labels, **self._get_labels(
                    old_value if isinstance(old_value, list) else [old_value],
                    attribute,
                )}

        if old_value != new_value:
            action.send(
                project.user,
                verb=verbs.UPDATED_ATTRIBUTE,
                action_object=attribute,
                target=project,
                attribute_identifier=prefix+attribute.identifier,
                old_value=old_value,
                new_value=new_value,
                labels=labels,
            )
