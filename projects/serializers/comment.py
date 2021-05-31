from django.utils.translation import gettext_lazy as _
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from projects.models import (
    FieldComment,
    ProjectComment,
    LastReadTimestamp,
    Attribute,
    FieldCommentFieldsetPathLocation,
)
from users.serializers import UserSerializer


class CommentSerializer(serializers.ModelSerializer):
    user = serializers.SlugRelatedField(read_only=True, slug_field="uuid")
    _metadata = serializers.SerializerMethodField()

    def get__metadata(self, comment):
        if not comment.user:
            return {"users": []}
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


class FieldsetPathSerializer(serializers.Serializer):
    parent = serializers.SlugRelatedField(
        read_only=False,
        slug_field="identifier",
        queryset=Attribute.objects.all(),
    )
    index = serializers.IntegerField()


class FieldCommentSerializer(CommentSerializer):
    field = serializers.SlugRelatedField(
        read_only=False, slug_field="identifier", queryset=Attribute.objects.all()
    )
    fieldset_path = FieldsetPathSerializer(
        many=True,
        required=False,
    )
    class Meta(CommentSerializer.Meta):
        model = FieldComment
        fields = CommentSerializer.Meta.fields + ["field", "fieldset_path"]

    def create(self, validated_data):
        fieldset_path = validated_data.pop("fieldset_path", [])
        comment = super().create(validated_data)
        for i, location in enumerate(fieldset_path):
            FieldCommentFieldsetPathLocation.objects.create(
                target=comment,
                index=i,
                child_index=location["index"],
                parent_fieldset=location["parent"],
            )

        return comment


class LastReadTimestampSerializer(serializers.ModelSerializer):
    user = serializers.SlugRelatedField(read_only=True, slug_field="uuid")

    class Meta:
        model = LastReadTimestamp
        fields = [
            "project",
            "user",
            "timestamp",
        ]
        read_only_fields = [
            "project",
            "user",
        ]

    def create(self, validated_data: dict) -> ProjectComment:
        validated_data["user"] = self.context["request"].user
        validated_data["project"] = self.context.get("parent_instance")
        return super().create(validated_data)
