from django.contrib.auth import get_user_model
from rest_framework import serializers


class UserSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="uuid")

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
