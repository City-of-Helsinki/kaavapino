from django.db import models
from django.urls import reverse_lazy
from django.utils.text import slugify
from django.utils.translation import ugettext_lazy as _

from projects.models import Attribute


class FooterLink(models.Model):
    link_text = models.CharField(max_length=255, verbose_name=_("link text"))
    url = models.CharField(max_length=255, verbose_name=_("url"))
    index = models.PositiveIntegerField(verbose_name=_("index"), default=0)
    section = models.ForeignKey(
        "FooterSection",
        verbose_name=_("section"),
        related_name="links",
        null=False,
        on_delete=models.CASCADE,
    )

    class Meta:
        verbose_name = _("footer link")
        verbose_name_plural = _("footer links")
        ordering = ("index",)

    def __str__(self):
        return self.link_text


class FooterSection(models.Model):
    title = models.CharField(max_length=255, verbose_name=_("title"))
    index = models.PositiveIntegerField(verbose_name=_("index"), default=0)

    class Meta:
        verbose_name = _("footer section")
        verbose_name_plural = _("footer sections")
        ordering = ("index",)

    def __str__(self):
        return self.title


class ListViewAttributeColumn(models.Model):
    """Defines custom ordering of attribute columns in project list view"""
    index = models.PositiveIntegerField(default=0)
    attribute = models.OneToOneField( \
        Attribute, primary_key=True, on_delete=models.CASCADE)

    class Meta(object):
        verbose_name = _("list view attribute column")
        verbose_name_plural = _("list view attribute columns")
        ordering = ("index",)


class TargetFloorArea(models.Model):
    """Defines a yearly floor area target"""
    year = models.IntegerField(
        unique=True,
        verbose_name=_("year"),
    )
    target = models.IntegerField(
        verbose_name=_("area target"),
    )
