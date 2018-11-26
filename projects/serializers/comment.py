from rest_framework import serializers

from projects.models import ProjectComment


class CommentSerializer(serializers.ModelSerializer):
    user = serializers.SlugRelatedField(read_only=True, slug_field="uuid")

    class Meta:
        model = ProjectComment
        fields = ["id", "project", "user", "created_at", "modified_at", "content"]
        read_only_fields = ["id", "project", "user", "created_at", "modified_at"]

    def create(self, validated_data: dict) -> ProjectComment:
        validated_data["user"] = self.context["request"].user
        validated_data["project"] = self.context.get("parent_instance")
        return super().create(validated_data)
