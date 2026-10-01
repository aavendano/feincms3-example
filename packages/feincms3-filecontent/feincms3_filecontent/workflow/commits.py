"""
Direct-mode writes: edit -> validate -> safe write -> git diff -> commit -> push.

Every write runs under the repository lock and is all-or-nothing locally: if
anything fails before the commit exists, the working tree and the Git index
are restored to their previous content. Once the commit exists the change is
durable; a failed push leaves the branch explicitly AHEAD and is reported in
the result, never retried or merged behind the user's back.
"""

import logging
from dataclasses import dataclass, field

from .. import services
from ..conf import get_settings
from ..content.documents import content_hash
from ..exceptions import (
    DirtyWorkingTree,
    DivergedError,
    DocumentNotFound,
    GitCommandError,
    MergeConflict,
    PushRejected,
    ReadOnlyError,
    StaleDocumentError,
)
from ..repository.conflicts import ensure_can_write
from ..repository.status import RepositoryStatus
from ..sync.engine import SyncEngine


logger = logging.getLogger(__name__)


@dataclass
class CommitResult:
    paths: list
    sha: str | None
    changed: bool
    pushed: bool = False
    push_error: str = ""
    sync: object = None
    sync_error: str = ""
    document: object = None

    @property
    def ok(self):
        return not (self.push_error or self.sync_error)


@dataclass
class SynchronizeResult:
    before: object
    after: object
    pulled: bool = False
    rebased: bool = False
    pushed: bool = False
    sync: object = None
    messages: list = field(default_factory=list)


def author_for(user, conf=None):
    """``(name, email)`` for a Django user, or the configured fallback."""
    conf = conf or get_settings()
    if user is None or not getattr(user, "is_authenticated", False):
        return (conf.commit_author_name, conf.commit_author_email)
    name = (user.get_full_name() or user.get_username()).strip()
    email = getattr(user, "email", "") or f"{user.get_username()}@users.noreply.local"
    return (name, email)


class ContentWriter:
    def __init__(self, *, store, repository, validator, sync_engine, conf):
        self.store = store
        self.repository = repository
        self.validator = validator
        self.sync_engine = sync_engine
        self.conf = conf

    @classmethod
    def default(cls):
        return cls(
            store=services.get_store(),
            repository=services.get_repository(),
            validator=services.get_validator(),
            sync_engine=SyncEngine.default(),
            conf=get_settings(),
        )

    # Public API -------------------------------------------------------------

    def save(self, path, text, *, message, author=None, expected_hash=None, push=None):
        """
        Create or update a document.

        ``expected_hash`` is the ``content_hash`` the editor started from
        (``""`` for a document that must not exist yet). A mismatch means
        someone else changed the file meanwhile: ``StaleDocumentError``.
        """
        document = self.validator.validate(path, text)
        path = document.path

        def apply():
            self._check_expected(path, expected_hash)
            self.store.write(path, text)

        result = self._commit([path], apply, message=message, author=author, push=push)
        result.document = document
        return result

    def delete(self, path, *, message, author=None, expected_hash=None, push=None):
        path = self.validator.validate_path(path)

        def apply():
            self._check_expected(path, expected_hash)
            if not self.store.exists(path):
                raise DocumentNotFound(path)
            self.store.delete(path)

        return self._commit([path], apply, message=message, author=author, push=push)

    def move(
        self,
        source,
        destination,
        *,
        message,
        author=None,
        expected_hash=None,
        push=None,
    ):
        source = self.validator.validate_path(source)
        destination = self.validator.validate_path(destination)

        def apply():
            self._check_expected(source, expected_hash)
            self.store.move(source, destination)

        return self._commit(
            [source, destination], apply, message=message, author=author, push=push
        )

    def push(self):
        """Push pending local commits (state AHEAD)."""
        self._check_writable()
        with self.repository.lock():
            self.repository.push(self.conf.branch)

    def synchronize(self, *, push=True):
        """
        Reconcile the local branch with its upstream, explicitly.

        * BEHIND   -> fast-forward
        * AHEAD    -> push (if ``push``)
        * DIVERGED -> rebase local commits onto upstream, but only when no file
          was touched on both sides (``CONFLICT_POLICY="strict"``) or when Git
          can replay without textual conflicts (``"git"``); otherwise raise
          and leave everything untouched.
        * CONFLICTED / dirty paths in the way -> raise.

        The content index is synchronized afterwards.
        """
        repo = self.repository
        repo.ensure_exists()
        with repo.lock():
            before = repo.status()
            if before.state is RepositoryStatus.CONFLICTED:
                raise MergeConflict(
                    "Resolve the unfinished merge or rebase first", before.conflicted
                )
            result = SynchronizeResult(before=before, after=before)
            if repo.remote_url():
                repo.fetch()
                report = repo.status()
                if report.behind and not report.ahead:
                    try:
                        repo.pull()
                    except GitCommandError as exc:
                        raise DirtyWorkingTree(
                            f"Cannot fast-forward: {exc.stderr.strip()}",
                            report.modified + report.untracked,
                        ) from exc
                    result.pulled = True
                elif report.ahead and report.behind:
                    if report.is_dirty:
                        raise DirtyWorkingTree(
                            "Commit or discard local changes before reconciling",
                            report.modified + report.untracked,
                        )
                    overlap = repo.diverging_paths("HEAD", repo.upstream)
                    if overlap and self.conf.conflict_policy == "strict":
                        raise DivergedError(
                            "Local and remote changes touch the same documents", overlap
                        )
                    repo.rebase(repo.upstream)
                    result.rebased = True
                    result.messages.append(
                        f"Rebased {report.ahead} local commit(s) onto {repo.upstream}."
                    )
                if push and not self.conf.read_only and repo.status().ahead:
                    repo.push(self.conf.branch)
                    result.pushed = True
            else:
                result.messages.append(
                    "No remote configured; nothing to fetch or push."
                )
            result.sync = self.sync_engine.sync()
            result.after = repo.status()
            return result

    # Internals --------------------------------------------------------------

    def _check_writable(self):
        if self.conf.read_only or self.store.read_only:
            raise ReadOnlyError("feincms3-filecontent is configured read-only.")

    def _check_expected(self, path, expected_hash):
        if expected_hash is None:
            return
        current = (
            content_hash(self.store.read_bytes(path)) if self.store.exists(path) else ""
        )
        if current != expected_hash:
            raise StaleDocumentError(
                "The document was changed by someone else since it was loaded", [path]
            )

    def _snapshot(self, paths):
        return {
            p: self.store.read_bytes(p) if self.store.exists(p) else None for p in paths
        }

    def _restore(self, snapshot):
        for path, data in snapshot.items():
            try:
                if data is None:
                    if self.store.exists(path):
                        self.store.delete(path)
                else:
                    self.store.write(path, data)
            except Exception:
                logger.exception("Could not restore %s", path)
        self.repository.unstage(list(snapshot))

    def _commit(self, paths, apply, *, message, author, push):
        self._check_writable()
        message = (message or "").strip()
        if not message:
            raise ValueError("A commit message is required.")
        repo = self.repository
        repo.ensure_exists()
        push = self.conf.auto_push if push is None else push

        with repo.lock():
            ensure_can_write(repo, paths)
            snapshot = self._snapshot(paths)
            try:
                apply()
                sha = repo.commit(message, paths, author=author)
            except BaseException:
                self._restore(snapshot)
                raise
            result = CommitResult(paths=list(paths), sha=sha, changed=sha is not None)
            if not result.changed:
                return result

            try:
                result.sync = self.sync_engine.sync()
            except Exception as exc:
                logger.exception("Index sync failed after commit %s", sha)
                result.sync_error = str(exc)

            if push:
                if not repo.remote_url():
                    result.push_error = "No remote configured."
                else:
                    try:
                        repo.push(self.conf.branch)
                        result.pushed = True
                    except (PushRejected, GitCommandError) as exc:
                        logger.warning("Push after commit %s failed: %s", sha, exc)
                        result.push_error = str(exc)
            return result
