import ast
import operator
import hashlib

from django.utils.encoding import force_bytes, force_text
from django.utils.text import slugify
from private_storage.storage.files import PrivateFileSystemStorage
from projects.models.deadline import Deadline

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
