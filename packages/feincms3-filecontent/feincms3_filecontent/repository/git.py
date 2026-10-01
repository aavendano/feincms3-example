"""
Thin, explicit wrapper around the ``git`` command line.

Only standard Git is required; nothing here knows about GitHub, GitLab or
Bitbucket. Every command runs non-interactively (no credential prompts) and
errors are raised as ``GitCommandError`` with credentials redacted.
"""

import logging
import os
import re
import subprocess
from pathlib import Path

from ..exceptions import (
    DivergedError,
    DocumentNotFound,
    GitCommandError,
    MergeConflict,
    NotARepository,
    PushRejected,
    RepositoryError,
)
from .base import RepositoryLock
from .diff import ChangeSet, ChangeType, FileChange, parse_name_status
from .history import LOG_FORMAT, parse_log
from .status import StatusReport, classify, parse_porcelain_v2


logger = logging.getLogger(__name__)

CREDENTIALS_RE = re.compile(r"(?P<scheme>[a-z][a-z0-9+.-]*://)[^/@\s]+@", re.IGNORECASE)
REJECTED_MARKERS = (
    "[rejected]",
    "non-fast-forward",
    "fetch first",
    "[remote rejected]",
)
LOCK_NAME = "filecontent.lock"


def redact(text):
    """Remove ``user:password@`` from URLs before logging or raising."""
    return CREDENTIALS_RE.sub(r"\g<scheme>***@", text or "")


def has_credentials(url):
    return bool(url and CREDENTIALS_RE.search(url))


class GitRepository:
    def __init__(
        self,
        path,
        *,
        remote_name="origin",
        branch="main",
        git_binary="git",
        timeout=120,
        lock_timeout=30,
        committer=("feincms3-filecontent", "filecontent@localhost"),
    ):
        self.path = Path(path)
        self.remote_name = remote_name
        self.branch = branch
        self.git_binary = git_binary
        self.timeout = timeout
        self.lock_timeout = lock_timeout
        self.committer = committer
        self._lock = None

    def __repr__(self):
        return f"<GitRepository {self.path} ({self.branch})>"

    # Plumbing ---------------------------------------------------------------

    def _env(self, extra=None):
        env = {
            **os.environ,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ASKPASS": "",
            "SSH_ASKPASS": "",
            "LC_ALL": "C",
            "LANG": "C",
            # Never pick up a pager or an editor.
            "GIT_PAGER": "cat",
            "GIT_EDITOR": "true",
        }
        env.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes")
        if extra:
            env.update(extra)
        return env

    def run(self, *args, check=True, cwd=None, env=None, input=None, strip=True):
        cmd = [self.git_binary, *args]
        try:
            proc = subprocess.run(
                cmd,
                cwd=cwd or self.path,
                env=self._env(env),
                input=input,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="surrogateescape",
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise GitCommandError(
                [redact(a) for a in args], -1, "", f"timed out after {self.timeout}s"
            ) from exc
        except FileNotFoundError as exc:
            raise RepositoryError(f"Git binary {self.git_binary!r} not found.") from exc
        if check and proc.returncode != 0:
            raise GitCommandError(
                [redact(a) for a in args],
                proc.returncode,
                redact(proc.stdout),
                redact(proc.stderr),
            )
        if strip:
            proc.stdout = proc.stdout.strip()
        return proc

    def out(self, *args, **kwargs):
        return self.run(*args, **kwargs).stdout

    # Introspection ----------------------------------------------------------

    def exists(self):
        if not self.path.is_dir():
            return False
        proc = self.run("rev-parse", "--is-inside-work-tree", check=False)
        if proc.returncode != 0 or proc.stdout != "true":
            return False
        top = Path(self.out("rev-parse", "--show-toplevel")).resolve()
        return top == self.path.resolve()

    def ensure_exists(self):
        if not self.exists():
            raise NotARepository(f"{self.path} is not the root of a Git working tree.")

    @property
    def git_dir(self):
        return Path(self.out("rev-parse", "--absolute-git-dir"))

    @property
    def common_dir(self):
        common = Path(self.out("rev-parse", "--git-common-dir"))
        return common if common.is_absolute() else (self.path / common).resolve()

    def lock(self):
        """Write lock shared by all worktrees of this repository."""
        if self._lock is None:
            self._lock = RepositoryLock(
                self.common_dir / LOCK_NAME, timeout=self.lock_timeout
            )
        return self._lock

    def current_branch(self):
        proc = self.run("symbolic-ref", "--quiet", "--short", "HEAD", check=False)
        return proc.stdout if proc.returncode == 0 else None

    def current_sha(self, ref="HEAD"):
        proc = self.run(
            "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", check=False
        )
        return proc.stdout if proc.returncode == 0 else None

    def has_commit(self, sha):
        return bool(sha) and self.current_sha(sha) is not None

    def is_ancestor(self, ancestor, descendant="HEAD"):
        proc = self.run(
            "merge-base", "--is-ancestor", ancestor, descendant, check=False
        )
        return proc.returncode == 0

    def merge_base(self, a, b):
        proc = self.run("merge-base", a, b, check=False)
        return proc.stdout if proc.returncode == 0 else None

    @property
    def upstream(self):
        return f"{self.remote_name}/{self.branch}"

    def remote_url(self):
        proc = self.run("remote", "get-url", self.remote_name, check=False)
        return proc.stdout if proc.returncode == 0 else None

    def operation_in_progress(self):
        git_dir = self.git_dir
        markers = {
            "MERGE_HEAD": "merge",
            "rebase-merge": "rebase",
            "rebase-apply": "rebase",
            "CHERRY_PICK_HEAD": "cherry-pick",
            "REVERT_HEAD": "revert",
        }
        for name, operation in markers.items():
            if (git_dir / name).exists():
                return operation
        return None

    def status(self):
        self.ensure_exists()
        output = self.run(
            "status",
            "--porcelain=v2",
            "--branch",
            "-z",
            "--untracked-files=all",
            env={"GIT_OPTIONAL_LOCKS": "0"},
            strip=False,
        ).stdout
        info = parse_porcelain_v2(output)
        operation = self.operation_in_progress()
        state = classify(
            ahead=info["ahead"],
            behind=info["behind"],
            modified=info["modified"],
            untracked=info["untracked"],
            conflicted=info["conflicted"],
            operation=operation,
        )
        return StatusReport(state=state, operation=operation, **info)

    def conflicted_files(self):
        out = self.out("diff", "--name-only", "--diff-filter=U", "-z", strip=False)
        return [p for p in out.split("\x00") if p]

    # Remote operations ------------------------------------------------------

    @classmethod
    def clone(cls, url, path, *, branch="main", **kwargs):
        path = Path(path)
        if path.exists() and any(path.iterdir()):
            raise RepositoryError(f"Cannot clone into non-empty directory {path}.")
        path.parent.mkdir(parents=True, exist_ok=True)
        repo = cls(path, branch=branch, **kwargs)
        repo.run(
            "clone",
            "--branch",
            branch,
            "--origin",
            repo.remote_name,
            "--",
            url,
            str(path),
            cwd=path.parent,
        )
        return repo

    def fetch(self):
        self.run("fetch", "--prune", self.remote_name)

    def pull(self):
        """
        Fast-forward the current branch to its upstream.

        Never merges: divergent histories raise ``DivergedError`` and must be
        reconciled explicitly (see ``workflow.commits.synchronize``).
        """
        self.fetch()
        head = self.current_sha()
        upstream = self.current_sha(self.upstream)
        if upstream is None or head == upstream:
            return head
        if head and not self.is_ancestor(head, upstream):
            if self.is_ancestor(upstream, head):
                return head  # local is ahead; nothing to pull
            raise DivergedError(
                f"{self.branch} and {self.upstream} have diverged",
                self.diverging_paths(head, upstream),
            )
        self.run("merge", "--ff-only", "--no-edit", self.upstream)
        return self.current_sha()

    def push(self, branch=None, *, set_upstream=False, cwd=None):
        branch = branch or self.current_branch() or self.branch
        args = ["push", "--porcelain"]
        if set_upstream:
            args.append("--set-upstream")
        args += [self.remote_name, f"refs/heads/{branch}:refs/heads/{branch}"]
        proc = self.run(*args, check=False, cwd=cwd)
        if proc.returncode != 0:
            text = f"{proc.stdout}\n{proc.stderr}"
            if any(marker in text for marker in REJECTED_MARKERS):
                raise PushRejected(
                    f"Push of {branch!r} to {self.remote_name!r} was rejected: "
                    f"{redact(proc.stderr).strip() or redact(proc.stdout).strip()}"
                )
            raise GitCommandError(
                args, proc.returncode, redact(proc.stdout), redact(proc.stderr)
            )

    # Branches ---------------------------------------------------------------

    def validate_branch_name(self, name):
        proc = self.run("check-ref-format", "--branch", name, check=False)
        if proc.returncode != 0 or name.startswith("-"):
            raise RepositoryError(f"Invalid branch name: {name!r}")
        return name

    def branch_exists(self, name, *, remote=False):
        ref = (
            f"refs/remotes/{self.remote_name}/{name}"
            if remote
            else f"refs/heads/{name}"
        )
        return (
            self.run("show-ref", "--verify", "--quiet", ref, check=False).returncode
            == 0
        )

    def create_branch(self, name, start_point="HEAD", *, checkout=False):
        self.validate_branch_name(name)
        if checkout:
            self.run("switch", "--create", name, start_point)
        else:
            self.run("branch", "--", name, start_point)

    def checkout(self, ref):
        if self.branch_exists(ref):
            self.run("switch", "--", ref)
        else:
            self.run("switch", "--detach", ref)

    def worktree_add(self, path, branch, start_point):
        self.validate_branch_name(branch)
        args = ["worktree", "add"]
        if self.branch_exists(branch):
            args += ["--", str(path), branch]
        else:
            args += ["-b", branch, "--", str(path), start_point]
        self.run(*args)
        return self.__class__(
            path,
            remote_name=self.remote_name,
            branch=branch,
            git_binary=self.git_binary,
            timeout=self.timeout,
            lock_timeout=self.lock_timeout,
            committer=self.committer,
        )

    def worktree_remove(self, path):
        self.run("worktree", "remove", "--force", "--", str(path), check=False)
        self.run("worktree", "prune", check=False)

    # Content ----------------------------------------------------------------

    def show(self, path, ref="HEAD"):
        proc = self.run("show", f"{ref}:{path}", check=False, strip=False)
        if proc.returncode != 0:
            raise DocumentNotFound(f"{path} does not exist at {ref}")
        return proc.stdout

    def ls_files(self, ref="HEAD"):
        out = self.out("ls-tree", "-r", "--name-only", "-z", ref, strip=False)
        return [p for p in out.split("\x00") if p]

    def diff(self, a=None, b=None, paths=()):
        """
        Unified diff. With no refs: working tree vs HEAD; with one ref: working
        tree vs that ref; with two: between the refs.
        """
        args = ["diff", "--no-color", "--no-ext-diff", "-M"]
        if a and not b:
            args.append(a)
        elif a and b:
            args += [a, b]
        else:
            args.append("HEAD")
        args.append("--")
        args.extend(paths)
        return self.out(*args, strip=False)

    def commit_diff(self, sha, paths=()):
        """The patch introduced by ``sha`` (works for root commits too)."""
        return self.out(
            "show",
            "--format=",
            "--no-color",
            "--no-ext-diff",
            "-M",
            sha,
            "--",
            *paths,
            strip=False,
        )

    def delete_branch(self, name):
        self.run("branch", "-D", "--", name, check=False)

    def changed_files(self, from_sha, to_sha="HEAD"):
        """Added/modified/deleted/renamed paths between two commits."""
        to = self.current_sha(to_sha)
        if to is None:
            raise RepositoryError(f"Unknown revision {to_sha!r}")
        if not from_sha:
            changes = tuple(FileChange(ChangeType.ADDED, p) for p in self.ls_files(to))
            return ChangeSet(None, to, changes)
        out = self.out(
            "diff",
            "--name-status",
            "-z",
            "-M",
            "--no-ext-diff",
            from_sha,
            to,
            strip=False,
        )
        return ChangeSet(from_sha, to, tuple(parse_name_status(out)))

    def diverging_paths(self, a, b):
        base = self.merge_base(a, b)
        if base is None:
            return []

        def touched(sha):
            changes = self.changed_files(base, sha).changes
            return {c.path for c in changes} | {
                c.old_path for c in changes if c.old_path
            }

        return sorted(touched(a) & touched(b))

    def log(self, path=None, *, ref="HEAD", max_count=50):
        if self.current_sha(ref) is None:
            return []
        args = ["log", f"--format={LOG_FORMAT}", f"--max-count={max_count}"]
        if path:
            args += ["--follow", ref, "--", path]
        else:
            args.append(ref)
        return parse_log(self.out(*args, strip=False))

    # Writing ----------------------------------------------------------------

    def commit(self, message, paths, *, author=None):
        """
        Stage exactly ``paths`` (additions, modifications, deletions) and commit
        only those paths. Other changes in the working tree are left alone.
        Returns the new commit SHA, or ``None`` if nothing changed.
        """
        paths = list(paths)
        if not paths:
            raise RepositoryError("commit() requires at least one path.")
        self.run("add", "--all", "--", *paths)
        staged = self.run("diff", "--cached", "--quiet", "--", *paths, check=False)
        if staged.returncode == 0:
            return None
        author_name, author_email = author or self.committer
        committer_name, committer_email = self.committer
        self.run(
            "commit",
            "--no-verify",
            "--quiet",
            "--file=-",
            "--",
            *paths,
            input=message,
            env={
                "GIT_AUTHOR_NAME": author_name,
                "GIT_AUTHOR_EMAIL": author_email,
                "GIT_COMMITTER_NAME": committer_name,
                "GIT_COMMITTER_EMAIL": committer_email,
            },
        )
        return self.current_sha()

    def unstage(self, paths):
        if self.current_sha() is None:
            self.run(
                "rm",
                "--cached",
                "--quiet",
                "--ignore-unmatch",
                "--",
                *paths,
                check=False,
            )
        else:
            self.run("reset", "--quiet", "HEAD", "--", *paths, check=False)

    def rebase(self, onto):
        """Rebase the current branch onto ``onto``; abort and raise on conflict."""
        proc = self.run("rebase", "--no-autostash", onto, check=False)
        if proc.returncode != 0:
            conflicted = self.conflicted_files()
            self.run("rebase", "--abort", check=False)
            raise MergeConflict(f"Rebasing onto {onto} produced conflicts", conflicted)

    def abort_operation(self):
        operation = self.operation_in_progress()
        if operation:
            self.run(operation, "--abort", check=False)
        return operation
