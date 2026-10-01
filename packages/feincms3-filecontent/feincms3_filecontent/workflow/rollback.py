"""
History and non-destructive rollback.

Restoring a version reads the file as it was at a commit and records it as a
*new* commit. History is never rewritten (no reset, no force-push).
"""

from .. import services
from ..storage.filesystem import normalize_path
from .commits import ContentWriter


def history(path, *, max_count=50):
    return services.get_repository().log(normalize_path(path), max_count=max_count)


def version(path, sha):
    """The document text at ``sha``; raises ``DocumentNotFound``."""
    return services.get_repository().show(normalize_path(path), sha)


def version_diff(path, sha):
    """The change ``sha`` introduced to ``path``."""
    return services.get_repository().commit_diff(sha, [normalize_path(path)])


def restore(
    path, sha, *, author=None, message=None, expected_hash=None, push=None, writer=None
):
    path = normalize_path(path)
    repo = services.get_repository()
    full_sha = repo.current_sha(sha)
    if full_sha is None:
        raise ValueError(f"Unknown commit {sha!r}")
    text = repo.show(path, full_sha)
    message = message or f"Restore {path} to {full_sha[:10]}"
    writer = writer or ContentWriter.default()
    return writer.save(
        path,
        text,
        message=message,
        author=author,
        expected_hash=expected_hash,
        push=push,
    )
