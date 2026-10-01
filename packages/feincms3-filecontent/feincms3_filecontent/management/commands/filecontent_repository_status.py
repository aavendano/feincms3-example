import json

from ... import services
from ...conf import get_settings
from ...repository.conflicts import describe
from ...repository.git import redact
from ...sync.state import get_state
from ._base import FileContentCommand


class Command(FileContentCommand):
    help = "Show the state of the content repository and of the content index."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true")
        parser.add_argument(
            "--fetch", action="store_true", help="Fetch before comparing."
        )

    def handle(self, **options):
        conf = get_settings()
        repo = services.get_repository()
        state = get_state(conf.branch)
        data = {
            "root": str(conf.root),
            "remote": redact(conf.remote_url or ""),
            "configured_branch": conf.branch,
            "read_only": conf.read_only,
            "repository": None,
            "index": {
                "last_indexed_sha": state.last_indexed_sha,
                "indexed_at": state.indexed_at.isoformat()
                if state.indexed_at
                else None,
                "last_sync_mode": state.last_sync_mode,
                "last_error": state.last_error,
            },
        }
        problems = []
        if repo.exists():
            if options["fetch"] and repo.remote_url():
                repo.fetch()
            report = repo.status()
            data["repository"] = report.as_dict()
            data["index"]["up_to_date"] = state.last_indexed_sha == (report.head or "")
            problems = describe(report)
            if report.branch and report.branch != conf.branch:
                problems.append(
                    f"Checked out {report.branch!r}, expected {conf.branch!r}."
                )
        else:
            problems.append(f"{conf.root} is not a Git working tree.")
        data["problems"] = problems

        if options["json"]:
            self.stdout.write(json.dumps(data, indent=2))
            return

        self.stdout.write(f"Root:       {data['root']}")
        self.stdout.write(f"Remote:     {data['remote'] or '-'}")
        if data["repository"]:
            r = data["repository"]
            self.stdout.write(f"State:      {r['state'].upper()}")
            self.stdout.write(f"Branch:     {r['branch'] or '(detached)'}")
            self.stdout.write(f"HEAD:       {r['head'] or '-'}")
            self.stdout.write(
                f"Upstream:   {r['upstream'] or '-'} (ahead {r['ahead']}, behind {r['behind']})"
            )
        index = data["index"]
        self.stdout.write(
            f"Index:      {index['last_indexed_sha'][:10] or '-'} "
            f"({index['last_sync_mode'] or 'never'}, "
            f"{'up to date' if index.get('up_to_date') else 'stale'})"
        )
        if index["last_error"]:
            self.error(f"Last sync error: {index['last_error']}")
        for problem in problems:
            self.warn(f"- {problem}")
        if not problems:
            self.ok("OK")
