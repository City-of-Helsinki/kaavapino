import re
from collections import namedtuple

from django.db import models
from django.contrib.auth import get_user_model
from rest_framework import serializers

from projects.models import (
    Attribute,
    AttributeValueChoice,
    FieldSetAttribute,
    Project,
)
from projects.models.project import (
    PhaseAttributeMatrixCell,
    ProjectFloorAreaSectionAttributeMatrixCell,
    ProjectPhaseFieldSetAttributeIndex,
)
from projects.serializers.deadline import DeadlineSerializer
from projects.serializers.utils import _is_attribute_required

FOREIGN_KEY_TYPE_MODELS = {
    Attribute.TYPE_USER: {
        "model": get_user_model(),
        "filters": {},
        "label_format": "{instance.first_name} {instance.last_name}",
        "value_field": "uuid",
    }
}

MatrixSectionAttribute = namedtuple("MatrixSectionAttribute", ["matrix"])


class AttributeChoiceSchemaSerializer(serializers.Serializer):
    label = serializers.CharField()
    value = serializers.CharField()


class ConditionSerializer(serializers.Serializer):
    variable = serializers.CharField()
    operator = serializers.CharField()
    comparison_value = serializers.SerializerMethodField()
    comparison_value_type = serializers.CharField()

    def get_comparison_value(self, obj):
        try:
            attribute = Attribute.objects.get(identifier=obj['variable'])
        except Attribute.DoesNotExist:
            attribute = None

        value = obj['comparison_value']
        value_type = obj['comparison_value_type']

        if value_type[0:4] == "list":
            return_list = re.split(',\s+', value[1:-1])

            if attribute and attribute.value_type == "choice":
                for index, choice in enumerate(return_list):
                    choice = choice.strip("\"")
                    try:
                        return_list[index] = \
                           attribute.value_choices.get(value=choice).identifier
                    except AttributeValueChoice.DoesNotExist:
                        return_list[index] = choice

            elif value_type[5:-1] == "string":
                return_list = [
                    string.strip("\"")
                    for string in return_list
                ]
            elif value_type[5:-1] == "number":
                return_list = [
                    int(number)
                    for number in return_list
                ]

            return return_list
        elif attribute and attribute.value_type == "choice":
            try:
                return attribute.value_choices.get(value=value).identifier
            except AttributeValueChoice.DoesNotExist:
                return value
        elif not isinstance(value, bool):
            try:
                return int(value)
            except ValueError:
                return value
        else:
            return value


class AutofillRuleSerializer(serializers.Serializer):
    condition = ConditionSerializer()
    then_branch = serializers.CharField()
    else_branch = serializers.CharField()
    variables = serializers.ListField(child=serializers.CharField())


class AttributeSchemaSerializer(serializers.Serializer):
    label = serializers.CharField(source="name")
    name = serializers.CharField(source="identifier")
    help_text = serializers.CharField()
    help_link = serializers.CharField(read_only=True)
    multiple_choice = serializers.BooleanField()
    character_limit = serializers.IntegerField()
    fieldset_attributes = serializers.SerializerMethodField()
    fieldset_index = serializers.SerializerMethodField("get_fieldset_index")
    type = serializers.CharField(source="value_type")
    required = serializers.SerializerMethodField()
    choices = serializers.SerializerMethodField()
    generated = serializers.BooleanField(read_only=True)
    unit = serializers.CharField()
    calculations = serializers.ListField(child=serializers.CharField())
    visibility_conditions = serializers.ListField(child=ConditionSerializer())
    autofill_rule = serializers.ListField(child=AutofillRuleSerializer())
    autofill_readonly = serializers.BooleanField()
    updates_autofill = serializers.BooleanField()
    related_fields = serializers.ListField(child=serializers.CharField())
    searchable = serializers.BooleanField()
    highlight_group = serializers.CharField()
    display = serializers.CharField()
    editable = serializers.SerializerMethodField("get_editable")

    def get_editable(self, attribute):
        project = self.context["project"]
        user = self.context["user"]
        print(user)
        print(project)

        if not project:
            return None
        elif project.user == user and attribute.owner_editable:
            return True
        elif user.has_privilege(attribute.edit_privilege):
            return True
        else:
            return False

    def get_fieldset_attributes(self, attribute):
        try:
            context = self.context
        except AttributeError:
            context = {}

        def take_index(attribute):
            try:
                return attribute["fieldset_index"] or 0
            except KeyError:
                return 0

        if attribute.value_type == Attribute.TYPE_FIELDSET:
            return sorted([
                AttributeSchemaSerializer(attr, context=context).data
                for attr in attribute.fieldset_attributes.all()
            ], key=take_index)
        return []

    def get_fieldset_index(self, attribute):
        if FieldSetAttribute.objects.filter(attribute_target=attribute).count() <= 0:
            return None

        try:
            fieldset = FieldSetAttribute.objects.get(attribute_target=attribute)
            return ProjectPhaseFieldSetAttributeIndex.objects.get(
                phase=self.context["phase"],
                attribute=fieldset,
            ).index
        except Exception:
            return None

    @staticmethod
    def get_required(attribute):
        return _is_attribute_required(attribute)

    @staticmethod
    def get_choices(attribute):
        foreign_key_choice = FOREIGN_KEY_TYPE_MODELS.get(attribute.value_type, None)

        if foreign_key_choice:
            choices = AttributeSchemaSerializer._get_foreign_key_choices(
                foreign_key_choice
            )
        else:
            choices = AttributeSchemaSerializer._get_attribute_choices(attribute)

        if not choices:
            return None

        return AttributeChoiceSchemaSerializer(choices, many=True).data

    @staticmethod
    def _get_foreign_key_choices(choice_data):
        choices = []
        model = choice_data["model"]
        filters = choice_data["filters"]
        label_format = choice_data["label_format"]
        value_field = (
            choice_data["value_field"] if choice_data.get("value_field", None) else "pk"
        )
        choice_instances = model.objects.filter(**filters)
        for choice in choice_instances:
            choices.append(
                {
                    "label": label_format.format(instance=choice),
                    "value": getattr(choice, value_field),
                }
            )
        return choices

    @staticmethod
    def _get_attribute_choices(attribute):
        choices = []
        choice_instances = attribute.value_choices.all()
        for choice in choice_instances:
            choices.append({"label": choice.value, "value": choice.identifier})
        return choices


class ProjectSectionAttributeSchemaSerializer(serializers.Serializer):
    relies_on = serializers.CharField(
        source="relies_on.attribute.identifier", allow_null=True
    )
    priority = serializers.IntegerField(read_only=True)

    @staticmethod
    def get_matrix(section_attribute):
        return getattr(section_attribute, "matrix", None)


class ProjectSectionAttributeMatrixSchemaSerializer(serializers.Serializer):
    type = serializers.SerializerMethodField()
    matrix = serializers.JSONField()

    def get_type(self, section_attribute):
        return "matrix"


class BaseMatrixableSchemaSerializer(serializers.Serializer):
    def _create_matrix_fields(self, cell_class, section_attributes):
        matrices = {}
        removal_indices = []

        cells = cell_class.objects.filter(
            attribute__in=section_attributes
        )
        cell_attribute_map = {cell.attribute_id: cell for cell in cells}

        # Iterate over all section attributes and find all matrices
        for idx, section_attribute in enumerate(section_attributes):
            cell = cell_attribute_map.get(section_attribute.id, None)

            # If the attribute is not part of a matrix, then continue
            if not cell:
                continue

            # Create a matrix structure
            matrix_structure = cell.structure
            matrix_structure_id = cell.structure_id

            # Create a base template if the matrix is not in the list
            if matrix_structure_id not in matrices:
                matrices[matrix_structure_id] = {
                    "index": section_attribute.index,
                    "rows": matrix_structure.row_names,
                    "columns": matrix_structure.column_names,
                    "fields": [],
                }

            query_params = getattr(self.context["request"], "GET", {})
            try:
                project = Project.objects.get(
                    pk=int(query_params.get("project", "")),
                )
            except Exception:
                project = None

            user = self.context["request"].user

            # Add each cell as fields to the matrix
            cell_attribute = self._create_matrix_cell_attribute(
                cell,
                section_attribute,
                project,
                user,
            )
            matrices[matrix_structure_id]["fields"].append(cell_attribute)

            # Store the field index for later removal
            removal_indices.append(idx)

        self._sort_matrices(matrices)

        # Remove all of the fields from the base attributes that
        # belongs to a matrix, since they will be represented
        # within the matrix structure instead.
        # Removal from highest to lowest index to keep index order.
        for i in reversed(removal_indices):
            del section_attributes[i]

        # Add the matrix structures at the index of the first field in the matrix
        for structure_id, matrix_data in matrices.items():
            attribute = MatrixSectionAttribute(matrix=matrix_data)
            insert_index = self._get_matrix_attribute_index(
                matrix_data, len(section_attributes) - 1
            )
            section_attributes.insert(insert_index, attribute)

    @staticmethod
    # def _serialize_section_attribute(section_attribute):
    def _serialize_section_attribute(section_attribute, project, user):
        if hasattr(section_attribute, "matrix"):
            return ProjectSectionAttributeMatrixSchemaSerializer(section_attribute).data

        serialized_attribute = ProjectSectionAttributeSchemaSerializer(
            section_attribute
        ).data

        serialized_attribute.update(AttributeSchemaSerializer(
            section_attribute.attribute,
            context={
                "phase": section_attribute.section.phase,
                "project": project,
                "user": user,
            },
        ).data)

        return serialized_attribute

    @staticmethod
    def _create_matrix_cell_attribute(cell, section_attribute, project, user):
        cell_attribute = ProjectSectionAttributeSchemaSerializer(section_attribute).data
        cell_attribute.update(AttributeSchemaSerializer(
            section_attribute.attribute,
            context={
                "project": project,
                "user": user,
            },
        ).data)
        cell_attribute["row"] = cell.row
        cell_attribute["column"] = cell.column

        return cell_attribute

    @staticmethod
    def _sort_matrices(matrices):
        for structure_id, matrix in matrices.items():
            matrix["fields"].sort(key=lambda x: x["column"], reverse=False)
            matrix["fields"].sort(key=lambda x: x["row"], reverse=False)

    @staticmethod
    def _get_matrix_attribute_index(matrix_data, max_index):
        highest_list_index = max_index

        # Field index goes from 1..n, max index goes from 0..n
        matrix0_index = matrix_data.pop("index") - 1
        return (
            matrix0_index if matrix0_index < highest_list_index else highest_list_index
        )


class ProjectSectionSchemaSerializer(BaseMatrixableSchemaSerializer):
    title = serializers.CharField(source="name")
    fields = serializers.SerializerMethodField("_get_fields")

    def _get_fields(self, section):
        query_params = getattr(self.context["request"], "GET", {})
        try:
            project = Project.objects.get(
                pk=int(query_params.get("project", "")),
            )
        except Exception:
            project = None

        user = self.context["request"].user
        section_attributes = list(section.projectphasesectionattribute_set.all())
        self._create_matrix_fields(PhaseAttributeMatrixCell, section_attributes)

        # Create a list of serialized fields
        data = []
        for section_attribute in section_attributes:
            data.append(self._serialize_section_attribute(
                section_attribute,
                project,
                user,
            ))

        return data


class ProjectPhaseSchemaSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField(source="name")
    color = serializers.CharField()
    color_code = serializers.CharField()
    list_prefix = serializers.CharField()
    sections = ProjectSectionSchemaSerializer(many=True)


class ProjectFloorAreaSchemaSerializer(BaseMatrixableSchemaSerializer):
    title = serializers.CharField(source="name")
    fields = serializers.SerializerMethodField("_get_fields")

    def _get_fields(self, section):
        query_params = getattr(self.context["request"], "GET", {})
        try:
            project = Project.objects.get(
                pk=int(query_params.get("project", "")),
            )
        except Exception:
            project = None

        user = self.context["request"].user
        section_attributes = list(section.projectfloorareasectionattribute_set.all())
        self._create_matrix_fields(
            ProjectFloorAreaSectionAttributeMatrixCell,
            section_attributes
        )

        # Create a list of serialized fields
        data = []
        for section_attribute in section_attributes:
            data.append(self._serialize_section_attribute(
                section_attribute,
                project,
                user,
            ))

        return data


class ProjectPhaseDeadlineSectionSerializer(serializers.Serializer):
    name = serializers.CharField()
    attributes = serializers.SerializerMethodField("_get_attributes")

    def _get_attributes(self, deadline_section):
        serialized = []
        deadlines = deadline_section.deadlines.select_related("attribute")

        query_params = getattr(self.context["request"], "GET", {})
        try:
            project = Project.objects.get(
                pk=int(query_params.get("project", "")),
            )
        except Exception:
            project = None

        user = self.context["request"].user
        i = 0

        for dl in deadlines:
            if project:
                check_owner = dl.attribute.owner_viewable and \
                    project.user == user
            else:
                check_owner = False

            check_privilege = user.has_privilege(dl.attribute.view_privilege)
            if check_owner or check_privilege:
                serialized.append(AttributeSchemaSerializer(
                    dl.attribute,
                    context={
                        "project": project,
                        "user": user,
                    },
                ).data)
                serialized[i]["deadline"] = DeadlineSerializer(dl).data
                i += 1

        return serialized


class ProjectPhaseDeadlineSectionsSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField(source="name")
    color = serializers.CharField()
    color_code = serializers.CharField()
    list_prefix = serializers.CharField()
    sections = ProjectPhaseDeadlineSectionSerializer(
        source="deadline_sections", many=True,
    )


class ProjectSubtypeListFilterSerializer(serializers.ListSerializer):
    def to_representation(self, data):
        query_params = getattr(self.context["request"], "GET", {})
        queryset = data.all() if isinstance(data, models.Manager) else data
        queryset = self.filter_subtypes(queryset, query_params)
        return super().to_representation(queryset)

    def filter_subtypes(self, queryset, query_params):
        subtypes = query_params.get("subtypes", "")
        subtypes = [subtype.strip() for subtype in subtypes.split(",") if subtype]

        if subtypes:
            queryset = queryset.filter(id__in=subtypes)

        return queryset


class ProjectSubTypeSchemaSerializer(serializers.Serializer):
    subtype_name = serializers.CharField(source="name")
    subtype = serializers.IntegerField(source="id")

    phases = ProjectPhaseSchemaSerializer(many=True)
    floor_area_sections = ProjectFloorAreaSchemaSerializer(many=True)
    deadline_sections = ProjectPhaseDeadlineSectionsSerializer(
        many=True,
        source="phases",
    )

    class Meta:
        list_serializer_class = ProjectSubtypeListFilterSerializer


class ProjectTypeSchemaSerializer(serializers.Serializer):
    subtypes = ProjectSubTypeSchemaSerializer(many=True)
    type_name = serializers.CharField(source="name")
    type = serializers.IntegerField(source="id")
