from collections import namedtuple

from django.db import models
from django.contrib.auth import get_user_model
from rest_framework import serializers

from projects.models import Attribute
from projects.models.project import PhaseAttributeMatrixCell
from projects.serializers.utils import _is_attribute_required

VALUE_TYPE_MAP = {Attribute.TYPE_USER: Attribute.TYPE_SHORT_STRING}

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


class AttributeSchemaSerializer(serializers.Serializer):
    label = serializers.CharField(source="name")
    name = serializers.CharField(source="identifier")
    help_text = serializers.CharField()
    multiple_choice = serializers.BooleanField()
    fieldset_attributes = serializers.SerializerMethodField()
    type = serializers.SerializerMethodField()
    required = serializers.SerializerMethodField()
    choices = serializers.SerializerMethodField()

    @staticmethod
    def get_fieldset_attributes(attribute):
        if attribute.value_type == Attribute.TYPE_FIELDSET:
            return [
                AttributeSchemaSerializer(attr).data
                for attr in attribute.fieldset_attributes.order_by(
                    "fieldset_attribute_source"
                )
            ]
        return []

    @staticmethod
    def get_required(attribute):
        return _is_attribute_required(attribute)

    @staticmethod
    def get_type(attribute):
        value_type = attribute.value_type
        # Remap values if applicable
        return VALUE_TYPE_MAP.get(value_type, value_type)

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

    @staticmethod
    def get_matrix(section_attribute):
        return getattr(section_attribute, "matrix", None)


class ProjectSectionAttributeMatrixSchemaSerializer(serializers.Serializer):
    type = serializers.SerializerMethodField()
    matrix = serializers.JSONField()

    def get_type(self, section_attribute):
        return "matrix"


class ProjectSectionSchemaSerializer(serializers.Serializer):
    title = serializers.CharField(source="name")
    fields = serializers.SerializerMethodField("_get_fields")

    def _get_fields(self, section):
        section_attributes = list(section.projectphasesectionattribute_set.all())
        self._create_matrix_fields(section_attributes)

        # Create a list of serialized fields
        data = []
        for section_attribute in section_attributes:
            data.append(self._serialize_section_attribute(section_attribute))

        return data

    def _create_matrix_fields(self, section_attributes):
        matrices = {}
        removal_indices = []

        cells = PhaseAttributeMatrixCell.objects.filter(
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

            # Add each cell as fields to the matrix
            cell_attribute = self._create_matrix_cell_attribute(cell, section_attribute)
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
    def _serialize_section_attribute(section_attribute):
        if hasattr(section_attribute, "matrix"):
            return ProjectSectionAttributeMatrixSchemaSerializer(section_attribute).data

        serialized_attribute = ProjectSectionAttributeSchemaSerializer(
            section_attribute
        ).data
        serialized_attribute.update(
            AttributeSchemaSerializer(section_attribute.attribute).data
        )
        return serialized_attribute

    @staticmethod
    def _create_matrix_cell_attribute(cell, section_attribute):
        cell_attribute = ProjectSectionAttributeSchemaSerializer(section_attribute).data
        cell_attribute.update(
            AttributeSchemaSerializer(section_attribute.attribute).data
        )
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


class ProjectPhaseSchemaSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField(source="name")
    color = serializers.CharField()
    color_code = serializers.CharField()
    sections = ProjectSectionSchemaSerializer(many=True)


class ProjectSubtypeListFilterSerializer(serializers.ListSerializer):
    def to_representation(self, data):
        query_params = getattr(self.context["request"], "GET", {})
        queryset = data.all() if isinstance(data, models.Manager) else data
        queryset = self.filter_subtypes(queryset, query_params)
        return super().to_representation(queryset)

    def filter_subtypes(self, queryset, query_params):
        subtypes = query_params.get("subtypes", None)
        subtypes = [subtype.strip() for subtype in subtypes.split(",") if subtype]

        if subtypes:
            queryset = queryset.filter(id__in=subtypes)

        return queryset


class ProjectSubTypeSchemaSerializer(serializers.Serializer):
    subtype_name = serializers.CharField(source="name")
    subtype = serializers.IntegerField(source="id")

    phases = ProjectPhaseSchemaSerializer(many=True)

    class Meta:
        list_serializer_class = ProjectSubtypeListFilterSerializer


class ProjectTypeSchemaSerializer(serializers.Serializer):
    subtypes = ProjectSubTypeSchemaSerializer(many=True)
    type_name = serializers.CharField(source="name")
    type = serializers.IntegerField(source="id")
