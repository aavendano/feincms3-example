import pytest

from feincms3_filecontent import services
from feincms3_filecontent.exceptions import DivergedError, PushRejected
from feincms3_filecontent.repository import ChangeType, RepositoryStatus, redact
from feincms3_filecontent.repository.conflicts import ensure_can_write

from .conftest import commit_all, git, push_from, write


@pytest.fixture
def repo(content):
    return services.get_repository()


def test_basic_introspection(repo, remote_head):
    assert repo.exists()
    assert repo.current_branch() == "main"
    assert repo.current_sha() == remote_head()
    assert repo.status().state is RepositoryStatus.CLEAN
    assert repo.status().upstream == "origin/main"


def test_dirty(repo, content):
    write(content, "about.md", "changed")
    write(content, "new.md", "new")
    report = repo.status()
    assert report.state is RepositoryStatus.DIRTY
    assert report.modified == ["about.md"]
    assert report.untracked == ["new.md"]


def test_ahead_behind_diverged(repo, content, other):
    write(content, "local.md", "x")
    commit_all(content, "local")
    assert repo.status().state is RepositoryStatus.AHEAD

    push_from(other, "remote.md", "y")
    repo.fetch()
    report = repo.status()
    assert report.state is RepositoryStatus.DIVERGED
    assert (report.ahead, report.behind) == (1, 1)

    git(content, "reset", "-q", "--hard", "origin/main~1")
    repo.fetch()
    assert repo.status().state is RepositoryStatus.BEHIND


def test_conflicted(repo, content, other):
    push_from(other, "about.md", "remote version\n")
    write(content, "about.md", "local version\n")
    commit_all(content, "local")
    repo.fetch()
    git(content, "merge", "origin/main", check=False)
    report = repo.status()
    assert report.state is RepositoryStatus.CONFLICTED
    assert report.conflicted == ["about.md"]
    assert report.operation == "merge"
    with pytest.raises(Exception, match="unfinished merge"):
        ensure_can_write(repo, ["x.md"])
    assert repo.abort_operation() == "merge"
    assert repo.status().state is RepositoryStatus.DIVERGED


def test_ensure_can_write(repo, content, other):
    write(content, "about.md", "uncommitted")
    with pytest.raises(Exception, match="Uncommitted"):
        ensure_can_write(repo, ["about.md"])
    ensure_can_write(repo, ["other.md"])  # unrelated dirt is tolerated
    git(content, "checkout", "--", "about.md")

    write(content, "about.md", "local")
    commit_all(content, "local")
    push_from(other, "about.md", "remote")
    repo.fetch()
    with pytest.raises(DivergedError) as info:
        ensure_can_write(repo, ["x.md"])
    assert info.value.paths == ["about.md"]


def test_changed_files_classifies_changes(repo, content):
    base = repo.current_sha()
    write(content, "about.md", "modified")
    write(content, "added.md", "added")
    git(content, "mv", "blog/hello.md", "blog/hello-again.md")
    git(content, "rm", "-q", "de/about.md")
    commit_all(content, "changes")
    changes = {(c.change, c.path, c.old_path) for c in repo.changed_files(base).changes}
    assert changes == {
        (ChangeType.MODIFIED, "about.md", None),
        (ChangeType.ADDED, "added.md", None),
        (ChangeType.RENAMED, "blog/hello-again.md", "blog/hello.md"),
        (ChangeType.DELETED, "de/about.md", None),
    }
    full = repo.changed_files(None)
    assert {c.change for c in full.changes} == {ChangeType.ADDED}


def test_commit_only_includes_given_paths(repo, content):
    write(content, "about.md", "edited")
    write(content, "unrelated.md", "leave me alone")
    sha = repo.commit("Edit about", ["about.md"], author=("Ada", "ada@example.com"))
    assert sha == repo.current_sha()
    assert repo.status().untracked == ["unrelated.md"]
    entry = repo.log("about.md", max_count=1)[0]
    assert (entry.author_name, entry.author_email, entry.subject) == (
        "Ada",
        "ada@example.com",
        "Edit about",
    )
    # Nothing staged -> no commit
    assert repo.commit("noop", ["about.md"]) is None


def test_history_and_show(repo, content):
    first = repo.current_sha()
    write(content, "about.md", "v2")
    commit_all(content, "v2")
    history = repo.log("about.md")
    assert [e.subject for e in history] == ["v2", "Initial content"]
    assert "We sell" in repo.show("about.md", first)
    assert "+v2" in repo.commit_diff(history[0].sha, ["about.md"])


def test_push_rejected(repo, content, other):
    push_from(other, "remote.md", "y")
    write(content, "local.md", "x")
    commit_all(content, "local")
    with pytest.raises(PushRejected):
        repo.push()


def test_pull_is_fast_forward_only(repo, content, other):
    sha = push_from(other, "remote.md", "y")
    assert repo.pull() == sha
    push_from(other, "remote2.md", "z")
    write(content, "local.md", "x")
    commit_all(content, "local")
    with pytest.raises(DivergedError):
        repo.pull()


def test_branch_names(repo):
    repo.validate_branch_name("content/update-about")
    for bad in ("-x", "a..b", "a b", "x~1"):
        with pytest.raises(Exception, match="Invalid branch name"):
            repo.validate_branch_name(bad)


def test_redact():
    assert (
        redact("https://user:token@github.com/x.git") == "https://***@github.com/x.git"
    )
    assert redact("git@github.com:x/y.git") == "git@github.com:x/y.git"
