from rest_framework import serializers

from projects.models import ProjectComment
from users.serializers import UserSerializer


class CommentSerializer(serializers.ModelSerializer):
    user = serializers.SlugRelatedField(read_only=True, slug_field="uuid")
    _metadata = serializers.SerializerMethodField()

    def get__metadata(self, comment):
        return {"users": UserSerializer([comment.user], many=True).data}

    class Meta:
        model = ProjectComment
        fields = [
            "id",
            "project",
            "user",
            "created_at",
            "modified_at",
            "content",
            "generated",
            "_metadata",
        ]
        read_only_fields = [
            "id",
            "project",
            "user",
            "created_at",
            "modified_at",
            "generated",
            "_metadata",
        ]

    def create(self, validated_data: dict) -> ProjectComment:
        validated_data["user"] = self.context["request"].user
        validated_data["project"] = self.context.get("parent_instance")
        return super().create(validated_data)
