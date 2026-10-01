from django.core.management.base import BaseCommand, CommandError

from ...exceptions import ConflictError, FileContentError


class FileContentCommand(BaseCommand):
    """Turns library errors into ``CommandError`` with a non-zero exit code."""

    def execute(self, *args, **options):
        try:
            return super().execute(*args, **options)
        except ConflictError as exc:
            raise CommandError(f"Conflict: {exc}", returncode=3) from exc
        except FileContentError as exc:
            raise CommandError(str(exc), returncode=2) from exc

    def ok(self, message):
        self.stdout.write(self.style.SUCCESS(message))

    def warn(self, message):
        self.stdout.write(self.style.WARNING(message))

    def error(self, message):
        self.stderr.write(self.style.ERROR(message))
