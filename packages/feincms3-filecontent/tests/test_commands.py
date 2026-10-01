import json
import shutil
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from feincms3_filecontent import services
from feincms3_filecontent.models import ContentIndex

from .conftest import commit_all, git, push_from, write


pytestmark = pytest.mark.django_db


def run(*args):
    out = StringIO()
    call_command(*args, stdout=out, stderr=out)
    return out.getvalue()


def test_sync_clones_missing_working_tree(content):
    shutil.rmtree(content)
    output = run("filecontent_sync")
    assert "Cloning main" in output
    assert (content / "about.md").exists()
    assert ContentIndex.objects.count() == 3


def test_sync_pulls_and_reindexes(content, other):
    run("filecontent_sync")
    push_from(other, "news.md", "---\ntitle: News\n---\n")
    output = run("filecontent_sync")
    assert "Fast-forwarded" in output
    assert "incremental: 1 upserted" in output


def test_sync_conflict_exits_with_error(content, other):
    push_from(other, "about.md", "---\ntitle: Remote\n---\n")
    write(content, "about.md", "---\ntitle: Local\n---\n")
    commit_all(content, "local")
    with pytest.raises(CommandError, match="Conflict: .*about.md") as info:
        run("filecontent_sync")
    assert info.value.returncode == 3


def test_rebuild(content):
    assert "full: 3 upserted" in run("filecontent_rebuild")


def test_repository_status(content):
    run("filecontent_rebuild")
    data = json.loads(run("filecontent_repository_status", "--json"))
    assert data["repository"]["state"] == "clean"
    assert data["index"]["up_to_date"] is True
    write(content, "about.md", "dirty")
    output = run("filecontent_repository_status")
    assert "State:      DIRTY" in output
    assert "Uncommitted changes: about.md" in output


def test_check(content):
    run("filecontent_rebuild")
    assert "3 document(s), 0 error(s), 0 warning(s)" in run("filecontent_check")
    write(content, "broken.md", "---\ntitle: [x\n---\n")
    (content / ".filecontent-tmp-zzz").write_text("partial")
    with pytest.raises(CommandError, match="1 error"):
        run("filecontent_check")
    (content / "broken.md").unlink()
    output = run("filecontent_check", "--fix")
    assert "Removed 1 temporary file" in output


def test_check_reports_unfinished_merge(content, other):
    push_from(other, "about.md", "---\ntitle: Remote\n---\n")
    write(content, "about.md", "---\ntitle: Local\n---\n")
    commit_all(content, "local")
    git(content, "fetch", "-q")
    git(content, "merge", "origin/main", check=False)
    with pytest.raises(CommandError):
        run("filecontent_check")
    output = run("filecontent_check", "--abort-operation")
    assert "Aborted unfinished merge" in output
    assert services.get_repository().operation_in_progress() is None


def test_history_and_rollback(content):
    first = services.get_repository().current_sha()
    write(content, "about.md", "---\ntitle: Changed\n---\n")
    commit_all(content, "Change about")
    history = run("filecontent_history", "about.md")
    assert "Change about" in history and "Initial content" in history
    assert "+title: Changed" in run("filecontent_history", "about.md", "--diff", "HEAD")
    output = run(
        "filecontent_rollback", "about.md", first, "--author", "Ada <ada@example.com>"
    )
    assert "Committed" in output and "Pushed" in output
    assert "We sell" in (content / "about.md").read_text()
    with pytest.raises(CommandError):
        run("filecontent_rollback", "about.md", first, "--author", "nope")
