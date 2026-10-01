import enum
from dataclasses import dataclass


class ChangeType(enum.Enum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"


@dataclass(frozen=True)
class FileChange:
    change: ChangeType
    path: str
    # Previous path for renames.
    old_path: str | None = None


_STATUS_MAP = {
    "A": ChangeType.ADDED,
    "C": ChangeType.ADDED,  # copy: the destination is new
    "M": ChangeType.MODIFIED,
    "T": ChangeType.MODIFIED,  # type change
    "D": ChangeType.DELETED,
    "R": ChangeType.RENAMED,
}


def parse_name_status(output):
    """Parse ``git diff --name-status -z -M`` output into ``FileChange``s."""
    tokens = output.split("\x00")
    changes = []
    i = 0
    while i < len(tokens):
        status = tokens[i]
        i += 1
        if not status:
            continue
        kind = _STATUS_MAP.get(status[0])
        if kind is None:
            # "U" (unmerged), "X" (unknown) — treat as modified so it is
            # reprocessed; conflicts are reported by status(), not here.
            kind = ChangeType.MODIFIED
        if status[0] in "RC":
            old, new = tokens[i], tokens[i + 1]
            i += 2
            if kind is ChangeType.RENAMED:
                changes.append(FileChange(kind, new, old))
            else:
                changes.append(FileChange(kind, new))
        else:
            changes.append(FileChange(kind, tokens[i]))
            i += 1
    return changes


@dataclass(frozen=True)
class ChangeSet:
    from_sha: str | None
    to_sha: str
    changes: tuple

    @property
    def upserts(self):
        """Paths whose current content must be (re)projected."""
        return [c.path for c in self.changes if c.change is not ChangeType.DELETED]

    @property
    def deletions(self):
        """Paths that no longer exist at ``to_sha``."""
        removed = []
        for c in self.changes:
            if c.change is ChangeType.DELETED:
                removed.append(c.path)
            elif c.change is ChangeType.RENAMED and c.old_path:
                removed.append(c.old_path)
        return removed

    def __bool__(self):
        return bool(self.changes)
