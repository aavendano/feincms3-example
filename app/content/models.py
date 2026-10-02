"""
Operational data for the content repository — never content.

``ArticleIndex`` is a *projection* of ``content/**/articles/*.md``: it exists
so listings can filter, order and paginate without reading every file. It can
be dropped at any time; ``./manage.py content_index --rebuild`` recreates it
from the files. Article bodies are not stored here.
"""

from django.db import models


class ArticleIndex(models.Model):
    market = models.CharField(max_length=2)
    locale = models.CharField(max_length=10)
    slug = models.CharField(max_length=200)
    title = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=20, blank=True)
    category = models.CharField(max_length=20, blank=True)
    publication_date = models.DateTimeField(null=True, blank=True)
    # SHA-256 of the file: the article's ``version``.
    version = models.CharField(max_length=64)
    # Change detection for the filesystem backend.
    mtime_ns = models.BigIntegerField(default=0)
    size = models.BigIntegerField(default=0)
    # Non-empty when the file could not be parsed; such rows are never listed.
    error = models.TextField(blank=True)
    indexed_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["market", "locale", "slug"], name="content_article_key"
            )
        ]
        indexes = [
            models.Index(
                fields=["market", "locale", "status", "publication_date"],
                name="content_article_listing",
            ),
            models.Index(fields=["category"], name="content_article_category"),
        ]
        verbose_name = "article index entry"
        verbose_name_plural = "article index"

    def __str__(self):
        return f"{self.market}/{self.locale}/{self.slug}"


class IndexState(models.Model):
    """Which content the index reflects (root, backend, last commit)."""

    name = models.CharField(max_length=50, unique=True)
    root = models.CharField(max_length=500, blank=True)
    backend = models.CharField(max_length=20, blank=True)
    last_indexed_sha = models.CharField(max_length=64, blank=True)
    last_mode = models.CharField(max_length=20, blank=True)
    indexed_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    def __str__(self):
        return self.name
