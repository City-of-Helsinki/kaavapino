from django.contrib.auth import get_user_model
from drf_spectacular.utils import extend_schema_field
from drf_spectacular.types import OpenApiTypes
from rest_framework import serializers

from users.models import privilege_as_label


class UserSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="uuid")
    privilege_name = serializers.SerializerMethodField()
    role_name = serializers.SerializerMethodField()

    @extend_schema_field(OpenApiTypes.STR)
    def get_privilege_name(self, user):
        return privilege_as_label(user.privilege)

    @extend_schema_field(OpenApiTypes.STR)
    def get_role_name(self, user):
        groups = list(getattr(user, "all_groups", []) or [])
        if not groups:
            return None

        def privilege_rank(g):
            gp = getattr(g, "groupprivilege", None)
            return getattr(gp, "as_int", -1)

        role = max(groups, key=privilege_rank, default=None)
        return getattr(role, "name", None) if role else None

    class Meta:
        model = get_user_model()
        fields = [
            "id",
            "department_name",
            "first_name",
            "last_name",
            "is_active",
            "is_staff",
            "email",
            "privilege",
            "privilege_name",
            "role_name",
            "ad_id",
        ]


class PersonnelSerializer(serializers.Serializer):
    id = serializers.CharField()
    name = serializers.SerializerMethodField()
    phone = serializers.SerializerMethodField()
    company = serializers.SerializerMethodField()
    email = serializers.CharField(source="mail")
    title = serializers.CharField(source="jobTitle")
    office = serializers.CharField(source="officeLocation")

    @extend_schema_field(OpenApiTypes.STR)
    def get_name(self, user):
        return " ".join([
            name for name in [user["givenName"], user["surname"]] if name
        ])

    @extend_schema_field(OpenApiTypes.STR)
    def get_phone(self, user):
        business_phones = user["businessPhones"]
        if business_phones and len(business_phones) > 0:
            return business_phones[0].replace('+358', '0')
        return user["mobilePhone"]

    @extend_schema_field(OpenApiTypes.STR)
    def get_company(self, user):
        try:
            return {
                "KYMP": "Kaupunkiympäristön toimiala",
                "KUVA": "Kulttuurin ja vapaa-ajan toimiala",
                "KASKO": "Kasvatuksen ja koulutuksen toimiala",
                "SOTE": "Sosiaali- ja terveystoimiala",
                "KEHA": "Keskushallinto"
            }[user["companyName"]]
        except KeyError:
            return None
