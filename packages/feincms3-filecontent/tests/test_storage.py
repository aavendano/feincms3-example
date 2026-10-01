import os

import pytest

from feincms3_filecontent.exceptions import (
    DocumentExists,
    DocumentNotFound,
    ReadOnlyError,
    UnsafePathError,
)
from feincms3_filecontent.storage.filesystem import (
    TEMP_PREFIX,
    FileSystemContentStore,
    normalize_path,
)


@pytest.fixture
def store(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.md").write_text("A")
    (root / "dir").mkdir()
    (root / "dir" / "b.md").write_text("B")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("secret")
    (root / ".hidden.md").write_text("hidden")
    return FileSystemContentStore(root)


@pytest.mark.parametrize(
    "path",
    [
        "",
        "../x.md",
        "dir/../../x.md",
        "/etc/passwd",
        "C:/x.md",
        "a\\b.md",
        "x\x00.md",
        "..",
    ],
)
def test_normalize_rejects_unsafe_paths(path):
    with pytest.raises(UnsafePathError):
        normalize_path(path)


def test_normalize_cleans_paths():
    assert normalize_path("./dir//b.md") == "dir/b.md"


def test_git_directory_is_never_reachable(store):
    with pytest.raises(UnsafePathError):
        store.read(".git/config")
    assert not store.exists(".git/config")
    with pytest.raises(UnsafePathError):
        store.write(".git/hooks/post-commit", "boom")


def test_symlink_escape_is_rejected(store, tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("secret")
    os.symlink(outside, store.root / "link.md")
    with pytest.raises(UnsafePathError):
        store.read("link.md")
    assert "link.md" not in store.list()


def test_read_list_stat(store):
    assert store.read("a.md") == "A"
    assert store.list() == ["a.md", "dir/b.md"]
    assert store.list("dir") == ["dir/b.md"]
    assert store.list(suffixes=(".txt",)) == []
    assert store.stat("dir/b.md").size == 1
    with pytest.raises(DocumentNotFound):
        store.read("missing.md")


def test_atomic_write_creates_directories_and_leaves_no_temp_files(store):
    store.write("new/deep/c.md", "C")
    assert store.read("new/deep/c.md") == "C"
    assert store.leftover_temp_files() == []
    with pytest.raises(DocumentExists):
        store.write("a.md", "X", overwrite=False)
    with pytest.raises(DocumentNotFound):
        store.write("nope.md", "X", create=False)


def test_failed_write_keeps_previous_content(store, monkeypatch):
    def boom(*args):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError, match="disk full"):
        store.write("a.md", "half-written")
    monkeypatch.undo()
    assert store.read("a.md") == "A"
    assert store.leftover_temp_files() == []


def test_move_and_delete_prune_empty_directories(store):
    store.move("dir/b.md", "other/b.md")
    assert not (store.root / "dir").exists()
    assert store.read("other/b.md") == "B"
    store.delete("other/b.md")
    assert not (store.root / "other").exists()
    with pytest.raises(DocumentNotFound):
        store.delete("other/b.md")


def test_read_only(store):
    ro = FileSystemContentStore(store.root, read_only=True)
    assert ro.read("a.md") == "A"
    for call in (
        lambda: ro.write("a.md", "x"),
        lambda: ro.delete("a.md"),
        lambda: ro.move("a.md", "b.md"),
    ):
        with pytest.raises(ReadOnlyError):
            call()


def test_temp_file_names_are_reserved_and_cleanable(store):
    leftover = store.root / "dir" / f"{TEMP_PREFIX}abc"
    leftover.write_text("partial")
    with pytest.raises(UnsafePathError):
        store.read(f"dir/{TEMP_PREFIX}abc")
    assert store.leftover_temp_files() == [f"dir/{TEMP_PREFIX}abc"]
    store.remove_temp_files()
    assert store.leftover_temp_files() == []
