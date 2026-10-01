"""
Service locator: builds the configured store, parsers, repository and
provider once per process from ``FILECONTENT``.
"""

from functools import lru_cache

from django.utils.module_loading import import_string

from .conf import get_settings
from .content.parser import ParserRegistry
from .content.validation import DocumentValidator
from .repository.git import GitRepository
from .storage.filesystem import FileSystemContentStore


@lru_cache(maxsize=1)
def get_store():
    conf = get_settings()
    return FileSystemContentStore(
        conf.root, read_only=conf.read_only, exclude=conf.exclude
    )


@lru_cache(maxsize=1)
def get_registry():
    conf = get_settings()
    return ParserRegistry(conf.parsers, conf)


@lru_cache(maxsize=1)
def get_validator():
    return DocumentValidator(get_registry(), get_settings())


@lru_cache(maxsize=1)
def get_repository():
    conf = get_settings()
    return GitRepository(
        conf.root,
        remote_name=conf.remote_name,
        branch=conf.branch,
        git_binary=conf.git_binary,
        timeout=conf.git_timeout,
        lock_timeout=conf.lock_timeout,
        committer=(conf.commit_author_name, conf.commit_author_email),
    )


@lru_cache(maxsize=1)
def get_provider():
    """The configured ``GitProvider`` or ``None``."""
    conf = get_settings()
    if not conf.provider:
        return None
    cls = conf.provider["CLASS"]
    cls = import_string(cls) if isinstance(cls, str) else cls
    return cls(**conf.provider.get("OPTIONS", {}))


def reset():
    for factory in (
        get_store,
        get_registry,
        get_validator,
        get_repository,
        get_provider,
    ):
        # Tolerate factories replaced by test doubles.
        getattr(factory, "cache_clear", lambda: None)()
    from .feincms.renderer import loader  # noqa: PLC0415 - circular

    loader.clear()
