from ... import services
from ...conf import get_settings
from ...repository.git import GitRepository
from ...sync.engine import SyncEngine
from ...workflow.commits import ContentWriter
from ._base import FileContentCommand


class Command(FileContentCommand):
    help = (
        "Clone the content repository if needed, fetch and fast-forward it, push "
        "pending commits and update the content index incrementally."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--no-fetch",
            action="store_true",
            help="Do not talk to the remote; only reindex local commits.",
        )
        parser.add_argument("--no-push", action="store_true", help="Never push.")
        parser.add_argument(
            "--full", action="store_true", help="Rebuild the index instead of diffing."
        )

    def handle(self, **options):
        conf = get_settings()
        repo = services.get_repository()
        if not repo.exists() and conf.remote_url and not options["no_fetch"]:
            if conf.root.exists() and any(conf.root.iterdir()):
                self.warn(
                    f"{conf.root} exists but is not a Git working tree; not cloning."
                )
            else:
                self.stdout.write(f"Cloning {conf.branch} into {conf.root} ...")
                GitRepository.clone(
                    conf.remote_url,
                    conf.root,
                    branch=conf.branch,
                    remote_name=conf.remote_name,
                    git_binary=conf.git_binary,
                    timeout=conf.git_timeout,
                )
                services.reset()
                repo = services.get_repository()

        if options["full"] or options["no_fetch"] or not repo.exists():
            result = SyncEngine.default().sync(full=options["full"])
            self.ok(result.summary())
            return

        push = not (options["no_push"] or conf.read_only)
        outcome = ContentWriter.default().synchronize(push=push)
        for message in outcome.messages:
            self.stdout.write(message)
        if outcome.pulled:
            self.stdout.write(f"Fast-forwarded to {outcome.after.head[:10]}.")
        if outcome.pushed:
            self.stdout.write("Pushed local commits.")
        self.ok(outcome.sync.summary())
        if outcome.after.state.value != "clean":
            self.warn(f"Repository state: {outcome.after.state.value}")
