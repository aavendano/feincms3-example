import pytest

from feincms3_filecontent import services
from feincms3_filecontent.models import ContentIndex, RepositoryState
from feincms3_filecontent.sync.engine import SyncEngine

from .conftest import commit_all, git, write


pytestmark = pytest.mark.django_db


def paths():
    return list(ContentIndex.objects.values_list("path", flat=True))


def test_rebuild_projects_every_document(content):
    result = SyncEngine.default().rebuild()
    head = services.get_repository().current_sha()
    assert result.mode == "full"
    assert paths() == ["about.md", "blog/hello.md", "de/about.md"]  # README.txt skipped
    hello = ContentIndex.objects.get(path="blog/hello.md")
    assert (hello.slug, hello.title, hello.locale, hello.git_sha) == (
        "hello-world",
        "Hello world",
        "",
        head,
    )
    assert ContentIndex.objects.get(path="de/about.md").locale == "de"
    state = RepositoryState.objects.get(branch="main")
    assert state.last_indexed_sha == head
    assert state.last_sync_mode == "full"


def test_first_sync_is_full_then_noop(content):
    assert SyncEngine.default().sync().mode == "full"
    assert SyncEngine.default().sync().mode == "noop"


def test_incremental_only_touches_changed_documents(content):
    engine = SyncEngine.default()
    engine.sync()
    untouched = ContentIndex.objects.get(path="about.md")

    write(content, "blog/hello.md", "---\ntitle: Hello again\nslug: hello-world\n---\n")
    write(content, "new.md", "---\ntitle: New\n---\n")
    git(content, "mv", "de/about.md", "de/ueber-uns.md")
    write(content, "notes.txt", "ignored")
    commit_all(content, "Edit, add, rename")

    result = engine.sync()
    assert result.mode == "incremental"
    assert sorted(result.upserted) == ["blog/hello.md", "de/ueber-uns.md", "new.md"]
    assert result.deleted == ["de/about.md"]
    assert paths() == ["about.md", "blog/hello.md", "de/ueber-uns.md", "new.md"]
    assert ContentIndex.objects.get(path="blog/hello.md").title == "Hello again"
    # The unchanged row was not rewritten.
    assert ContentIndex.objects.get(path="about.md").indexed_at == untouched.indexed_at

    git(content, "rm", "-q", "new.md")
    commit_all(content, "Delete")
    result = engine.sync()
    assert result.deleted == ["new.md"]
    assert "new.md" not in paths()


def test_unknown_previous_commit_triggers_full_rebuild(content):
    SyncEngine.default().sync()
    RepositoryState.objects.update(last_indexed_sha="0" * 40)
    result = SyncEngine.default().sync()
    assert result.mode == "full"
    assert "unknown" in result.reason


def test_index_can_be_dropped_and_rebuilt(content):
    SyncEngine.default().sync()
    before = list(ContentIndex.objects.values_list("path", "title", "content_hash"))
    ContentIndex.objects.all().delete()
    RepositoryState.objects.all().delete()
    SyncEngine.default().sync()
    assert (
        list(ContentIndex.objects.values_list("path", "title", "content_hash"))
        == before
    )


def test_invalid_documents_are_indexed_as_invalid(content):
    write(content, "broken.md", "---\ntitle: [oops\n---\n")
    write(content, "untitled.md", "no front matter")
    commit_all(content, "bad docs")
    result = SyncEngine.default().rebuild()
    assert sorted(result.invalid) == ["broken.md", "untitled.md"]
    broken = ContentIndex.objects.get(path="broken.md")
    assert broken.status == ContentIndex.Status.INVALID
    assert "Invalid YAML" in broken.error


def test_plain_directory_without_git(tmp_path, settings):
    root = tmp_path / "plain"
    root.mkdir()
    (root / "page.md").write_text("---\ntitle: Plain\n---\n")
    settings.FILECONTENT = {"ROOT": str(root), "READ_ONLY": True}
    services.reset()
    result = SyncEngine.default().sync()
    assert result.mode == "full"
    assert result.to_sha is None
    assert paths() == ["page.md"]


def test_failures_are_recorded(content, monkeypatch):
    engine = SyncEngine.default()

    def boom(*args, **kwargs):
        raise RuntimeError("database on fire")

    monkeypatch.setattr(engine.projector, "bulk_create", boom)
    with pytest.raises(RuntimeError):
        engine.sync()
    assert RepositoryState.objects.get(branch="main").last_error == "database on fire"
