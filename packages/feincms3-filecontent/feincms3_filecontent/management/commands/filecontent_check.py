from django.core.management.base import CommandError

from ... import services
from ...conf import get_settings
from ...exceptions import DocumentValidationError
from ...repository.git import has_credentials
from ...sync.scanner import Scanner
from ...sync.state import get_state
from ._base import FileContentCommand


class Command(FileContentCommand):
    help = (
        "Check configuration, repository health, interrupted operations and "
        "validate every document. Exits non-zero when errors are found."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--fix",
            action="store_true",
            help="Remove temporary files left behind by interrupted writes.",
        )
        parser.add_argument(
            "--abort-operation",
            action="store_true",
            help="Abort an unfinished merge/rebase/cherry-pick in the working tree.",
        )

    def handle(self, **options):
        conf = get_settings()
        store = services.get_store()
        repo = services.get_repository()
        errors = warnings = 0

        if not conf.root.is_dir():
            raise CommandError(f"Content root {conf.root} does not exist.")
        if has_credentials(conf.remote_url):
            self.warn(
                "REMOTE_URL embeds credentials; use SSH keys or a credential helper."
            )
            warnings += 1

        leftovers = store.leftover_temp_files()
        if leftovers and options["fix"]:
            store.remove_temp_files()
            self.ok(f"Removed {len(leftovers)} temporary file(s).")
        elif leftovers:
            self.warn(
                f"Interrupted writes left temporary files: {', '.join(leftovers)}"
            )
            warnings += 1

        if repo.exists():
            operation = repo.operation_in_progress()
            if operation and options["abort_operation"]:
                repo.abort_operation()
                self.ok(f"Aborted unfinished {operation}.")
            elif operation:
                self.error(
                    f"An unfinished {operation} is in progress (use --abort-operation)."
                )
                errors += 1
            report = repo.status()
            if report.conflicted:
                self.error(f"Unmerged paths: {', '.join(report.conflicted)}")
                errors += 1
            if report.branch != conf.branch:
                self.error(f"Checked out {report.branch!r}, expected {conf.branch!r}.")
                errors += 1
            if report.modified or report.untracked:
                self.warn(
                    "Uncommitted changes: "
                    + ", ".join(report.modified + report.untracked)
                )
                warnings += 1
            state = get_state(conf.branch)
            if state.last_indexed_sha != (report.head or ""):
                self.warn("The content index is stale; run filecontent_sync.")
                warnings += 1
            if state.last_error:
                self.warn(f"Last sync failed: {state.last_error}")
                warnings += 1
        else:
            self.warn(
                f"{conf.root} is not a Git working tree (read-only directory mode)."
            )
            warnings += 1

        validator = services.get_validator()
        scanner = Scanner(store, services.get_registry())
        paths = scanner.paths()
        for path in paths:
            try:
                validator.validate(path, store.read_bytes(path))
            except DocumentValidationError as exc:
                self.error(str(exc))
                errors += 1

        summary = f"{len(paths)} document(s), {errors} error(s), {warnings} warning(s)."
        if errors:
            raise CommandError(summary)
        self.ok(summary)
