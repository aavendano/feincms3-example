import subprocess
from pathlib import Path

import pytest

from feincms3_filecontent import services


ABOUT = """---
title: About us
---

# About us

We sell **things**.
"""

HELLO = """---
title: Hello world
slug: hello-world
date: 2026-01-15
tags: [news, launch]
---

First post.
"""

ABOUT_DE = """---
title: Über uns
---

Wir verkaufen Dinge.
"""


@pytest.fixture(autouse=True)
def isolated_git(tmp_path, monkeypatch):
    """Keep the user's global Git configuration out of the tests."""
    config = tmp_path / "gitconfig"
    config.write_text(
        "[init]\n\tdefaultBranch = main\n[advice]\n\tdetachedHead = false\n"
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for key in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{key}_NAME", "Test Seeder")
        monkeypatch.setenv(f"GIT_{key}_EMAIL", "seed@example.com")


def git(cwd, *args, check=True):
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False
    )
    if check and proc.returncode:
        raise AssertionError(f"git {' '.join(args)}: {proc.stderr}")
    return proc.stdout.strip()


def write(root, path, text):
    target = Path(root) / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)


def commit_all(cwd, message):
    git(cwd, "add", "--all")
    git(cwd, "commit", "-q", "-m", message)
    return git(cwd, "rev-parse", "HEAD")


@pytest.fixture
def remote(tmp_path):
    """A bare repository playing the role of GitHub/GitLab — no network involved."""
    bare = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    seed = tmp_path / "seed"
    git(tmp_path, "clone", "-q", str(bare), str(seed))
    write(seed, "about.md", ABOUT)
    write(seed, "blog/hello.md", HELLO)
    write(seed, "de/about.md", ABOUT_DE)
    write(seed, "README.txt", "Not a document.\n")
    commit_all(seed, "Initial content")
    git(seed, "push", "-q", "origin", "main")
    return bare


@pytest.fixture
def other(tmp_path, remote):
    """A second clone: another editor working concurrently."""
    path = tmp_path / "other"
    git(tmp_path, "clone", "-q", str(remote), str(path))
    return path


@pytest.fixture
def content(tmp_path, remote, settings):
    """The local working tree configured as FILECONTENT["ROOT"]."""
    root = tmp_path / "content"
    git(tmp_path, "clone", "-q", str(remote), str(root))
    settings.FILECONTENT = {
        "ROOT": str(root),
        "REMOTE_URL": str(remote),
        "SHOW_ERRORS": False,
    }
    services.reset()
    yield root
    services.reset()


@pytest.fixture
def remote_head(remote):
    def head(branch="main"):
        return git(remote, "rev-parse", branch)

    return head


def push_from(clone, path, text, message="Remote edit"):
    write(clone, path, text)
    sha = commit_all(clone, message)
    git(clone, "push", "-q", "origin", "main")
    return sha
