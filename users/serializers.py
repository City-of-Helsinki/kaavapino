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
    name = serializers.CharField(source="displayName")
    phone = serializers.CharField(source="mobilePhone")
    email = serializers.CharField(source="mail")
    title = serializers.CharField(source="jobTitle")
    office = serializers.CharField(source="officeLocation")
