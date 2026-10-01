"""
Conflict detection. Nothing in here resolves anything: every function either
returns a description or raises a ``ConflictError`` subclass naming the
affected paths, leaving the decision to a human.
"""

from ..exceptions import DirtyWorkingTree, DivergedError, MergeConflict
from .status import RepositoryStatus


def describe(report):
    """Human-readable list of problems in a ``StatusReport``."""
    problems = []
    if report.operation:
        problems.append(f"A {report.operation} is in progress.")
    if report.conflicted:
        problems.append(f"Unmerged paths: {', '.join(report.conflicted)}.")
    if report.modified:
        problems.append(f"Uncommitted changes: {', '.join(report.modified)}.")
    if report.untracked:
        problems.append(f"Untracked files: {', '.join(report.untracked)}.")
    if report.is_detached:
        problems.append("HEAD is detached.")
    if report.ahead and report.behind:
        problems.append(
            f"Diverged from {report.upstream}: {report.ahead} local and "
            f"{report.behind} remote commits."
        )
    elif report.ahead:
        problems.append(
            f"{report.ahead} local commit(s) not pushed to {report.upstream}."
        )
    elif report.behind:
        problems.append(
            f"{report.behind} remote commit(s) not pulled from {report.upstream}."
        )
    return problems


def ensure_can_write(repo, paths=()):
    """
    Refuse to start a write when the working tree is in a state where the
    result would be ambiguous.

    * merge/rebase in progress or unmerged paths -> ``MergeConflict``
    * uncommitted changes on any of ``paths``     -> ``DirtyWorkingTree``
    * history diverged from upstream             -> ``DivergedError``

    Unrelated uncommitted changes and being ahead/behind are tolerated: commits
    only include the edited paths, and pushes detect remote changes.
    """
    report = repo.status()
    if report.state is RepositoryStatus.CONFLICTED:
        raise MergeConflict(
            "The repository has an unfinished merge or rebase",
            report.conflicted,
        )
    if report.is_detached:
        raise DirtyWorkingTree("HEAD is detached; check out a branch first")
    wanted = set(paths)
    dirty = wanted & (set(report.modified) | set(report.untracked))
    if dirty:
        raise DirtyWorkingTree("Uncommitted changes would be overwritten", dirty)
    if report.state is RepositoryStatus.DIVERGED:
        raise DivergedError(
            f"{report.branch} has diverged from {report.upstream}",
            repo.diverging_paths("HEAD", report.upstream) if report.upstream else (),
        )
    return report
