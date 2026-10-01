"""
ORM projection of the repository.

Nothing in these tables is authoritative: ``filecontent_rebuild`` deletes and
recreates every row from the working tree. Never edit them by hand.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class ContentIndex(models.Model):
    class Status(models.TextChoices):
        OK = "ok", _("ok")
        INVALID = "invalid", _("invalid")

    path = models.CharField(_("path"), max_length=500, unique=True)
    content_type = models.CharField(_("content type"), max_length=100)
    locale = models.CharField(_("locale"), max_length=20, blank=True, db_index=True)
    slug = models.CharField(_("slug"), max_length=200, db_index=True)
    title = models.CharField(_("title"), max_length=500)
    metadata = models.JSONField(_("metadata"), default=dict, blank=True)
    content_hash = models.CharField(_("content hash"), max_length=64)
    git_sha = models.CharField(_("Git SHA"), max_length=64, blank=True)
    modified_at = models.DateTimeField(_("modified at"), null=True, blank=True)
    indexed_at = models.DateTimeField(_("indexed at"), auto_now=True)
    status = models.CharField(
        _("status"), max_length=20, choices=Status.choices, default=Status.OK
    )
    error = models.TextField(_("error"), blank=True)

    class Meta:
        ordering = ["path"]
        verbose_name = _("document")
        verbose_name_plural = _("documents")
        indexes = [models.Index(fields=["locale", "slug"])]
        permissions = [
            ("edit_document", _("Can edit, commit and restore documents")),
            ("manage_repository", _("Can synchronize and rebuild the content index")),
        ]

    def __str__(self):
        return self.path


class RepositoryState(models.Model):
    """Bookkeeping for incremental sync: which commit the index reflects."""

    branch = models.CharField(_("branch"), max_length=200, unique=True)
    last_indexed_sha = models.CharField(
        _("last indexed SHA"), max_length=64, blank=True
    )
    indexed_at = models.DateTimeField(_("indexed at"), null=True, blank=True)
    last_sync_mode = models.CharField(_("last sync mode"), max_length=20, blank=True)
    last_error = models.TextField(_("last error"), blank=True)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    class Meta:
        verbose_name = _("repository state")
        verbose_name_plural = _("repository states")

    def __str__(self):
        sha = self.last_indexed_sha[:10] or "-"
        return f"{self.branch} @ {sha}"
