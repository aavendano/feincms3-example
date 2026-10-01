import contextlib
import logging
from dataclasses import dataclass, field

from django.db import transaction

from .. import services
from ..conf import get_settings
from ..models import ContentIndex
from .changes import document_changes, plan
from .projector import Projector
from .scanner import Scanner
from .state import get_state, mark_error, mark_indexed


logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    mode: str  # "noop", "incremental", "full"
    from_sha: str | None
    to_sha: str | None
    upserted: list = field(default_factory=list)
    deleted: list = field(default_factory=list)
    invalid: list = field(default_factory=list)
    reason: str = ""

    def summary(self):
        text = (
            f"{self.mode}: {len(self.upserted)} upserted, {len(self.deleted)} deleted, "
            f"{len(self.invalid)} invalid"
        )
        if self.to_sha:
            text += f" @ {self.to_sha[:10]}"
        if self.reason:
            text += f" ({self.reason})"
        return text


class SyncEngine:
    """
    Keeps ``ContentIndex`` in step with the working tree.

    Incremental sync asks Git for the files changed between the last indexed
    commit and HEAD and reprocesses only those. ``rebuild()`` discards the
    whole projection and recreates it, which is also the fallback whenever the
    previous commit is unknown. Without a Git repository (plain directory,
    read-only deployments) every sync is a rebuild.
    """

    def __init__(self, *, store, registry, validator, repository=None, branch="main"):
        self.store = store
        self.registry = registry
        self.repository = repository
        self.branch = branch
        self.scanner = Scanner(store, registry)
        self.projector = Projector(store, registry, validator)

    @classmethod
    def default(cls):
        conf = get_settings()
        return cls(
            store=services.get_store(),
            registry=services.get_registry(),
            validator=services.get_validator(),
            repository=services.get_repository(),
            branch=conf.branch,
        )

    def has_git(self):
        return self.repository is not None and self.repository.exists()

    def _lock(self):
        return self.repository.lock() if self.has_git() else contextlib.nullcontext()

    def sync(self, *, full=False):
        with self._lock():
            try:
                return self._sync(full=full)
            except Exception as exc:
                mark_error(self.branch, exc)
                raise

    def rebuild(self):
        return self.sync(full=True)

    def _sync(self, *, full):
        head = self.repository.current_sha() if self.has_git() else None
        if full or head is None:
            reason = "requested" if full else "no Git history"
            return self._rebuild(head, reason)
        state = get_state(self.branch)
        mode, info = plan(self.repository, state.last_indexed_sha, head)
        if mode == "full":
            return self._rebuild(head, info)
        if mode == "noop":
            return SyncResult("noop", head, head)
        return self._incremental(document_changes(info, self.scanner))

    @transaction.atomic
    def _rebuild(self, head, reason):
        ContentIndex.objects.all().delete()
        rows = self.projector.bulk_create(self.scanner.paths(), head or "")
        mark_indexed(self.branch, head, mode="full")
        result = SyncResult(
            "full",
            None,
            head,
            upserted=[row.path for row in rows],
            invalid=[row.path for row in rows if row.status != ContentIndex.Status.OK],
            reason=reason,
        )
        logger.info("filecontent rebuild: %s", result.summary())
        return result

    @transaction.atomic
    def _incremental(self, changeset):
        result = SyncResult("incremental", changeset.from_sha, changeset.to_sha)
        result.deleted = changeset.deletions
        self.projector.delete(result.deleted)
        for path in changeset.upserts:
            row = self.projector.upsert(path, changeset.to_sha)
            if row is None:
                result.deleted.append(path)
                continue
            result.upserted.append(path)
            if row.status != ContentIndex.Status.OK:
                result.invalid.append(path)
        mark_indexed(self.branch, changeset.to_sha, mode="incremental")
        logger.info("filecontent sync: %s", result.summary())
        return result
