import hashlib
from dataclasses import dataclass, field
from datetime import datetime


def content_hash(data):
    """SHA-256 of the raw file bytes; used for change detection and locking."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class Document:
    """
    A file normalized for feincms3.

    The document is a pure value object: it knows nothing about Git, the
    database or the filesystem it came from.
    """

    path: str
    content_type: str
    locale: str
    slug: str
    title: str
    metadata: dict = field(hash=False)
    body: str = field(repr=False)
    content_hash: str = ""
    modified_at: datetime | None = None

    def get(self, key, default=None):
        return self.metadata.get(key, default)
