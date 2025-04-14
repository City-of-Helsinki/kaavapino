import ast
import operator
import hashlib

from django.utils.encoding import force_bytes, force_text
from django.utils.text import slugify
from private_storage.storage.files import PrivateFileSystemStorage
from projects.models.deadline import Deadline
from projects.models.attribute import Attribute

def clean_attribute_data_for_preview(attribute_data: dict) -> dict:
    """Ensures all values are JSON-serializable. Avoids double-serializing already-clean values."""
    cleaned = {}

    attributes = Attribute.objects.filter(identifier__in=attribute_data.keys()).prefetch_related("value_choices")

    for attr in attributes:
        raw_value = attribute_data.get(attr.identifier)

        # Skip serialize_value if the value is already JSON-safe (e.g., string or list of strings)
        if isinstance(raw_value, (str, int, bool, float, type(None))):
            cleaned[attr.identifier] = raw_value
        elif isinstance(raw_value, list) and all(isinstance(v, (str, int, bool, float)) for v in raw_value):
            cleaned[attr.identifier] = raw_value
        else:
            cleaned[attr.identifier] = attr.serialize_value(raw_value)

    return cleaned

def normalize_identifier_list(lst):
    return [str(x).strip() for x in (lst or [])]

def get_applicable_deadlines_for_project(project):
    # Ensure we can access subtype through phase
    if not project.phase or not project.phase.project_subtype:
        return Deadline.objects.none()

    return Deadline.objects.filter(
        subtype=project.phase.project_subtype,
        phase=project.phase,
    ).select_related("attribute")


def create_identifier(text):
    return slugify(text).replace("-", "_")


def check_identifier(identifier):
    return slugify(identifier).replace("-", "_") == identifier


def truncate_identifier(identifier: str, length: int = None, hash_len: int = 4):
    """Shorten an identifier to a repeatable mangled version with the given length."""
    if length is None or len(identifier) <= length:
        return identifier

    digest = hashlib.sha1(force_bytes(identifier)).hexdigest()[:hash_len]

    return f"{identifier[: length - hash_len]}{digest}"


class KaavapinoPrivateStorage(PrivateFileSystemStorage):
    def __init__(self, url_postfix=None, *args, **kwargs):
        self.url_postfix = url_postfix
        super().__init__(*args, **kwargs)

    def url(self, name):
        # Make sure reverse_lazy() is evaluated, as Python 3 won't do this here.
        if self.url_postfix:
            self.base_url = force_text(self.base_url).replace(
                f"/{self.url_postfix}", ""
            )
        return super(PrivateFileSystemStorage, self).url(name)


binOps = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.USub: operator.neg,
}


def arithmetic_eval(s):
    node = ast.parse(s, mode="eval")  # noqa

    def _eval(node):
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        elif isinstance(node, ast.Str):
            return node.s
        elif isinstance(node, ast.Num):
            return node.n
        elif isinstance(node, ast.BinOp):
            return binOps[type(node.op)](_eval(node.left), _eval(node.right))
        elif isinstance(node, ast.UnaryOp):  # <operator> <operand> e.g., -1
            return binOps[type(node.op)](_eval(node.operand))
        else:
            raise Exception("Unsupported type {}".format(node))

    return _eval(node.body)
