"""
Rebuildable index of articles, and a repository wrapper that lists from it.

    files (source of truth) ──sync──▶ ArticleIndex (ORM projection)
                                         │
    IndexedArticleRepository.list() ◀────┘   get()/writes ──▶ backend (files)

How the index follows the files:

* **Writes through the repository** update the affected rows immediately
  (inside the backend's write lock, re-reading the file that was written).
* **Git backend**: ``sync()`` asks Git for the files changed between the last
  indexed commit and HEAD and reprocesses only those (the planner from
  ``feincms3_filecontent.sync``). Unknown or missing previous commit, or a
  different root, means a full rebuild.
* **Filesystem backend**: ``sync()`` compares each file's mtime/size with the
  stored values and reparses only what changed (no file reads otherwise).
* Changes made behind the repository's back (``git pull`` on the shell, hand
  edits) appear after the next ``sync()`` — run by the repository sync API,
  ``./manage.py content_index`` or the first listing on an empty index.

``list()`` returns ``ArticleSummary`` objects (no body). ``get()`` always reads
the file, so the full article never comes from the index.
"""

import logging
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone
from feincms3_filecontent.content.documents import content_hash
from feincms3_filecontent.sync.changes import plan

from . import schemas
from .exceptions import DocumentNotFound, InvalidDocument
from .models import ArticleIndex, IndexState
from .repository import ORDER_OLDEST_FIRST, ArticleFilter, ContentRepository


logger = logging.getLogger(__name__)

STATE_NAME = "articles"


@dataclass(frozen=True)
class ArticleSummary:
    """What a listing needs; deliberately has no ``body``."""

    key: schemas.ArticleKey
    title: str
    status: str
    publication_date: object
    category: str
    version: str

    market = property(lambda self: self.key.market)
    locale = property(lambda self: self.key.locale)
    slug = property(lambda self: self.key.slug)
    id = property(lambda self: self.key.id)

    @property
    def is_draft(self):
        return self.status == schemas.STATUS_DRAFT

    def is_published(self, now=None):
        return self.status == schemas.STATUS_PUBLISHED and self.publication_date <= (
            now or timezone.now()
        )

    @classmethod
    def from_row(cls, row):
        return cls(
            key=schemas.ArticleKey(row.market, row.locale, row.slug),
            title=row.title,
            status=row.status,
            publication_date=row.publication_date,
            category=row.category,
            version=row.version,
        )


@dataclass
class IndexResult:
    mode: str  # "noop", "incremental", "full"
    upserted: int = 0
    deleted: int = 0
    invalid: int = 0
    reason: str = ""

    def as_dict(self):
        return dict(self.__dict__)


class ArticleIndexer:
    def __init__(self, backend):
        self.backend = backend

    # State ---------------------------------------------------------------

    def state(self):
        return IndexState.objects.filter(name=STATE_NAME).first()

    def _git(self):
        git = getattr(self.backend, "git", None)
        return git if git is not None and git.exists() else None

    def _head(self):
        git = self._git()
        return git.current_sha() if git else None

    def _save_state(self, *, mode, sha):
        IndexState.objects.update_or_create(
            name=STATE_NAME,
            defaults={
                "root": str(self.backend.root),
                "backend": self.backend.backend,
                "last_indexed_sha": sha or "",
                "last_mode": mode,
                "indexed_at": timezone.now(),
                "last_error": "",
            },
        )

    def is_current_root(self, state):
        return (
            state is not None
            and state.root == str(self.backend.root)
            and state.backend == self.backend.backend
        )

    # Rows -------------------------------------------------------------------

    def _row(self, key):
        """An unsaved row for ``key`` read from the file; ``None`` if missing."""
        try:
            stat = self.backend.stat(key)
            article = self.backend.get(key)
        except DocumentNotFound:
            return None
        except InvalidDocument as exc:
            return ArticleIndex(
                market=key.market,
                locale=key.locale,
                slug=key.slug,
                version=content_hash(
                    self.backend.store.read_bytes(self.backend.path_for(key))
                ),
                mtime_ns=stat.mtime_ns,
                size=stat.size,
                error=str(exc),
            )
        return ArticleIndex(
            market=key.market,
            locale=key.locale,
            slug=key.slug,
            title=article.title,
            status=article.status,
            category=article.category,
            publication_date=article.publication_date,
            version=article.version,
            mtime_ns=stat.mtime_ns,
            size=stat.size,
        )

    def _upsert(self, key):
        row = self._row(key)
        rows = ArticleIndex.objects.filter(
            market=key.market, locale=key.locale, slug=key.slug
        )
        if row is None:
            rows.delete()
            return None
        fields = {
            f.name: getattr(row, f.name)
            for f in ArticleIndex._meta.concrete_fields
            if f.name not in {"id", "market", "locale", "slug", "indexed_at"}
        }
        ArticleIndex.objects.update_or_create(
            market=key.market, locale=key.locale, slug=key.slug, defaults=fields
        )
        return row

    def _delete(self, keys):
        for key in keys:
            ArticleIndex.objects.filter(
                market=key.market, locale=key.locale, slug=key.slug
            ).delete()

    # Public -----------------------------------------------------------------

    def refresh(self, keys):
        """Re-read ``keys`` from their files (write-through)."""
        with transaction.atomic():
            for key in keys:
                self._upsert(key)

    @transaction.atomic
    def rebuild(self, reason="requested"):
        head = self._head()
        ArticleIndex.objects.all().delete()
        rows = [row for key in self.backend.article_keys() if (row := self._row(key))]
        ArticleIndex.objects.bulk_create(rows, batch_size=500)
        self._save_state(mode="full", sha=head)
        return IndexResult(
            "full",
            upserted=len(rows),
            invalid=sum(1 for r in rows if r.error),
            reason=reason,
        )

    def sync(self, *, full=False):
        try:
            return self._sync(full=full)
        except Exception as exc:
            IndexState.objects.update_or_create(
                name=STATE_NAME, defaults={"last_error": str(exc)}
            )
            raise

    def _sync(self, *, full):
        state = self.state()
        if full:
            return self.rebuild()
        if not self.is_current_root(state):
            return self.rebuild("no index for this content root")
        git = self._git()
        if git is not None:
            head = git.current_sha()
            mode, info = plan(git, state.last_indexed_sha, head)
            if mode == "full":
                return self.rebuild(info)
            if mode == "noop":
                return IndexResult("noop")
            return self._apply_changes(info, head)
        return self._sync_by_stat()

    @transaction.atomic
    def _apply_changes(self, changeset, head):
        to_key = self.backend.key_for_path
        deleted = [k for p in changeset.deletions if (k := to_key(p))]
        upserts = [k for p in changeset.upserts if (k := to_key(p))]
        self._delete(deleted)
        invalid = 0
        for key in upserts:
            row = self._upsert(key)
            invalid += bool(row is not None and row.error)
        self._save_state(mode="incremental", sha=head)
        return IndexResult(
            "incremental", upserted=len(upserts), deleted=len(deleted), invalid=invalid
        )

    @transaction.atomic
    def _sync_by_stat(self):
        known = {
            (r.market, r.locale, r.slug): (r.mtime_ns, r.size)
            for r in ArticleIndex.objects.only(
                "market", "locale", "slug", "mtime_ns", "size"
            )
        }
        upserted = invalid = 0
        seen = set()
        for key in self.backend.article_keys():
            ident = (key.market, key.locale, key.slug)
            seen.add(ident)
            stat = self.backend.stat(key)
            if known.get(ident) == (stat.mtime_ns, stat.size):
                continue
            row = self._upsert(key)
            upserted += 1
            invalid += bool(row is not None and row.error)
        gone = [schemas.ArticleKey(*ident) for ident in set(known) - seen]
        self._delete(gone)
        self._save_state(mode="incremental", sha=None)
        mode = "incremental" if upserted or gone else "noop"
        return IndexResult(mode, upserted=upserted, deleted=len(gone), invalid=invalid)

    def status(self):
        state = self.state()
        data = {
            "rows": ArticleIndex.objects.count(),
            "invalid": ArticleIndex.objects.exclude(error="").count(),
        }
        if state is None or not self.is_current_root(state):
            return {**data, "state": "missing"}
        head = self._head()
        data.update(
            last_mode=state.last_mode,
            indexed_at=state.indexed_at.isoformat() if state.indexed_at else None,
            last_error=state.last_error,
            last_indexed_sha=state.last_indexed_sha,
        )
        if head is not None:
            data["state"] = "current" if state.last_indexed_sha == head else "stale"
        else:
            data["state"] = "unknown"  # filesystem: only a sync can tell
        return data


class IndexedArticleRepository(ContentRepository):
    """
    Wraps any article backend. Listing and counting use the index; everything
    else is delegated, and writes refresh the index for the keys they touch.
    """

    def __init__(self, inner):
        self.inner = inner
        self.indexer = ArticleIndexer(inner)

    def __getattr__(self, name):
        # root, markets, describe_location, last_commit, lock, … of the backend.
        return getattr(self.inner, name)

    @property
    def backend(self):
        return self.inner.backend

    @property
    def capabilities(self):
        return self.inner.capabilities | {"index", "count"}

    def __repr__(self):
        return f"<IndexedArticleRepository {self.inner!r}>"

    # Reading -------------------------------------------------------------

    def _ensure_index(self):
        if not self.indexer.is_current_root(self.indexer.state()):
            self.indexer.sync()

    def _queryset(self, query):
        self._ensure_index()
        qs = ArticleIndex.objects.filter(error="")
        if query.market:
            qs = qs.filter(market=query.market)
        if query.locale:
            qs = qs.filter(locale=query.locale)
        if query.category:
            qs = qs.filter(category=query.category)
        if query.status:
            qs = qs.filter(status=query.status)
        if query.published_only:
            qs = qs.filter(
                status=schemas.STATUS_PUBLISHED, publication_date__lte=timezone.now()
            )
        return qs

    def list(self, query=None):
        query = query or ArticleFilter()
        qs = self._queryset(query)
        if query.order == ORDER_OLDEST_FIRST:
            qs = qs.order_by("publication_date", "market", "locale", "slug")
        else:
            qs = qs.order_by("-publication_date", "market", "locale", "slug")
        end = None if query.limit is None else query.offset + query.limit
        return [ArticleSummary.from_row(row) for row in qs[query.offset : end]]

    def count(self, query=None):
        return self._queryset(query or ArticleFilter()).count()

    def invalid_documents(self):
        self._ensure_index()
        return {
            f"{r.market}/{r.locale}/{r.slug}": {"document": [r.error]}
            for r in ArticleIndex.objects.exclude(error="")
        }

    def get(self, key):
        return self.inner.get(key)

    def exists(self, key):
        return self.inner.exists(key)

    # Writing (write-through) ------------------------------------------------

    def _write(self, keys, operation):
        with self.inner.lock:
            git = self.indexer._git()
            before = git.current_sha() if git else None
            result = operation()
            self.indexer.refresh(keys)
            state = self.indexer.state()
            if (
                git
                and self.indexer.is_current_root(state)
                and state.last_indexed_sha == before
            ):
                # Nothing else changed since the last sync: our commit is the
                # only difference, and it is indexed now.
                IndexState.objects.filter(pk=state.pk).update(
                    last_indexed_sha=git.current_sha() or ""
                )
            return result

    def create(self, article, *, context=None):
        return self._write(
            [article.key], lambda: self.inner.create(article, context=context)
        )

    def update(self, key, article, *, expected_version=None, context=None):
        return self._write(
            [key, article.key],
            lambda: self.inner.update(
                key, article, expected_version=expected_version, context=context
            ),
        )

    def delete(self, key, *, expected_version=None, context=None):
        return self._write(
            [key],
            lambda: self.inner.delete(
                key, expected_version=expected_version, context=context
            ),
        )

    def restore(self, key, version, *, expected_version=None, context=None):
        return self._write(
            [key],
            lambda: self.inner.restore(
                key, version, expected_version=expected_version, context=context
            ),
        )

    def commit(self, keys, *, context):
        return self._write(keys, lambda: self.inner.commit(keys, context=context))

    # Delegated versioned operations --------------------------------------------

    def history(self, key, **kwargs):
        return self.inner.history(key, **kwargs)

    def diff(self, key, from_version, to_version=None):
        return self.inner.diff(key, from_version, to_version)

    def sync(self):
        """Backend sync (Git: fetch/fast-forward/push), then index sync."""
        status = self.inner.sync() if hasattr(self.inner, "sync") else {}
        result = self.indexer.sync()
        return {**(status or self.inner.status()), "index": result.as_dict()}

    def status(self):
        return {**self.inner.status(), "index": self.indexer.status()}
