"""
ContentRepository: the only door to editorial content.

Callers (API views, public views, templates) talk in content operations —
list articles of a market/locale, get one by key, create, update, delete —
never in files, paths or QuerySets. Backends decide where documents live:

    ContentRepository
        ├── FilesystemArticleRepository   (implemented: content/{market}/{locale}/articles/*.md)
        └── GitArticleRepository          (app/content/git.py: + history/diff/restore)

Capabilities that only a versioned backend can offer (``history``, ``diff``,
``restore``, ``commit``) are part of the interface so call sites are written
against it once; the plain filesystem backend raises ``OperationNotSupported``
and every backend advertises what it supports in ``capabilities``.
"""

import abc
from dataclasses import dataclass

from .exceptions import OperationNotSupported


ORDER_NEWEST_FIRST = "-publication_date"
ORDER_OLDEST_FIRST = "publication_date"


@dataclass(frozen=True)
class ArticleFilter:
    """What to list. ``None`` means "any"."""

    market: str | None = None
    locale: str | None = None
    category: str | None = None
    status: str | None = None  # "draft" / "published" (as stored)
    published_only: bool = False  # status=published AND publication_date <= now
    order: str = ORDER_NEWEST_FIRST


@dataclass(frozen=True)
class ChangeContext:
    """
    Who is changing content and why. Unused by the filesystem backend, but a
    Git backend turns it into the commit author and message, so call sites
    pass it from day one.
    """

    author_name: str = ""
    author_email: str = ""
    message: str = ""


class ContentRepository(abc.ABC):
    backend = "abstract"
    capabilities = frozenset({"list", "get", "create", "update", "delete", "exists"})

    # Reading ----------------------------------------------------------------

    @abc.abstractmethod
    def list(self, query=None):
        """Return articles matching ``query`` (an ``ArticleFilter``), ordered."""

    @abc.abstractmethod
    def get(self, key):
        """Return the article at ``key`` or raise ``DocumentNotFound``."""

    @abc.abstractmethod
    def exists(self, key): ...

    # Writing ----------------------------------------------------------------

    @abc.abstractmethod
    def create(self, article, *, context=None):
        """Store a new article; ``DocumentAlreadyExists`` if the key is taken."""

    @abc.abstractmethod
    def update(self, key, article, *, expected_version=None, context=None):
        """
        Replace the article at ``key`` with ``article`` (whose key may differ:
        that is a move). ``expected_version`` enables optimistic locking.
        """

    @abc.abstractmethod
    def delete(self, key, *, expected_version=None, context=None): ...

    # Versioned backends only ---------------------------------------------------

    def history(self, key):
        raise OperationNotSupported("history requires a versioned backend")

    def diff(self, key, from_version, to_version=None):
        raise OperationNotSupported("diff requires a versioned backend")

    def commit(self, keys, *, context):
        raise OperationNotSupported("commit requires a versioned backend")

    def restore(self, key, version, *, expected_version=None, context=None):
        """Write the content ``key`` had at ``version`` as a *new* change."""
        raise OperationNotSupported("restore requires a versioned backend")

    def status(self):
        """Backend health for UIs and monitoring (no secrets, no paths)."""
        return {"backend": self.backend, "capabilities": sorted(self.capabilities)}

    def move(self, key, new_key, *, expected_version=None, context=None):
        article = self.get(key)
        return self.update(
            key,
            article.with_key(new_key),
            expected_version=expected_version,
            context=context,
        )
