from ..repository.diff import ChangeSet, ChangeType, FileChange


def document_changes(changeset, scanner):
    """
    Restrict a Git ``ChangeSet`` to files the index cares about.

    A rename between a document and a non-document becomes an add or a delete.
    """
    relevant = []
    for change in changeset.changes:
        new_is_doc = scanner.is_document(change.path)
        if change.change is ChangeType.RENAMED:
            old_is_doc = scanner.is_document(change.old_path)
            if new_is_doc and old_is_doc:
                relevant.append(change)
            elif new_is_doc:
                relevant.append(FileChange(ChangeType.ADDED, change.path))
            elif old_is_doc:
                relevant.append(FileChange(ChangeType.DELETED, change.old_path))
        elif new_is_doc:
            relevant.append(change)
    return ChangeSet(changeset.from_sha, changeset.to_sha, tuple(relevant))


def plan(repo, last_indexed_sha, head):
    """
    Decide how to bring the index from ``last_indexed_sha`` to ``head``.

    Returns ``("noop", None)``, ``("incremental", changeset)`` or
    ``("full", reason)``. A full rebuild is required when there is no previous
    state or the previous commit is no longer reachable (force-push, history
    rewrite, different clone).
    """
    if not last_indexed_sha:
        return "full", "no previous index"
    if last_indexed_sha == head:
        return "noop", None
    if not repo.has_commit(last_indexed_sha):
        return "full", f"indexed commit {last_indexed_sha[:10]} is unknown"
    return "incremental", repo.changed_files(last_indexed_sha, head)
