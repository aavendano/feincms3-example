from django.core.management.base import BaseCommand, CommandError
from feincms3_filecontent.exceptions import FileContentError
from feincms3_filecontent.repository.git import has_credentials, redact

from app.content import get_article_repository


class Command(BaseCommand):
    help = (
        "First run: clone the content repository into CONTENT_REPOSITORY['ROOT'] "
        "and build the article index. Safe to re-run; never overwrites files."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--remote",
            help="Remote URL (default: CONTENT_REPOSITORY['GIT']['REMOTE_URL']).",
        )
        parser.add_argument(
            "--no-index", action="store_true", help="Do not build the index."
        )

    def handle(self, **options):
        repository = get_article_repository()
        backend = getattr(repository, "inner", repository)
        if backend.backend != "git":
            raise CommandError(
                'CONTENT_REPOSITORY["BACKEND"] is not "git"; nothing to clone.'
            )
        remote = options["remote"] or backend.remote_url
        if remote and has_credentials(remote):
            self.stderr.write(
                self.style.WARNING(
                    "The remote URL embeds credentials; prefer SSH keys or a "
                    "credential helper (it is never printed or stored by Django)."
                )
            )
        try:
            cloned = backend.clone(remote)
        except FileContentError as exc:
            raise CommandError(str(exc)) from exc
        if cloned:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Cloned {redact(remote)} ({backend.git.branch}) into {backend.root}."
                )
            )
        else:
            self.stdout.write(f"{backend.root} is already a working tree; not cloning.")

        indexer = getattr(repository, "indexer", None)
        if indexer is not None and not options["no_index"]:
            result = indexer.sync(full=cloned)
            self.stdout.write(
                f"Index: {result.mode} ({result.upserted} upserted, "
                f"{result.deleted} deleted, {result.invalid} invalid)."
            )
