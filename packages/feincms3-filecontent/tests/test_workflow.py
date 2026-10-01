import pytest

from feincms3_filecontent import services
from feincms3_filecontent.content.documents import content_hash
from feincms3_filecontent.exceptions import (
    DirtyWorkingTree,
    DivergedError,
    DocumentValidationError,
    MergeConflict,
    ReadOnlyError,
    StaleDocumentError,
)
from feincms3_filecontent.models import ContentIndex
from feincms3_filecontent.providers.base import GitProvider, PullRequest
from feincms3_filecontent.repository import RepositoryStatus
from feincms3_filecontent.workflow import rollback
from feincms3_filecontent.workflow.branches import content_branch, translation_branch
from feincms3_filecontent.workflow.commits import ContentWriter
from feincms3_filecontent.workflow.proposals import propose_change

from .conftest import git, push_from, write


pytestmark = pytest.mark.django_db

DOC = "---\ntitle: Contact\n---\n\nWrite to us.\n"


@pytest.fixture
def writer(content):
    return ContentWriter.default()


def remote_file(remote, path, ref="main"):
    return git(remote, "show", f"{ref}:{path}", check=False)


def test_save_validates_commits_pushes_and_indexes(
    writer, content, remote, remote_head
):
    result = writer.save(
        "contact.md", DOC, message="Add contact page", author=("Ada", "ada@example.com")
    )
    assert result.changed and result.pushed and result.ok
    assert result.sha == remote_head()
    assert remote_file(remote, "contact.md") == DOC.strip()
    assert (
        git(remote, "log", "-1", "--format=%an <%ae>|%s")
        == "Ada <ada@example.com>|Add contact page"
    )
    assert ContentIndex.objects.get(path="contact.md").git_sha == result.sha
    assert services.get_repository().status().state is RepositoryStatus.CLEAN


def test_unchanged_save_is_a_noop(writer, content):
    text = (content / "about.md").read_text()
    result = writer.save("about.md", text, message="noop")
    assert not result.changed
    assert result.sha is None


def test_invalid_document_is_never_written(writer, content):
    with pytest.raises(DocumentValidationError):
        writer.save("about.md", "---\ntitle: [oops\n---\n", message="break it")
    assert "We sell" in (content / "about.md").read_text()
    with pytest.raises(DocumentValidationError):
        writer.save("../outside.md", DOC, message="escape")


def test_concurrent_edit_is_detected(writer, content):
    loaded = content_hash((content / "about.md").read_bytes())
    writer.save("about.md", DOC, message="first editor", expected_hash=loaded)
    with pytest.raises(StaleDocumentError):
        writer.save(
            "about.md", DOC + "x", message="second editor", expected_hash=loaded
        )
    with pytest.raises(StaleDocumentError):
        writer.save("about.md", DOC, message="create", expected_hash="")


def test_failed_commit_restores_working_tree(writer, content, monkeypatch):
    original = (content / "about.md").read_text()

    def boom(*args, **kwargs):
        raise RuntimeError("git crashed")

    monkeypatch.setattr(services.get_repository(), "commit", boom)
    with pytest.raises(RuntimeError):
        writer.save("about.md", DOC, message="edit")
    with pytest.raises(RuntimeError):
        writer.save("brand-new.md", DOC, message="add")
    monkeypatch.undo()
    assert (content / "about.md").read_text() == original
    assert not (content / "brand-new.md").exists()
    assert services.get_repository().status().state is RepositoryStatus.CLEAN


def test_dirty_target_is_refused(writer, content):
    write(content, "about.md", "hand edit")
    with pytest.raises(DirtyWorkingTree):
        writer.save("about.md", DOC, message="edit")
    assert (content / "about.md").read_text() == "hand edit"


def test_rejected_push_is_reported_not_merged(writer, content, other, remote_head):
    push_from(other, "elsewhere.md", "---\ntitle: E\n---\n")
    remote_before = remote_head()
    result = writer.save("contact.md", DOC, message="Add contact")
    assert result.changed and not result.pushed
    assert "rejected" in result.push_error
    assert remote_head() == remote_before
    services.get_repository().fetch()
    assert services.get_repository().status().state is RepositoryStatus.DIVERGED


def test_synchronize_fast_forwards_and_reindexes(writer, content, other):
    writer.sync_engine.sync()
    push_from(other, "news.md", "---\ntitle: News\n---\n")
    outcome = writer.synchronize()
    assert outcome.pulled
    assert (content / "news.md").exists()
    assert outcome.sync.upserted == ["news.md"]


def test_synchronize_rebases_disjoint_divergence(writer, content, other, remote_head):
    push_from(other, "news.md", "---\ntitle: News\n---\n")
    writer.save("contact.md", DOC, message="Add contact")  # push rejected
    outcome = writer.synchronize()
    assert outcome.rebased and outcome.pushed
    assert remote_head() == services.get_repository().current_sha()
    assert remote_file(remote := other.parent / "remote.git", "contact.md")
    assert remote_file(remote, "news.md")


def test_synchronize_refuses_same_file_divergence(writer, content, other):
    push_from(other, "about.md", "---\ntitle: Remote about\n---\n")
    writer.save("about.md", DOC, message="Local about")
    head = services.get_repository().current_sha()
    with pytest.raises(DivergedError) as info:
        writer.synchronize()
    assert info.value.paths == ["about.md"]
    # Nothing was touched.
    assert services.get_repository().current_sha() == head
    assert (content / "about.md").read_text() == DOC


def test_git_policy_still_raises_on_textual_conflict(settings, content, other):
    settings.FILECONTENT = {**settings.FILECONTENT, "CONFLICT_POLICY": "git"}
    writer = ContentWriter.default()
    push_from(other, "about.md", "---\ntitle: Remote about\n---\n")
    writer.save("about.md", DOC, message="Local about")
    head = services.get_repository().current_sha()
    with pytest.raises(MergeConflict):
        writer.synchronize()
    report = services.get_repository().status()
    assert report.operation is None
    assert report.head == head


def test_delete_and_move(writer, content, remote):
    writer.move("about.md", "company/about.md", message="Move about")
    assert remote_file(remote, "company/about.md")
    assert not remote_file(remote, "about.md")
    writer.delete("company/about.md", message="Remove about")
    assert not remote_file(remote, "company/about.md")
    assert (
        not ContentIndex.objects.filter(path__contains="about.md")
        .exclude(path="de/about.md")
        .exists()
    )


def test_read_only_refuses_writes(settings, content):
    settings.FILECONTENT = {**settings.FILECONTENT, "READ_ONLY": True}
    with pytest.raises(ReadOnlyError):
        ContentWriter.default().save("contact.md", DOC, message="x")


def test_history_and_non_destructive_restore(writer, content, remote):
    first = services.get_repository().current_sha()
    original = (content / "about.md").read_text()
    writer.save("about.md", DOC, message="Rewrite about")
    history_before = rollback.history("about.md")
    assert [e.subject for e in history_before] == ["Rewrite about", "Initial content"]
    assert "We sell" in rollback.version("about.md", first)
    assert "+Write to us." in rollback.version_diff("about.md", history_before[0].sha)

    result = rollback.restore("about.md", first[:8], author=("Ada", "ada@example.com"))
    assert result.changed and result.pushed
    assert (content / "about.md").read_text() == original
    subjects = [e.subject for e in rollback.history("about.md")]
    assert subjects == [
        f"Restore about.md to {first[:10]}",
        "Rewrite about",
        "Initial content",
    ]
    assert remote_file(remote, "about.md") == original.strip()


class FakeProvider(GitProvider):
    def __init__(self):
        self.created = []

    def create_pull_request(self, *, head, base, title, body=""):
        self.created.append((head, base, title))
        return PullRequest(1, "https://example.com/pr/1", "open", title, head, base)

    def find_pull_request(self, *, head, base):
        return None

    def get_pull_request(self, number):
        raise NotImplementedError

    def merge_pull_request(self, number, *, method="merge"):
        raise NotImplementedError

    def get_status(self, ref):
        return ""


def test_review_mode_uses_branch_and_keeps_served_tree(content, remote, monkeypatch):
    provider = FakeProvider()
    monkeypatch.setattr(services, "get_provider", lambda: provider)
    head = services.get_repository().current_sha()
    proposal = propose_change(
        "about.md", DOC, message="Rewrite about page", author=("Ada", "ada@example.com")
    )
    assert proposal.branch == "content/update-about"
    assert proposal.pushed
    assert remote_file(remote, "about.md", ref="content/update-about") == DOC.strip()
    # main and the served working tree are untouched
    assert "We sell" in remote_file(remote, "about.md")
    assert "We sell" in (content / "about.md").read_text()
    repo = services.get_repository()
    assert repo.current_sha() == head and repo.current_branch() == "main"
    assert repo.status().state is RepositoryStatus.CLEAN
    assert provider.created == [("content/update-about", "main", "Rewrite about page")]
    assert proposal.pull_request.number == 1

    # A second round on the same branch builds on top of the first.
    propose_change(
        "about.md", DOC + "More.\n", message="Second round", open_pull_request=False
    )
    assert git(
        remote, "log", "--format=%s", "-2", "content/update-about"
    ).splitlines() == [
        "Second round",
        "Rewrite about page",
    ]


def test_branch_names():
    assert content_branch("update", "About Us") == "content/update-about-us"
    assert content_branch("article", 123) == "content/article-123"
    assert translation_branch("fr", "article", 123) == "translation/fr/article-123"
