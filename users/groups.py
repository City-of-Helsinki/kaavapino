from extended_choices import Choices
from django.utils.translation import ugettext_lazy as _


GROUPS = Choices(
    ("ADMINISTRATOR", "admin", _("Administrator")),
    ("SECRETARY", "secretary", _("Secretary")),
    ("EXPERT", "expert", _("Expert")),
    ("PLANNER", "planner", _("Planner")),
)
