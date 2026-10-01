import logging

from ..content.documents import content_hash
from ..exceptions import DocumentNotFound, DocumentValidationError, FileContentError
from ..models import ContentIndex


logger = logging.getLogger(__name__)


class Projector:
    """Projects documents from the ContentStore into ``ContentIndex`` rows."""

    def __init__(self, store, registry, validator):
        self.store = store
        self.registry = registry
        self.validator = validator

    def build(self, path, git_sha=""):
        """Return an unsaved ``ContentIndex`` for ``path``; never raises for bad content."""
        stat = self.store.stat(path)
        raw = self.store.read_bytes(path)
        row = ContentIndex(
            path=path, git_sha=git_sha or "", modified_at=stat.modified_at
        )
        try:
            text = raw.decode("utf-8")
            document = self.validator.validate(path, text)
        except (DocumentValidationError, UnicodeDecodeError) as exc:
            row.status = ContentIndex.Status.INVALID
            row.error = str(exc)
            document = self._best_effort(path, raw)
        if document is not None:
            row.content_type = document.content_type
            row.locale = document.locale
            row.slug = document.slug[:200]
            row.title = document.title[:500]
            row.metadata = document.metadata
            row.content_hash = document.content_hash
            row.modified_at = document.modified_at or stat.modified_at
        else:
            row.content_type = "application/octet-stream"
            row.slug = path.rsplit("/", 1)[-1].split(".", 1)[0][:200]
            row.title = path[:500]
            row.content_hash = content_hash(raw)
        return row

    def _best_effort(self, path, raw):
        try:
            return self.registry.parse(path, raw.decode("utf-8"))
        except (FileContentError, UnicodeDecodeError):
            return None

    def upsert(self, path, git_sha=""):
        try:
            row = self.build(path, git_sha)
        except DocumentNotFound:
            # Listed by Git but missing from the working tree (e.g. a sparse
            # checkout or a concurrent delete): the file is gone for readers.
            self.delete([path])
            return None
        fields = {
            f.name: getattr(row, f.name)
            for f in ContentIndex._meta.concrete_fields
            if f.name not in {"id", "path", "indexed_at"}
        }
        obj, _created = ContentIndex.objects.update_or_create(
            path=path, defaults=fields
        )
        if row.status != ContentIndex.Status.OK:
            logger.warning("Indexed invalid document %s: %s", path, row.error)
        return obj

    def bulk_create(self, paths, git_sha=""):
        rows = [self.build(path, git_sha) for path in paths]
        ContentIndex.objects.bulk_create(rows, batch_size=500)
        return rows

    def delete(self, paths):
        if not paths:
            return 0
        deleted, _ = ContentIndex.objects.filter(path__in=list(paths)).delete()
        return deleted
