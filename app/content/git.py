"""
Git backend: the filesystem backend plus one commit per change.

    content/                      ← root of a Git working tree (its own repo)
      CA/en/articles/*.md

Reads are exactly the filesystem backend's: Git never runs on the read path.
Every create/update/delete runs under the repository write lock and is turned
into a single commit authored by the editor (``ChangeContext``). The Git
plumbing — command runner, status/conflict detection, cross-process lock,
history, diffs — is ``feincms3_filecontent.repository``; this module only
maps content operations onto it.

Guarantees:

* A change that fails before its commit exists leaves the working tree and
  the Git index exactly as they were (file contents restored, paths unstaged).
* A failed push never fails the edit: the commit is durable locally, the
  repository is AHEAD and ``status()`` / the API say so. ``sync()`` pushes
  later; divergent histories are reported, never merged automatically.
* History is never rewritten: ``restore()`` writes old content as a new commit.
"""

import threading
from dataclasses import asdict, dataclass

from feincms3_filecontent.exceptions import (
    DocumentNotFound as GitDocumentNotFound,
    GitCommandError,
    PushRejected,
    RepositoryError,
)
from feincms3_filecontent.repository.conflicts import describe, ensure_can_write
from feincms3_filecontent.repository.git import (
    GitRepository,
    has_credentials,
    redact,
)

from . import schemas
from .exceptions import DocumentNotFound
from .filesystem import FilesystemArticleRepository
from .repository import ChangeContext


@dataclass(frozen=True)
class CommitInfo:
    sha: str | None  # None: nothing changed
    pushed: bool = False
    push_error: str = ""

    def as_dict(self):
        return asdict(self)


class GitArticleRepository(FilesystemArticleRepository):
    backend = "git"
    capabilities = FilesystemArticleRepository.capabilities | {
        "history",
        "diff",
        "restore",
        "commit",
    }

    def __init__(
        self,
        root,
        *,
        markets,
        branch="main",
        remote_name="origin",
        remote_url=None,
        auto_push=True,
        committer=("feincms3 content", "content@localhost"),
        lock_timeout=10,
    ):
        super().__init__(root, markets=markets, lock_timeout=lock_timeout)
        self.auto_push = auto_push
        self.remote_url = remote_url
        self.git = GitRepository(
            self.root,
            remote_name=remote_name,
            branch=branch,
            committer=committer,
            lock_timeout=lock_timeout,
        )
        self._local = threading.local()
        self._lock = None

    # The write lock lives in the Git directory (shared by every process and
    # every worktree of the repository), not in the content tree.
    @property
    def lock(self):
        if self._lock is None:
            self.git.ensure_exists()
            self._lock = self.git.lock()
        return self._lock

    @lock.setter
    def lock(self, value):
        # FilesystemArticleRepository.__init__ assigns its own lock; ignore it.
        pass

    # Commit bookkeeping ------------------------------------------------------

    def last_commit(self):
        """``CommitInfo`` of this thread's most recent write, if any."""
        return getattr(self._local, "last_commit", None)

    def _author(self, context):
        if context and context.author_name:
            return (context.author_name, context.author_email or "unknown@localhost")
        return None

    def _transaction(self, paths, operation, *, context, message, allow_dirty=False):
        """
        Run ``operation`` (which mutates files for ``paths``) and commit exactly
        those paths. Restores everything if anything fails before the commit.
        Uncommitted changes on ``paths`` are refused unless ``allow_dirty``
        (they would otherwise be silently folded into this commit).
        """
        self._local.last_commit = None
        paths = list(dict.fromkeys(paths))
        message = (context.message if context and context.message else message).strip()
        with self.lock:
            ensure_can_write(self.git, () if allow_dirty else paths)
            snapshot = {
                p: self.store.read_bytes(p) if self.store.exists(p) else None
                for p in paths
            }
            try:
                result = operation()
                sha = self.git.commit(message, paths, author=self._author(context))
            except BaseException:
                self._restore_snapshot(snapshot)
                raise
            info = CommitInfo(sha=sha)
            if sha and self.auto_push and self.git.remote_url():
                info = self._push(sha)
            self._local.last_commit = info
            return result

    def _restore_snapshot(self, snapshot):
        for path, data in snapshot.items():
            if data is None:
                if self.store.exists(path):
                    self.store.delete(path)
            else:
                self.store.write(path, data)
        self.git.unstage(list(snapshot))

    def _push(self, sha):
        try:
            self.git.push()
        except (PushRejected, GitCommandError) as exc:
            return CommitInfo(sha=sha, pushed=False, push_error=redact(str(exc)))
        return CommitInfo(sha=sha, pushed=True)

    # Writes ------------------------------------------------------------------

    def create(self, article, *, context=None):
        return self._transaction(
            [self._path(article.key)],
            lambda: super(GitArticleRepository, self).create(article),
            context=context,
            message=f"Add article {article.id}",
        )

    def update(self, key, article, *, expected_version=None, context=None):
        moved = article.key != key
        return self._transaction(
            [self._path(key), self._path(article.key)],
            lambda: super(GitArticleRepository, self).update(
                key, article, expected_version=expected_version
            ),
            context=context,
            message=f"Move article {key.id} to {article.id}"
            if moved
            else f"Update article {key.id}",
        )

    def delete(self, key, *, expected_version=None, context=None):
        return self._transaction(
            [self._path(key)],
            lambda: super(GitArticleRepository, self).delete(
                key, expected_version=expected_version
            ),
            context=context,
            message=f"Delete article {key.id}",
        )

    def commit(self, keys, *, context):
        """Commit pending working-tree changes of ``keys`` (e.g. hand edits)."""
        return self._transaction(
            [self._path(k) for k in keys],
            lambda: None,
            context=context,
            message="Update articles",
            allow_dirty=True,
        )

    # History -----------------------------------------------------------------

    def history(self, key, *, max_count=50):
        return [
            {
                "version": entry.sha,
                "short_version": entry.short_sha,
                "author_name": entry.author_name,
                "author_email": entry.author_email,
                "date": entry.date.isoformat(),
                "message": entry.subject,
            }
            for entry in self.git.log(self._path(key), max_count=max_count)
        ]

    def _resolve(self, version):
        sha = self.git.current_sha(version) if version else None
        if not sha:
            raise DocumentNotFound(f"Unknown version {version!r}")
        return sha

    def diff(self, key, from_version, to_version=None):
        """
        With one version: the change that commit made to the article.
        With two: the difference between them.
        """
        path = self._path(key)
        a = self._resolve(from_version)
        if to_version is None:
            return self.git.commit_diff(a, [path])
        return self.git.diff(a, self._resolve(to_version), [path])

    def version(self, key, version):
        """The article as it was at ``version`` (a commit)."""
        try:
            text = self.git.show(self._path(key), self._resolve(version))
        except GitDocumentNotFound:
            raise DocumentNotFound(f"{key.id} did not exist at {version}") from None
        return schemas.parse(key, text)

    def restore(self, key, version, *, expected_version=None, context=None):
        old = self.version(key, version)
        sha = self._resolve(version)
        context = ChangeContext(
            author_name=context.author_name if context else "",
            author_email=context.author_email if context else "",
            message=(context.message if context and context.message else "")
            or f"Restore article {key.id} to {sha[:10]}",
        )
        if self.exists(key):
            return self.update(
                key, old, expected_version=expected_version, context=context
            )
        return self.create(old, context=context)

    # Repository state -------------------------------------------------------

    # First run ----------------------------------------------------------------

    def clone(self, remote_url=None):
        """
        Materialize the working tree from ``remote_url`` (default: the
        configured one). Returns ``True`` if it cloned, ``False`` if ROOT
        already is a working tree of this repository. Refuses to touch a
        non-empty directory that is not one: content is never overwritten.
        """
        url = remote_url or self.remote_url
        if self.git.exists():
            current = self.git.remote_url()
            if url and current and current != url:
                raise RepositoryError(
                    f"{self.root} is a clone of {redact(current)}, not {redact(url)}."
                )
            return False
        if not url:
            raise RepositoryError(
                'No remote configured (CONTENT_REPOSITORY["GIT"]["REMOTE_URL"]).'
            )
        if self.root.exists() and any(self.root.iterdir()):
            raise RepositoryError(
                f"{self.root} is not empty and not a Git working tree; "
                "refusing to clone over it."
            )
        GitRepository.clone(
            url,
            self.root,
            branch=self.git.branch,
            remote_name=self.git.remote_name,
        )
        self._lock = None
        return True

    def status(self):
        data = super().status()
        data["remote"] = redact(self.remote_url or "")
        if self.remote_url and has_credentials(self.remote_url):
            data.setdefault("warnings", []).append(
                "The remote URL embeds credentials; use SSH keys or a credential helper."
            )
        if not self.git.exists():
            return {
                **data,
                "ok": False,
                "cloned": False,
                "problems": ["Not a Git working tree (run ./manage.py content_clone)."],
            }
        report = self.git.status()
        if self.git.remote_url():
            data["remote"] = redact(self.git.remote_url())
        return {
            **data,
            "cloned": True,
            "modified": report.modified,
            "untracked": report.untracked,
            "conflicted": report.conflicted,
            "ok": report.state.value == "clean",
            "state": report.state.value,
            "branch": report.branch,
            "head": report.head,
            "upstream": report.upstream,
            "ahead": report.ahead,
            "behind": report.behind,
            "problems": describe(report),
        }

    def fetch(self):
        """Update remote-tracking refs (for an accurate ahead/behind)."""
        if self.git.exists() and self.git.remote_url():
            self.git.fetch()

    def sync(self):
        """
        Fetch, fast-forward if behind, push if ahead. Divergence raises
        ``DivergedError`` (with the paths touched on both sides) and changes
        nothing: reconciling editorial conflicts is a human decision.
        """
        with self.lock:
            if not self.git.remote_url():
                return self.status()
            self.git.pull()  # fetch + fast-forward only
            if self.git.status().ahead:
                self.git.push()
            return self.status()
