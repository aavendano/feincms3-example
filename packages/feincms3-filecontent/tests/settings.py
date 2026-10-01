import tempfile
from pathlib import Path


SECRET_KEY = "tests"
DEBUG = False
ALLOWED_HOSTS = ["*"]
USE_TZ = True
LANGUAGE_CODE = "en"
LANGUAGES = [("en", "English"), ("de", "German"), ("fr", "French")]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "feincms3",
    "content_editor",
    "tree_queries",
    "feincms3_filecontent",
    "tests.testapp",
]
MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]
ROOT_URLCONF = "tests.testapp.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]
STATIC_URL = "/static/"
# Replaced per test by the ``content`` fixture.
FILECONTENT = {"ROOT": str(Path(tempfile.gettempdir()) / "filecontent-tests-unused")}
