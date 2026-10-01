"""
Filesystem-first editorial content (proof of concept, articles only).

    React Admin  ->  Django API (app.content.api)
                 ->  ContentRepository (app.content.repository)
                 ->  FilesystemArticleRepository (app.content.filesystem)
                 ->  content/{MARKET}/{locale}/articles/*.md

The Django ORM is not involved in storing these articles. See
docs/content-repository.md.
"""

from functools import lru_cache

from django.conf import settings
from django.core.signals import setting_changed
from django.dispatch import receiver


@lru_cache(maxsize=1)
def get_article_repository():
    """The configured article repository (filesystem backend for now)."""
    from .filesystem import FilesystemArticleRepository  # noqa: PLC0415

    conf = settings.CONTENT_REPOSITORY
    return FilesystemArticleRepository(conf["ROOT"], markets=conf["MARKETS"])


@receiver(setting_changed)
def _reset(*, setting, **kwargs):
    if setting == "CONTENT_REPOSITORY":
        get_article_repository.cache_clear()
