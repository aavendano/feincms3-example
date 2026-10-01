from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from .. import services
from ..exceptions import UnsafePathError
from ..storage.filesystem import normalize_path
from .renderer import load_document


def validate_content_path(value):
    try:
        path = normalize_path(value)
    except UnsafePathError as exc:
        raise ValidationError(str(exc)) from exc
    if not services.get_registry().supports(path):
        raise ValidationError(
            _("Unsupported document type; expected one of %(suffixes)s.")
            % {"suffixes": ", ".join(services.get_registry().suffixes)}
        )
    if not services.get_store().exists(path):
        raise ValidationError(_("No document exists at %(path)s.") % {"path": path})


class FileContent(models.Model):
    """
    Abstract feincms3 plugin referencing a document by path.

    The body is never copied into the database; it is read from the
    ContentStore at render time::

        class FileContent(feincms3_filecontent.feincms.models.FileContent, PagePlugin):
            pass
    """

    content_path = models.CharField(
        _("document"),
        max_length=500,
        validators=[validate_content_path],
        help_text=_("Path of the document relative to the content repository."),
    )

    class Meta:
        abstract = True
        verbose_name = _("file content")
        verbose_name_plural = _("file contents")

    def __str__(self):
        return self.content_path

    def get_document(self):
        return load_document(self.content_path).document
