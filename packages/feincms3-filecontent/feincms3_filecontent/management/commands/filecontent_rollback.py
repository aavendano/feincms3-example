import re

from django.core.management.base import CommandError

from ...workflow import rollback
from ._base import FileContentCommand


AUTHOR_RE = re.compile(r"^(?P<name>[^<>]+?)\s*<(?P<email>[^<>]+)>$")


class Command(FileContentCommand):
    help = (
        "Restore a document to its content at a previous commit by creating a "
        "new commit. History is never rewritten."
    )

    def add_arguments(self, parser):
        parser.add_argument("path")
        parser.add_argument("sha")
        parser.add_argument("--message", "-m")
        parser.add_argument("--author", help='"Name <email>"')
        parser.add_argument("--no-push", action="store_true")

    def handle(self, path, sha, **options):
        author = None
        if options["author"]:
            match = AUTHOR_RE.match(options["author"])
            if not match:
                raise CommandError('--author must look like "Name <email>".')
            author = (match["name"], match["email"])
        result = rollback.restore(
            path,
            sha,
            author=author,
            message=options["message"],
            push=False if options["no_push"] else None,
        )
        if not result.changed:
            self.warn(f"{path} already matches {sha}; nothing to commit.")
            return
        self.ok(f"Committed {result.sha[:10]}.")
        if result.pushed:
            self.ok("Pushed.")
        elif result.push_error:
            self.warn(f"Not pushed: {result.push_error}")
