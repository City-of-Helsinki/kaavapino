from django.utils.translation import ugettext_lazy as _
from extended_choices import Choices

GROUPS = Choices(
    ("ADMINISTRATOR", "admin", _("Administrator")),
    ("SECRETARY", "secretary", _("Secretary")),
    ("PLANNER", "planner", _("Planner")),
)

GROUPS.add_subset("ADMINISTRATIVE_PERSONNEL", ("ADMINISTRATOR", "SECRETARY"))
