from rest_framework import serializers
from sitecontent.models import FooterSection, FooterLink, TargetFloorArea


class FooterLinkSerializer(serializers.ModelSerializer):
    class Meta:
        model = FooterLink
        fields = [
            "link_text",
            "url",
        ]


class FooterSectionSerializer(serializers.ModelSerializer):
    links = FooterLinkSerializer(many=True)

    class Meta:
        model = FooterSection
        fields = [
            "title",
            "links",
        ]
