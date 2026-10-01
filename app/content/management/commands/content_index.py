from django.core.management.base import BaseCommand, CommandError

from app.content import get_article_repository


class Command(BaseCommand):
    help = (
        "Bring the article index up to date with the content files "
        "(incremental by default)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--rebuild", action="store_true", help="Drop and recreate the whole index."
        )
        parser.add_argument(
            "--status", action="store_true", help="Only report the index state."
        )

    def handle(self, **options):
        repository = get_article_repository()
        indexer = getattr(repository, "indexer", None)
        if indexer is None:
            raise CommandError('CONTENT_REPOSITORY["INDEX"] is disabled.')
        if options["status"]:
            for key, value in indexer.status().items():
                self.stdout.write(f"{key}: {value}")
            return
        result = indexer.sync(full=options["rebuild"])
        summary = (
            f"{result.mode}: {result.upserted} upserted, {result.deleted} deleted, "
            f"{result.invalid} invalid"
        )
        if result.reason:
            summary += f" ({result.reason})"
        self.stdout.write(self.style.SUCCESS(summary))
