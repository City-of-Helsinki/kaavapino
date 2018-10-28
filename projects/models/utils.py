import hashlib

from django.utils.encoding import force_bytes
from django.utils.text import slugify


def create_identifier(text):
    return slugify(text).replace("-", "_")


def truncate_identifier(identifier: str, length: int = None, hash_len: int = 4):
    """Shorten an identifier to a repeatable mangled version with the given length."""
    if length is None or len(identifier) <= length:
        return identifier

    digest = hashlib.sha1(force_bytes(identifier)).hexdigest()[:hash_len]

    return f"{identifier[: length - hash_len]}{digest}"
