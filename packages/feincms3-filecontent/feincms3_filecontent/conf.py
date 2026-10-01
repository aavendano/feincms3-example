"""
Settings access.

All configuration lives in a single ``FILECONTENT`` dictionary::

    FILECONTENT = {
        "ROOT": BASE_DIR / "content",          # local working tree (required)
        "REMOTE_URL": os.environ.get("FILECONTENT_REMOTE_URL"),
        "BRANCH": "main",
        "READ_ONLY": False,
    }

Credentials never belong here as literals: Git authentication is delegated to
SSH keys / Git credential helpers and provider tokens are read from the
environment variable named by ``PROVIDER["OPTIONS"]["token_env"]``.
"""

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.core.signals import setting_changed
from django.dispatch import receiver
from django.utils.module_loading import import_string

from .exceptions import ConfigurationError


DEFAULTS = {
    "ROOT": None,
    "REMOTE_URL": None,
    "REMOTE_NAME": "origin",
    "BRANCH": "main",
    "READ_ONLY": False,
    # Push to the remote right after each commit.
    "AUTO_PUSH": True,
    # Fallback commit identity when no user is given.
    "COMMIT_AUTHOR_NAME": "feincms3-filecontent",
    "COMMIT_AUTHOR_EMAIL": "filecontent@localhost",
    # Linked worktrees used for review branches, outside the served tree.
    "WORKTREES_DIR": None,
    # Extension -> parser class (dotted path or class).
    "PARSERS": {
        ".md": "feincms3_filecontent.content.parser.MarkdownParser",
        ".markdown": "feincms3_filecontent.content.parser.MarkdownParser",
    },
    "MARKDOWN_EXTENSIONS": ["extra", "sane_lists", "toc"],
    "MARKDOWN_EXTENSION_CONFIGS": {},
    # Optional callable(html) -> html applied after rendering.
    "SANITIZER": None,
    "REQUIRED_FIELDS": ["title"],
    "MAX_DOCUMENT_SIZE": 1024 * 1024,
    # Top-level names never served, indexed or written.
    "EXCLUDE": [".git", ".github", ".gitlab", "node_modules"],
    # "strict": refuse to integrate divergent histories that touched the same
    # file on both sides, even if Git could merge the hunks.
    # "git": let Git's three-way merge decide; textual conflicts still raise.
    "CONFLICT_POLICY": "strict",
    "GIT_BINARY": "git",
    "GIT_TIMEOUT": 120,
    "LOCK_TIMEOUT": 30,
    # {"CLASS": "feincms3_filecontent.providers.github.GitHubProvider",
    #  "OPTIONS": {"repository": "owner/name", "token_env": "GITHUB_TOKEN"}}
    "PROVIDER": None,
    # Render a visible error box instead of an empty string when a document
    # cannot be rendered. Defaults to ``settings.DEBUG``.
    "SHOW_ERRORS": None,
}


@dataclass(frozen=True)
class FileContentSettings:
    root: Path
    remote_url: str | None
    remote_name: str
    branch: str
    read_only: bool
    auto_push: bool
    commit_author_name: str
    commit_author_email: str
    worktrees_dir: Path
    parsers: dict = field(hash=False)
    markdown_extensions: list = field(hash=False)
    markdown_extension_configs: dict = field(hash=False)
    sanitizer: object
    required_fields: tuple
    max_document_size: int
    exclude: tuple
    conflict_policy: str
    git_binary: str
    git_timeout: int
    lock_timeout: int
    provider: dict | None = field(hash=False)
    show_errors: bool


def build_settings(overrides=None):
    raw = {**DEFAULTS, **getattr(settings, "FILECONTENT", {}), **(overrides or {})}
    unknown = set(raw) - set(DEFAULTS)
    if unknown:
        raise ConfigurationError(
            f"Unknown FILECONTENT keys: {', '.join(sorted(unknown))}"
        )
    if not raw["ROOT"]:
        raise ConfigurationError('FILECONTENT["ROOT"] is required.')
    if raw["CONFLICT_POLICY"] not in {"strict", "git"}:
        raise ConfigurationError(
            'FILECONTENT["CONFLICT_POLICY"] must be "strict" or "git".'
        )

    root = Path(raw["ROOT"]).expanduser().resolve()
    worktrees = raw["WORKTREES_DIR"]
    worktrees = (
        Path(worktrees).expanduser().resolve()
        if worktrees
        else root.with_name(root.name + ".worktrees")
    )
    sanitizer = raw["SANITIZER"]
    if isinstance(sanitizer, str):
        sanitizer = import_string(sanitizer)
    show_errors = raw["SHOW_ERRORS"]
    if show_errors is None:
        show_errors = settings.DEBUG

    return FileContentSettings(
        root=root,
        remote_url=raw["REMOTE_URL"] or None,
        remote_name=raw["REMOTE_NAME"],
        branch=raw["BRANCH"],
        read_only=bool(raw["READ_ONLY"]),
        auto_push=bool(raw["AUTO_PUSH"]),
        commit_author_name=raw["COMMIT_AUTHOR_NAME"],
        commit_author_email=raw["COMMIT_AUTHOR_EMAIL"],
        worktrees_dir=worktrees,
        parsers=dict(raw["PARSERS"]),
        markdown_extensions=list(raw["MARKDOWN_EXTENSIONS"]),
        markdown_extension_configs=dict(raw["MARKDOWN_EXTENSION_CONFIGS"]),
        sanitizer=sanitizer,
        required_fields=tuple(raw["REQUIRED_FIELDS"]),
        max_document_size=int(raw["MAX_DOCUMENT_SIZE"]),
        exclude=tuple(raw["EXCLUDE"]),
        conflict_policy=raw["CONFLICT_POLICY"],
        git_binary=raw["GIT_BINARY"],
        git_timeout=int(raw["GIT_TIMEOUT"]),
        lock_timeout=int(raw["LOCK_TIMEOUT"]),
        provider=raw["PROVIDER"],
        show_errors=bool(show_errors),
    )


@lru_cache(maxsize=1)
def get_settings():
    return build_settings()


@receiver(setting_changed)
def _reset(*, setting, **kwargs):
    if setting in {"FILECONTENT", "DEBUG"}:
        get_settings.cache_clear()
        # Services are built from settings; drop them too.
        from . import services  # noqa: PLC0415 - circular

        services.reset()
