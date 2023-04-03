import re
import logging
from collections import namedtuple

from django.db import models
from django.contrib.auth import get_user_model
from django.core.cache import cache
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from projects.models import (
    Attribute,
    AttributeValueChoice,
    FieldSetAttribute,
    Project,
    ProjectSubtype,
    ProjectCardSectionAttribute,
)
from projects.models.attribute import AttributeLock
from projects.models.project import (
    PhaseAttributeMatrixCell,
    ProjectFloorAreaSectionAttributeMatrixCell,
    ProjectPhaseFieldSetAttributeIndex,
)
from projects.serializers.deadline import DeadlineSerializer
from projects.serializers.utils import _is_attribute_required
from users.models import privilege_as_int

log = logging.getLogger(__name__)


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

            if attribute and attribute.value_type == "choice" \
                and attribute.identifier != "kaavaprosessin_kokoluokka":
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
    condition = serializers.SerializerMethodField()
    conditions = serializers.SerializerMethodField()
    then_branch = serializers.CharField()
    else_branch = serializers.CharField()
    variables = serializers.ListField(child=serializers.CharField())

    # TODO remove once frontend fully supports multiple conditions
    def get_condition(self, autofill_rule):
        if len(autofill_rule.get("conditions")) == 1:
            return autofill_rule.get("conditions")[0]

    # Hide conditions if only single condition exists
    # TODO only `conditions` should be used to allow multiple OR's
    # but currently frontend does not support it
    def get_conditions(self, autofill_rule):
        conditions = autofill_rule.get("conditions", [])
        if conditions and len(conditions) > 1:
            serialized = []
            for condition in conditions:
                serializer = ConditionSerializer(condition)
                serialized.append(serializer.data)
            return serialized
        return None


class SimpleAttributeSerializer(serializers.Serializer):
    label = serializers.CharField(source="name")
    name = serializers.CharField(source="identifier")


class AttributeLockSerializer(serializers.Serializer):

    project_name = serializers.SerializerMethodField()
    attribute_identifier = serializers.SerializerMethodField()
    fieldset_attribute_identifier = serializers.SerializerMethodField()
    fieldset_attribute_index = serializers.IntegerField()
    field_identifier = serializers.SerializerMethodField()
    user_name = serializers.SerializerMethodField()
    user_email = serializers.SerializerMethodField()
    timestamp = serializers.DateTimeField()
    owner = serializers.SerializerMethodField()

    def get_project_name(self, attribute_lock):
        return attribute_lock.project.name

    def get_attribute_identifier(self, attribute_lock):
        return attribute_lock.attribute.identifier

    def get_fieldset_attribute_identifier(self, attribute_lock):
        return attribute_lock.fieldset_attribute.identifier \
            if attribute_lock.fieldset_attribute else None

    def get_field_identifier(self, attribute_lock):
        if attribute_lock.fieldset_attribute and attribute_lock.fieldset_attribute_index:
            return f'{attribute_lock.fieldset_attribute.identifier} \
            [{attribute_lock.fieldset_attribute_index}]. \
            {attribute_lock.attribute.identifier}'
        return attribute_lock.attribute.identifier

    def get_user_name(self, attribute_lock):
        return f'{attribute_lock.user.first_name} {attribute_lock.user.last_name}'

    def get_user_email(self, attribute_lock):
        return attribute_lock.user.email

    def get_owner(self, attribute_lock):
        return self.context["request"].user == attribute_lock.user

    class Meta:
        model = AttributeLock


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
    placeholder_text = serializers.CharField()
    choices = serializers.SerializerMethodField()
    generated = serializers.BooleanField(read_only=True)
    unit = serializers.CharField()
    calculations = serializers.ListField(child=serializers.CharField())
    visibility_conditions = serializers.ListField(child=ConditionSerializer())
    hide_conditions = serializers.ListField(child=ConditionSerializer())
    autofill_rule = serializers.ListField(child=AutofillRuleSerializer())
    autofill_readonly = serializers.BooleanField()
    updates_autofill = serializers.BooleanField()
    related_fields = serializers.ListField(child=serializers.CharField())
    searchable = serializers.BooleanField()
    highlight_group = serializers.CharField()
    display = serializers.CharField()
    editable = serializers.SerializerMethodField("get_editable")
    disable_fieldset_delete_add = serializers.SerializerMethodField()

    def get_editable(self, attribute):
        privilege = privilege_as_int(self.context["privilege"])
        owner = self.context["owner"]

        # owner can edit owner-editable fields regardless of their role
        if owner and attribute.owner_editable:
            return True
        # check privilege for others
        elif attribute.edit_privilege and \
            privilege >= privilege_as_int(attribute.edit_privilege):
            return True
        else:
            return False

    def get_disable_fieldset_delete_add(self, attribute):
        if attribute.value_type != Attribute.TYPE_FIELDSET:
            return None

        if attribute.data_source and not attribute.key_attribute:
            return True

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
        try:
            return ProjectPhaseFieldSetAttributeIndex.objects.get(
                phase=self.context["phase"],
                attribute__attribute_target=attribute,
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
        ).prefetch_related("structure")
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
            cell_attribute = self._create_matrix_cell_attribute(
                cell,
                section_attribute,
                self.context["owner"],
                self.context["privilege"],
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
    def _serialize_section_attribute(section_attribute, owner, privilege):
        if hasattr(section_attribute, "matrix"):
            return ProjectSectionAttributeMatrixSchemaSerializer(section_attribute).data

        serialized_attribute = ProjectSectionAttributeSchemaSerializer(
            section_attribute
        ).data

        serialized_attribute.update(AttributeSchemaSerializer(
            section_attribute.attribute,
            context={
                "phase": section_attribute.section.phase,
                "owner": owner,
                "privilege": privilege,
            }
        ).data)

        return serialized_attribute

    @staticmethod
    def _create_matrix_cell_attribute(cell, section_attribute, owner, privilege):
        cell_attribute = ProjectSectionAttributeSchemaSerializer(section_attribute).data
        cell_attribute.update(AttributeSchemaSerializer(
            section_attribute.attribute,
            context={"owner": owner, "privilege": privilege}
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
        section_attributes = list(section.projectphasesectionattribute_set.all())
        self._create_matrix_fields(PhaseAttributeMatrixCell, section_attributes)

        # Create a list of serialized fields
        data = []
        for section_attribute in section_attributes:
            data.append(self._serialize_section_attribute(
                section_attribute,
                self.context["owner"],
                self.context["privilege"],
            ))

        return data


class ProjectPhaseSchemaSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField(source="name")
    color = serializers.CharField()
    color_code = serializers.CharField()
    list_prefix = serializers.CharField()
    sections = serializers.SerializerMethodField()

    @staticmethod
    def _get_sections(privilege, owner, phase, project=None):
        sections_cache = cache.get("serialized_phase_sections", {})

        try:
            sections = sections_cache[(privilege, owner, phase)]
        except KeyError:
            sections = [
                ProjectSectionSchemaSerializer(
                    section,
                    context={"privilege": privilege, "owner": owner},
                ).data
                for section in phase.sections.all()
            ]

            sections_cache[(privilege, owner, phase)] = sections
            cache.set("serialized_phase_sections", sections_cache, None)

        confirmed_deadlines = [
            dl.deadline.attribute.identifier for dl in project.deadlines.all()
            .select_related("deadline", "project", "deadline__attribute", "deadline__confirmation_attribute")
            if dl.confirmed and dl.deadline.attribute
        ] if project else []

        for sect_i, section in enumerate(sections):
            for attr_i, attr in enumerate(section["fields"]):
                if attr["name"] in confirmed_deadlines:
                    sections[sect_i]["fields"][attr_i]["editable"] = False

        return sections

    def get_sections(self, phase):
        try:
            context = self.context
        except AttributeError:
            context = {}

        try:
            query_params = getattr(self.context["request"], "GET", {})
        except KeyError:
            query_params = {}

        try:
            project = Project.objects.prefetch_related("deadlines").get(pk=int(query_params.get("project")))
        except (ValueError, TypeError, Project.DoesNotExist):
            project = None

        return self._get_sections(
            context.get("privilege"),
            context.get("owner"),
            phase,
            project,
        )


class ProjectFloorAreaSchemaSerializer(BaseMatrixableSchemaSerializer):
    title = serializers.CharField(source="name")
    fields = serializers.SerializerMethodField("_get_fields")

    def _get_fields(self, section):
        section_attributes = list(section.projectfloorareasectionattribute_set.all().prefetch_related("attribute", "attribute__value_choices"))
        self._create_matrix_fields(
            ProjectFloorAreaSectionAttributeMatrixCell,
            section_attributes
        )

        # Create a list of serialized fields
        data = []
        for section_attribute in section_attributes:
            data.append(self._serialize_section_attribute(
                section_attribute,
                self.context["owner"],
                self.context["privilege"],
            ))

        return data


class ProjectPhaseDeadlineSectionSerializer(serializers.Serializer):
    name = serializers.CharField()
    attributes = serializers.SerializerMethodField("_get_attributes")

    @staticmethod
    def _get_serialized_attributes(sect_attrs, owner, privilege):
        serialized = []

        for sect_attr in sect_attrs:
            serialized.append(AttributeSchemaSerializer(
                sect_attr.attribute,
                context={"owner": owner, "privilege": privilege}
            ).data)

        return serialized

    def _get_attributes(self, deadline_section):
        owner = self.context.get("owner", False)
        privilege = self.context.get("privilege", False)

        if privilege == "admin":
            sect_attrs = deadline_section.projectphasedeadlinesectionattribute_set \
                .filter(admin_field=True).select_related("attribute")
        elif privilege == "browse":
            sect_attrs = []
        else:
            sect_attrs = deadline_section.projectphasedeadlinesectionattribute_set \
                .filter(owner_field=True).select_related("attribute")

        return self._get_serialized_attributes(sect_attrs, owner, privilege)


class ProjectPhaseDeadlineSectionsSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField(source="name")
    color = serializers.CharField()
    color_code = serializers.CharField()
    list_prefix = serializers.CharField()
    sections = serializers.SerializerMethodField()

    @staticmethod
    def _get_sections(privilege, owner, phase, project=None):
        sections_cache = cache.get("serialized_deadline_sections", {})

        try:
            deadline_sections = sections_cache[(privilege, owner, phase)]
        except KeyError:
            deadline_sections = [
                ProjectPhaseDeadlineSectionSerializer(
                    section,
                    context={"privilege": privilege, "owner": owner},
                ).data
                for section in phase.deadline_sections.all()
            ]

            sections_cache[(privilege, owner, phase)] = deadline_sections
            cache.set("serialized_deadline_sections", sections_cache, None)

        confirmed_deadlines = [
            dl.deadline.attribute.identifier for dl in project.deadlines.all()
            .select_related("deadline", "project", "deadline__attribute", "deadline__confirmation_attribute")
            if dl.confirmed and dl.deadline.attribute
        ] if project else []

        for sect_i, section in enumerate(deadline_sections):
            for attr_i, attr in enumerate(section["attributes"]):
                if attr["name"] in confirmed_deadlines:
                    deadline_sections[sect_i]["attributes"][attr_i]["editable"] = False

        return deadline_sections

    def get_sections(self, phase):
        try:
            context = self.context
        except AttributeError:
            context = {}

        query_params = getattr(self.context["request"], "GET", {})
        try:
            project = Project.objects.prefetch_related("deadlines").get(pk=int(query_params.get("project")))
        except (ValueError, TypeError, Project.DoesNotExist):
            project = None

        return self._get_sections(
            context.get("privilege"),
            context.get("owner"),
            phase,
            project,
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
    phases = serializers.SerializerMethodField()
    deadline_sections = serializers.SerializerMethodField()

    def get_phases(self, instance):
        query_params = getattr(self.context["request"], "GET", {})
        try:
            project = Project.objects.get(pk=int(query_params.get("project")))
        except (ValueError, TypeError, Project.DoesNotExist):
            return ProjectPhaseSchemaSerializer(
                instance.phases.all(),
                many=True,
                context=self.context,
            ).data

        return ProjectPhaseSchemaSerializer(
            instance.get_phases(project),
            many=True,
            context=self.context,
        ).data

    def get_deadline_sections(self, instance):
        query_params = getattr(self.context["request"], "GET", {})
        try:
            project = Project.objects.get(pk=int(query_params.get("project")))
        except (ValueError, TypeError, Project.DoesNotExist):
            return ProjectPhaseSchemaSerializer(
                instance.phases.all(),
                many=True,
                context=self.context,
            ).data

        return ProjectPhaseDeadlineSectionsSerializer(
            instance.get_phases(project),
            many=True,
            context=self.context,
        ).data

    def get_fields(self):
        fields = super(ProjectSubTypeSchemaSerializer, self).get_fields()
        fields["floor_area_sections"] = ProjectFloorAreaSchemaSerializer(
            many=True,
            context=self.context,
        )

        return fields

    class Meta:
        list_serializer_class = ProjectSubtypeListFilterSerializer


class BaseProjectTypeSchemaSerializer(serializers.Serializer):
    type_name = serializers.CharField(source="name")
    type = serializers.IntegerField(source="id")

    def _get_subtypes(self, obj, privilege=None):
        context = self.context
        context["privilege"] = privilege
        context["owner"] = False
        serializer = ProjectSubTypeSchemaSerializer(
            ProjectSubtype.objects.all(),
            many=True,
            context=context,
        )
        return serializer.data

def create_project_type_schema_serializer(privilege, owner):
    prefix = f"{(privilege or '').capitalize()}{('Owner' if owner else '')}"

    def get_subtypes(self, obj):
        context = self.context
        context["privilege"] = privilege
        context["owner"] = owner
        serializer = ProjectSubTypeSchemaSerializer(
            ProjectSubtype.objects.all(),
            many=True,
            context=context,
        )
        return serializer.data

    return type(
        f"{prefix}ProjectTypeSchemaSerializer",
        (BaseProjectTypeSchemaSerializer,),
        {
            "subtypes": serializers.SerializerMethodField(),
            "type_name": serializers.CharField(source="name"),
            "type": serializers.IntegerField(source="id"),
            "get_subtypes": get_subtypes,
        },
    )


AdminProjectTypeSchemaSerializer = create_project_type_schema_serializer("admin", False)
CreateProjectTypeSchemaSerializer = create_project_type_schema_serializer("create", False)
EditProjectTypeSchemaSerializer = create_project_type_schema_serializer("edit", False)
BrowseProjectTypeSchemaSerializer = create_project_type_schema_serializer("browse", False)
AdminOwnerProjectTypeSchemaSerializer = create_project_type_schema_serializer("admin", True)
CreateOwnerProjectTypeSchemaSerializer = create_project_type_schema_serializer("create", True)
EditOwnerProjectTypeSchemaSerializer = create_project_type_schema_serializer("edit", True)

class OwnerProjectTypeSchemaSerializer(serializers.Serializer):
    subtypes = serializers.SerializerMethodField()
    type_name = serializers.CharField(source="name")
    type = serializers.IntegerField(source="id")

    def get_subtypes(self, obj):
        context = self.context
        context["privilege"] = False
        context["owner"] = True
        serializer = ProjectSubTypeSchemaSerializer(
            ProjectSubtype.objects.all(),
            many=True,
            context=context,
        )
        return serializer.data


class ProjectCardSchemaSerializer(serializers.ModelSerializer):
    choices = serializers.SerializerMethodField()
    label =serializers.SerializerMethodField()
    name = serializers.CharField(source="attribute.identifier")
    section_key = serializers.CharField(source="section.key")
    section_name = serializers.CharField(source="section.name")

    def get_label(self, obj):
        return obj.custom_label or obj.attribute.name

    class Meta:
        model = ProjectCardSectionAttribute
        fields = [
            "section_id",
            "label",
            "name",
            "section_name",
            "section_key",
            "choices",
            "date_format",
            "show_on_mobile",
        ]

    @staticmethod
    @extend_schema_field(AttributeChoiceSchemaSerializer(many=True))
    def get_choices(sect_attr):
        attribute = sect_attr.attribute
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
