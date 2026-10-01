from ...sync.engine import SyncEngine
from ._base import FileContentCommand


class Command(FileContentCommand):
    help = "Delete the content index and rebuild it completely from the working tree."

    def handle(self, **options):
        result = SyncEngine.default().rebuild()
        self.ok(result.summary())
        for path in result.invalid:
            self.warn(f"invalid: {path}")
