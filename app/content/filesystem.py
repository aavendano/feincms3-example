"""
Filesystem backend::

    <root>/<MARKET>/<locale>/articles/<slug>.md

Market, locale and slug come from the path; everything else from the file.
Low-level safety (path normalization, refusing anything that resolves outside
the root, atomic temp-file + fsync + rename writes, inter-process locking) is
delegated to the primitives of ``feincms3_filecontent`` so this module only
deals with article semantics.
"""

from dataclasses import replace
from pathlib import Path

from django.utils import timezone
from feincms3_filecontent.exceptions import (
    DocumentNotFound as StoreNotFound,
    UnsafePathError,
)
from feincms3_filecontent.repository.base import RepositoryLock
from feincms3_filecontent.storage.filesystem import FileSystemContentStore

from . import schemas
from .exceptions import (
    DocumentAlreadyExists,
    DocumentNotFound,
    InvalidDocument,
    InvalidPath,
    VersionConflict,
)
from .repository import ORDER_OLDEST_FIRST, ArticleFilter, ContentRepository


ARTICLES_DIR = "articles"
SUFFIX = ".md"
LOCK_NAME = ".content.lock"


class FilesystemArticleRepository(ContentRepository):
    backend = "filesystem"

    def __init__(self, root, *, markets, lock_timeout=10):
        """
        ``markets`` maps market codes to their enabled locales, e.g.
        ``{"CA": ["en", "fr"], "US": ["en", "es"]}``. Only these directories
        are read or written.
        """
        self.root = Path(root).resolve()
        self.markets = {market: tuple(locales) for market, locales in markets.items()}
        self.store = FileSystemContentStore(self.root)
        self.lock = RepositoryLock(self.root / LOCK_NAME, timeout=lock_timeout)

    def __repr__(self):
        return f"<FilesystemArticleRepository {self.root}>"

    # Paths (private: nothing outside this class sees them) ------------------

    def _path(self, key):
        key.validate(markets=self.markets)
        path = f"{key.market}/{key.locale}/{ARTICLES_DIR}/{key.slug}{SUFFIX}"
        try:
            self.store.resolve(path)
        except UnsafePathError as exc:
            raise InvalidPath({"path": [str(exc)]}) from exc
        return path

    def describe_location(self, key):
        """Human-readable location for UIs ("content/CA/en/articles/x.md")."""
        return f"{self.root.name}/{self._path(key)}"

    # Reading ----------------------------------------------------------------

    def _read(self, key):
        path = self._path(key)
        try:
            text = self.store.read(path)
        except StoreNotFound:
            raise DocumentNotFound(key.id) from None
        return schemas.parse(key, text)

    def get(self, key):
        return self._read(key)

    def exists(self, key):
        return self.store.exists(self._path(key))

    def article_keys(self, market=None, locale=None):
        """Keys of every article file (valid or not), without reading them."""
        return self._keys(market, locale)

    def key_for_path(self, path):
        """
        Inverse of the path layout: ``"CA/en/articles/x.md"`` -> key, or
        ``None`` for anything that is not an article of a configured market.
        """
        parts = path.split("/")
        if len(parts) != 4 or parts[2] != ARTICLES_DIR or not parts[3].endswith(SUFFIX):
            return None
        key = schemas.ArticleKey(parts[0], parts[1], parts[3][: -len(SUFFIX)])
        try:
            key.validate(markets=self.markets)
        except InvalidDocument:
            return None
        return key

    def path_for(self, key):
        """Path relative to the root (for indexes and Git; never sent to browsers)."""
        return self._path(key)

    def stat(self, key):
        try:
            return self.store.stat(self._path(key))
        except StoreNotFound:
            raise DocumentNotFound(key.id) from None

    def _keys(self, market=None, locale=None):
        for mkt, locales in sorted(self.markets.items()):
            if market and mkt != market:
                continue
            for loc in locales:
                if locale and loc != locale:
                    continue
                prefix = f"{mkt}/{loc}/{ARTICLES_DIR}"
                for path in self.store.list(prefix, suffixes=(SUFFIX,)):
                    name = path.rsplit("/", 1)[-1][: -len(SUFFIX)]
                    if path.count("/") != 3 or not schemas.SLUG_RE.match(name):
                        continue  # nested folders / odd names are not articles
                    yield schemas.ArticleKey(mkt, loc, name)

    def list(self, query=None):
        """
        Articles matching ``query``. Invalid files are skipped here and
        reported by ``invalid_documents()`` so one bad file cannot take the
        whole listing down.
        """
        query = query or ArticleFilter()
        now = timezone.now()
        articles = []
        for key in self._keys(query.market, query.locale):
            try:
                article = self._read(key)
            except (InvalidDocument, DocumentNotFound):
                continue
            if query.category and article.category != query.category:
                continue
            if query.status and article.status != query.status:
                continue
            if query.published_only and not article.is_published(now):
                continue
            articles.append(article)
        # Stable sorts: ties on the date always fall back to id order.
        articles.sort(key=lambda a: a.id)
        articles.sort(
            key=lambda a: a.publication_date,
            reverse=query.order != ORDER_OLDEST_FIRST,
        )
        end = None if query.limit is None else query.offset + query.limit
        return articles[query.offset : end]

    def count(self, query=None):
        query = query or ArticleFilter()
        return len(self.list(replace(query, limit=None, offset=0)))

    def invalid_documents(self):
        """``{article id: errors}`` for files that cannot be parsed."""
        problems = {}
        for key in self._keys():
            try:
                self._read(key)
            except InvalidDocument as exc:
                problems[key.id] = exc.errors
        return problems

    # Writing ----------------------------------------------------------------

    def _write(self, key, article):
        """Serialize, re-parse (validation round-trip), then write atomically."""
        text = schemas.serialize(article.with_key(key))
        stored = schemas.parse(key, text)
        self.store.write(self._path(key), text)
        return stored

    def _check_version(self, current, expected_version):
        if expected_version is not None and current.version != expected_version:
            raise VersionConflict(current.version)

    def create(self, article, *, context=None):
        key = article.key
        with self.lock:
            if self.exists(key):
                raise DocumentAlreadyExists(key.id)
            return self._write(key, article)

    def update(self, key, article, *, expected_version=None, context=None):
        new_key = article.key
        with self.lock:
            current = self._read(key)
            self._check_version(current, expected_version)
            if new_key != key and self.exists(new_key):
                raise DocumentAlreadyExists(new_key.id)
            stored = self._write(new_key, article)
            if new_key != key:
                # Write the new location first: a crash in between leaves a
                # duplicate (visible, recoverable), never a lost article.
                self.store.delete(self._path(key))
            return stored

    def delete(self, key, *, expected_version=None, context=None):
        with self.lock:
            current = self._read(key)
            self._check_version(current, expected_version)
            self.store.delete(self._path(key))
