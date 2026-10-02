from django.apps import AppConfig


class ContentConfig(AppConfig):
    name = "app.content"
    label = "content"
    verbose_name = "Content repository"
    default_auto_field = "django.db.models.BigAutoField"
