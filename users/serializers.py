from django.contrib.auth import get_user_model
from rest_framework import serializers

from users.models import privilege_as_label


class UserSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="uuid")
    privilege_name = serializers.SerializerMethodField()
    role_name = serializers.SerializerMethodField()

    def get_privilege_name(self, user):
        return privilege_as_label(user.privilege)

    def get_role_name(self, user):
        if not user.all_groups.count():
            return None

        role = user.all_groups[0]
        for group in user.all_groups:
            if role.groupprivilege.as_int < group.groupprivilege.as_int:
                role = group

        if not role:
            return None

        return role.name

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
        ]


class PersonnelSerializer(serializers.Serializer):
    id = serializers.CharField()
    name = serializers.SerializerMethodField()
    phone = serializers.CharField(source="mobilePhone")
    email = serializers.CharField(source="mail")
    title = serializers.CharField(source="jobTitle")
    office = serializers.CharField(source="officeLocation")

    def get_name(self, user):
        return " ".join([
            name for name in [user["givenName"], user["surname"]] if name
        ])



class PersonnelDetailSerializer(PersonnelSerializer):
    def get_fields(self):
        fields = super(PersonnelDetailSerializer, self).get_fields()
        fields["company"] = serializers.SerializerMethodField()
        return fields

    def get_company(self, user):
        try:
            return {
                "KYMP": "Kaupunkiympäristön toimiala",
                "KUVA": "Kulttuurin ja vapaa-ajan toimiala",
                "KASKO": "kasvatuksen ja koulutuksen toimiala",
                "SOTE": "sosiaali- ja terveystoimiala",
                "KEHA": "Keskushallinto"
            }[user["companyName"]]
        except KeyError:
            return None
