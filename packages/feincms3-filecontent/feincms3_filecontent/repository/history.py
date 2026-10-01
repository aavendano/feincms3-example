from dataclasses import dataclass
from datetime import datetime


FIELD_SEP = "\x1f"
RECORD_SEP = "\x1e"
LOG_FORMAT = FIELD_SEP.join(["%H", "%an", "%ae", "%aI", "%s", "%b"]) + RECORD_SEP


@dataclass(frozen=True)
class HistoryEntry:
    sha: str
    author_name: str
    author_email: str
    date: datetime
    subject: str
    body: str = ""

    @property
    def short_sha(self):
        return self.sha[:10]

    @property
    def message(self):
        return f"{self.subject}\n\n{self.body}".strip()


def parse_log(output):
    entries = []
    for raw in output.split(RECORD_SEP):
        record = raw.strip("\n")
        if not record:
            continue
        sha, name, email, date, subject, body = record.split(FIELD_SEP, 5)
        entries.append(
            HistoryEntry(
                sha=sha,
                author_name=name,
                author_email=email,
                date=datetime.fromisoformat(date),
                subject=subject,
                body=body.strip(),
            )
        )
    return entries
