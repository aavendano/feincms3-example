from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class FileContentConfig(AppConfig):
    name = "feincms3_filecontent"
    label = "feincms3_filecontent"
    verbose_name = _("file content")
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from . import checks  # noqa: F401, PLC0415 - registers system checks
