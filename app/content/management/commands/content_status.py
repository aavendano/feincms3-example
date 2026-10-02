import json

from django.core.management.base import BaseCommand, CommandError
from feincms3_filecontent.exceptions import FileContentError

from app.content import get_article_repository


class Command(BaseCommand):
    help = (
        "Report the state of the content repository (backend, branch, "
        "ahead/behind, uncommitted files, problems) and of the article index."
    )

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", help="Machine output.")
        parser.add_argument(
            "--fetch",
            action="store_true",
            help="Fetch from the remote first for accurate ahead/behind.",
        )
        parser.add_argument(
            "--check",
            action="store_true",
            help="Exit with status 1 unless everything is clean and indexed.",
        )

    def handle(self, **options):
        repository = get_article_repository()
        if options["fetch"] and hasattr(repository, "fetch"):
            try:
                repository.fetch()
            except FileContentError as exc:
                raise CommandError(f"Fetch failed: {exc}") from exc
        status = repository.status()
        healthy = self._healthy(status)
        if options["json"]:
            self.stdout.write(
                json.dumps({**status, "healthy": healthy}, indent=2, default=str)
            )
        else:
            self._print(status, healthy)
        if options["check"] and not healthy:
            raise CommandError("Content repository needs attention.", returncode=1)

    @staticmethod
    def _healthy(status):
        index = status.get("index") or {}
        if status.get("backend") == "git" and not status.get("ok"):
            return False
        if index and (
            index.get("state") in {"missing", "stale"} or index.get("last_error")
        ):
            return False
        return not status.get("problems")

    def _print(self, status, healthy):
        line = self.stdout.write
        line(f"Backend:    {status.get('backend')}")
        if status.get("backend") == "git":
            line(f"Remote:     {status.get('remote') or '-'}")
            if status.get("cloned"):
                line(f"State:      {status.get('state', '').upper()}")
                line(f"Branch:     {status.get('branch') or '(detached)'}")
                line(f"HEAD:       {status.get('head') or '-'}")
                line(
                    f"Upstream:   {status.get('upstream') or '-'} "
                    f"(ahead {status.get('ahead', 0)}, behind {status.get('behind', 0)})"
                )
                for label in ("modified", "untracked", "conflicted"):
                    for path in status.get(label) or ():
                        line(f"  {label}: {path}")
        index = status.get("index")
        if index:
            sha = (index.get("last_indexed_sha") or "")[:10]
            line(
                f"Index:      {index.get('state')} · {index.get('rows')} rows · "
                f"{index.get('invalid')} invalid" + (f" · @ {sha}" if sha else "")
            )
            if index.get("last_error"):
                line(self.style.ERROR(f"  last error: {index['last_error']}"))
        for warning in status.get("warnings") or ():
            line(self.style.WARNING(f"! {warning}"))
        for problem in status.get("problems") or ():
            line(self.style.WARNING(f"- {problem}"))
        line(
            self.style.SUCCESS("OK")
            if healthy
            else self.style.WARNING("Needs attention")
        )
