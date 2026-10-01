"""
Filesystem-first editorial content (proof of concept, articles only).

    React Admin  ->  Django API (app.content.api)
                 ->  ContentRepository (app.content.repository)
                 ->  FilesystemArticleRepository (app.content.filesystem)
                     or GitArticleRepository (app.content.git, one commit per change)
                 ->  content/{MARKET}/{locale}/articles/*.md

The Django ORM is not involved in storing these articles. See
docs/content-repository.md.
"""

from functools import lru_cache

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.signals import setting_changed
from django.dispatch import receiver


@lru_cache(maxsize=1)
def get_article_repository():
    """
    The configured article repository::

        CONTENT_REPOSITORY = {
            "BACKEND": "filesystem",   # or "git": one commit per change
            "ROOT": ...,               # for "git": root of its own working tree
            "MARKETS": {"CA": ["en", "fr"]},
            "GIT": {"BRANCH": "main", "AUTO_PUSH": True},
            "INDEX": True,             # list/count from the ORM index (default)
        }
    """
    conf = settings.CONTENT_REPOSITORY
    repository = _backend(conf)
    if conf.get("INDEX", True):
        from .index import IndexedArticleRepository  # noqa: PLC0415

        repository = IndexedArticleRepository(repository)
    return repository


def _backend(conf):
    from .filesystem import FilesystemArticleRepository  # noqa: PLC0415
    from .git import GitArticleRepository  # noqa: PLC0415

    backend = conf.get("BACKEND", "filesystem")
    if backend == "filesystem":
        return FilesystemArticleRepository(conf["ROOT"], markets=conf["MARKETS"])
    if backend == "git":
        git = conf.get("GIT", {})
        return GitArticleRepository(
            conf["ROOT"],
            markets=conf["MARKETS"],
            branch=git.get("BRANCH", "main"),
            remote_name=git.get("REMOTE_NAME", "origin"),
            auto_push=git.get("AUTO_PUSH", True),
            committer=(
                git.get("COMMITTER_NAME", "feincms3 content"),
                git.get("COMMITTER_EMAIL", "content@localhost"),
            ),
        )
    raise ImproperlyConfigured(f"Unknown CONTENT_REPOSITORY backend {backend!r}")


@receiver(setting_changed)
def _reset(*, setting, **kwargs):
    if setting == "CONTENT_REPOSITORY":
        get_article_repository.cache_clear()
