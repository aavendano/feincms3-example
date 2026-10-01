"""
Review mode: edit -> branch -> commit -> push -> pull request -> review ->
merge -> main.

The served working tree is never switched away from the configured branch;
the edit is committed in a temporary worktree. Opening and merging pull
requests needs a configured ``GitProvider``; without one the branch is pushed
and the review happens wherever the team reviews branches.
"""

from dataclasses import dataclass

from .. import services
from ..conf import get_settings
from ..content.documents import content_hash
from ..exceptions import DivergedError, ProviderError, ReadOnlyError, StaleDocumentError
from .branches import BranchWorkspace, content_branch
from .commits import ContentWriter


@dataclass
class Proposal:
    branch: str
    sha: str | None
    pushed: bool
    pull_request: object = None


def propose_change(
    path,
    text,
    *,
    message,
    branch=None,
    author=None,
    expected_hash=None,
    title=None,
    body="",
    base=None,
    open_pull_request=True,
):
    conf = get_settings()
    if conf.read_only:
        raise ReadOnlyError("feincms3-filecontent is configured read-only.")
    repo = services.get_repository()
    store = services.get_store()
    document = services.get_validator().validate(path, text)
    path = document.path
    base = base or conf.branch
    branch = branch or content_branch("update", document.slug)
    repo.ensure_exists()

    with repo.lock():
        has_remote = bool(repo.remote_url())
        if has_remote:
            repo.fetch()
        if expected_hash is not None:
            current = content_hash(store.read_bytes(path)) if store.exists(path) else ""
            if current != expected_hash:
                raise StaleDocumentError(
                    "The document was changed by someone else since it was loaded",
                    [path],
                )
        remote_branch = f"{repo.remote_name}/{branch}"
        has_remote_branch = has_remote and repo.branch_exists(branch, remote=True)
        if has_remote_branch:
            start_point = remote_branch
        elif has_remote and repo.branch_exists(base, remote=True):
            start_point = f"{repo.remote_name}/{base}"
        else:
            start_point = base

        with BranchWorkspace(
            repo,
            branch,
            start_point=start_point,
            worktrees_dir=conf.worktrees_dir,
            exclude=conf.exclude,
        ) as workspace:
            if has_remote_branch:
                # A local branch left by an earlier (e.g. failed push) run must
                # be able to fast-forward to the remote one; otherwise stop.
                local, remote = (
                    workspace.worktree.current_sha(),
                    repo.current_sha(remote_branch),
                )
                if local != remote:
                    if workspace.worktree.is_ancestor(local, remote):
                        workspace.worktree.run("merge", "--ff-only", remote_branch)
                    elif not workspace.worktree.is_ancestor(remote, local):
                        raise DivergedError(
                            f"Local and remote {branch!r} have diverged",
                            repo.diverging_paths(local, remote),
                        )
            workspace.store.write(path, text)
            sha = workspace.worktree.commit(message, [path], author=author)
            pushed = False
            if has_remote and sha:
                repo.push(branch, cwd=workspace.path)
                pushed = True
        if pushed:
            # The remote branch is the authority; drop the local copy.
            repo.delete_branch(branch)

    proposal = Proposal(branch=branch, sha=sha, pushed=pushed)
    provider = services.get_provider()
    if open_pull_request and provider and pushed:
        existing = provider.find_pull_request(head=branch, base=base)
        proposal.pull_request = existing or provider.create_pull_request(
            head=branch,
            base=base,
            title=title or message.splitlines()[0],
            body=body,
        )
    return proposal


def merge_proposal(number, *, method="merge"):
    """Merge a pull request through the provider, then pull it locally."""
    provider = services.get_provider()
    if provider is None:
        raise ProviderError("No GitProvider is configured.")
    pull_request = provider.merge_pull_request(number, method=method)
    sync = ContentWriter.default().synchronize(push=False)
    return pull_request, sync
