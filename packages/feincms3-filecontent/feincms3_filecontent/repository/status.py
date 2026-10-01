import enum
from dataclasses import dataclass, field


class RepositoryStatus(enum.Enum):
    CLEAN = "clean"
    DIRTY = "dirty"
    AHEAD = "ahead"
    BEHIND = "behind"
    DIVERGED = "diverged"
    CONFLICTED = "conflicted"


@dataclass(frozen=True)
class StatusReport:
    """
    Snapshot of the working tree relative to HEAD and its upstream.

    ``state`` is the single most urgent condition, in this order:
    CONFLICTED > DIRTY > DIVERGED > AHEAD > BEHIND > CLEAN. The individual
    fields keep the full picture (a tree can be dirty *and* ahead).
    """

    state: RepositoryStatus
    branch: str | None
    head: str | None
    upstream: str | None = None
    ahead: int = 0
    behind: int = 0
    modified: list = field(default_factory=list)
    untracked: list = field(default_factory=list)
    conflicted: list = field(default_factory=list)
    operation: str | None = None  # "merge", "rebase", "cherry-pick", "revert"

    @property
    def is_dirty(self):
        return bool(self.modified or self.untracked)

    @property
    def is_detached(self):
        return self.branch is None

    def as_dict(self):
        return {
            "state": self.state.value,
            "branch": self.branch,
            "head": self.head,
            "upstream": self.upstream,
            "ahead": self.ahead,
            "behind": self.behind,
            "modified": list(self.modified),
            "untracked": list(self.untracked),
            "conflicted": list(self.conflicted),
            "operation": self.operation,
        }


def classify(*, ahead, behind, modified, untracked, conflicted, operation):
    if conflicted or operation:
        return RepositoryStatus.CONFLICTED
    if modified or untracked:
        return RepositoryStatus.DIRTY
    if ahead and behind:
        return RepositoryStatus.DIVERGED
    if ahead:
        return RepositoryStatus.AHEAD
    if behind:
        return RepositoryStatus.BEHIND
    return RepositoryStatus.CLEAN


def parse_porcelain_v2(output):
    """
    Parse ``git status --porcelain=v2 --branch -z`` output.

    Returns a dict with branch/head/upstream/ahead/behind and path lists.
    """
    info = {
        "branch": None,
        "head": None,
        "upstream": None,
        "ahead": 0,
        "behind": 0,
        "modified": [],
        "untracked": [],
        "conflicted": [],
    }
    records = output.split("\x00")
    i = 0
    while i < len(records):
        record = records[i]
        i += 1
        if not record:
            continue
        if record.startswith("# branch.oid "):
            oid = record.split(" ", 2)[2]
            info["head"] = None if oid == "(initial)" else oid
        elif record.startswith("# branch.head "):
            head = record.split(" ", 2)[2]
            info["branch"] = None if head == "(detached)" else head
        elif record.startswith("# branch.upstream "):
            info["upstream"] = record.split(" ", 2)[2]
        elif record.startswith("# branch.ab "):
            _, _, ahead, behind = record.split(" ")
            info["ahead"] = abs(int(ahead))
            info["behind"] = abs(int(behind))
        elif record.startswith("1 "):
            info["modified"].append(record.split(" ", 8)[8])
        elif record.startswith("2 "):
            # Renamed/copied: "2 XY sub mH mI mW hH hI Xscore path" + NUL + origPath
            info["modified"].append(record.split(" ", 9)[9])
            info["modified"].append(records[i])
            i += 1
        elif record.startswith("u "):
            info["conflicted"].append(record.split(" ", 10)[10])
        elif record.startswith("? "):
            info["untracked"].append(record[2:])
    return info
