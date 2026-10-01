from ...workflow import rollback
from ._base import FileContentCommand


class Command(FileContentCommand):
    help = (
        "Show the Git history of a document, optionally with the patch of one commit."
    )

    def add_arguments(self, parser):
        parser.add_argument("path")
        parser.add_argument("--limit", type=int, default=20)
        parser.add_argument(
            "--diff", metavar="SHA", help="Show the change made by SHA."
        )

    def handle(self, path, **options):
        if options["diff"]:
            self.stdout.write(rollback.version_diff(path, options["diff"]))
            return
        entries = rollback.history(path, max_count=options["limit"])
        if not entries:
            self.warn("No history.")
        for entry in entries:
            self.stdout.write(
                f"{entry.short_sha}  {entry.date:%Y-%m-%d %H:%M}  "
                f"{entry.author_name} <{entry.author_email}>  {entry.subject}"
            )
