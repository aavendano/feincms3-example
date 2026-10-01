"""
Branches as a first-class capability.

Naming conventions::

    main
    content/update-about
    content/article-123
    translation/fr/article-123

Review branches are never checked out in the served working tree. They get
their own linked worktree (``git worktree``) under ``WORKTREES_DIR`` so HTTP
requests keep reading the configured branch while a proposal is prepared.
"""

import shutil
from pathlib import Path

from django.utils.text import slugify

from ..storage.filesystem import FileSystemContentStore


def _slug(value):
    slug = slugify(str(value))
    if not slug:
        raise ValueError(f"Cannot build a branch name from {value!r}")
    return slug


def content_branch(*parts):
    """``content_branch("update", "about")`` -> ``"content/update-about"``"""
    return "content/" + "-".join(_slug(p) for p in parts)


def translation_branch(locale, *parts):
    """``translation_branch("fr", "article", 123)`` -> ``"translation/fr/article-123"``"""
    return f"translation/{_slug(locale)}/" + "-".join(_slug(p) for p in parts)


def list_branches(repo, pattern="*"):
    out = repo.out("for-each-ref", "--format=%(refname:short)", f"refs/heads/{pattern}")
    return [line for line in out.splitlines() if line]


class BranchWorkspace:
    """
    Context manager providing an isolated worktree checked out on ``branch``.

    ``branch`` is created from ``start_point`` when it does not exist locally.
    The worktree is always removed on exit; commits stay in the repository.
    """

    def __init__(self, repo, branch, *, start_point, worktrees_dir, exclude=(".git",)):
        self.repo = repo
        self.branch = repo.validate_branch_name(branch)
        self.start_point = start_point
        self.path = Path(worktrees_dir) / branch.replace("/", "__")
        self.exclude = exclude
        self.worktree = None
        self.store = None

    def __enter__(self):
        if self.path.exists():
            # Left over from an interrupted run.
            self.repo.worktree_remove(self.path)
            shutil.rmtree(self.path, ignore_errors=True)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.worktree = self.repo.worktree_add(self.path, self.branch, self.start_point)
        self.store = FileSystemContentStore(self.path, exclude=self.exclude)
        return self

    def __exit__(self, *exc):
        self.repo.worktree_remove(self.path)
        shutil.rmtree(self.path, ignore_errors=True)
