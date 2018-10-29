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
        ]
