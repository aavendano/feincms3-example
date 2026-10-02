"""
Shared Django settings for the feincms3 example project.

Environment-specific values live in ``development`` / ``production``.
"""

import importlib.util
import os

from django.utils.translation import gettext_lazy as _


# Project root (feincms3-example/), not the settings package directory.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


INSTALLED_APPS = [
    # django-admin-react before django.contrib.admin so the package's
    # admin/base_site.html override (experience-toggle strip) wins.
    "django_admin_react",
    "django_admin_rest_api",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Libraries
    "feincms3",
    "tree_queries",
    "content_editor",
    # Libraries for content-editor plugins
    "imagefield",
    # Editorial content as Git-versioned Markdown files
    "feincms3_filecontent",
    # Our app
    "app",
    "app.pages",
    "app.articles",
    "app.content",
]

MIDDLEWARE = MIDDLEWARE_CLASSES = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "feincms3.applications.apps_middleware",
    "app.pages.middleware.page_if_404_middleware",
]

ROOT_URLCONF = "app.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "app.wsgi.application"

DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "en-us"
LANGUAGES = [
    ("en", _("English")),
    ("de", _("German")),
]

TIME_ZONE = "UTC"

USE_I18N = True

USE_L10N = True

USE_TZ = True

STATIC_URL = "/static/"
MEDIA_URL = "/media/"
MEDIA_ROOT = os.path.join(BASE_DIR, "media")

# React admin SPA reads the CSRF token from the cookie.
CSRF_COOKIE_HTTPONLY = False

# Optional branding / dual-admin toggle (legacy /admin/ + SPA /admin-react/).
DJANGO_ADMIN_REACT = {
    "BRAND_TITLE": "feincms3 example",
    "LEGACY_ADMIN_URL_PREFIX": "admin/",
    "REACT_ADMIN_URL_PREFIX": "admin-react/",
}

# feincms3-filecontent: Markdown documents live in a Git working tree under
# ``filecontent/``; ``./manage.py filecontent_sync`` clones it from
# FILECONTENT_REMOTE_URL on first run. Git authentication comes from SSH keys
# or a credential helper, never from this file.
FILECONTENT = {
    "ROOT": os.environ.get("FILECONTENT_ROOT", os.path.join(BASE_DIR, "filecontent")),
    "REMOTE_URL": os.environ.get("FILECONTENT_REMOTE_URL"),
    "BRANCH": os.environ.get("FILECONTENT_BRANCH", "main"),
    "READ_ONLY": os.environ.get("FILECONTENT_READ_ONLY") == "1",
}

# Filesystem-first article repository (POC, see docs/content-repository.md).
# Articles live in content/{MARKET}/{locale}/articles/{slug}.md; the ORM is
# not involved. Only the markets/locales listed here are read or written.
# Set CONTENT_REPOSITORY_BACKEND=git with a ROOT that is its own Git working
# tree to get one commit per edit, history and restore.
CONTENT_REPOSITORY = {
    "BACKEND": os.environ.get("CONTENT_REPOSITORY_BACKEND", "filesystem"),
    "ROOT": os.environ.get(
        "CONTENT_REPOSITORY_ROOT", os.path.join(BASE_DIR, "content")
    ),
    "GIT": {
        "BRANCH": os.environ.get("CONTENT_REPOSITORY_BRANCH", "main"),
        # ./manage.py content_clone clones this into ROOT on first run.
        "REMOTE_URL": os.environ.get("CONTENT_REPOSITORY_REMOTE_URL"),
        "AUTO_PUSH": os.environ.get("CONTENT_REPOSITORY_AUTO_PUSH", "1") == "1",
    },
    "MARKETS": {
        "CA": ["en", "fr"],
        "US": ["en", "es"],
    },
}

# The filesystem articles editor (app/static/content/article-editor.js) is
# hosted natively inside the React admin when the installed
# django-admin-react supports CUSTOM_PAGES; otherwise app/urls.py serves it
# as a standalone page at the same URL.
# Detect support without importing the package: importing
# django_admin_react.conf while settings are still loading would cache its
# settings before this block runs.
CONTENT_EDITOR_IN_SPA = (
    importlib.util.find_spec("django_admin_react") is not None
    and importlib.util.find_spec("django_admin_react.custom_pages") is not None
)
if CONTENT_EDITOR_IN_SPA:
    DJANGO_ADMIN_REACT["CUSTOM_PAGES"] = [
        {
            "path": "content/articles",
            "label": "Articles (files)",
            "group": "Content",
            "module": "content/article-editor.js",
            "permission": "articles.view_article",
        }
    ]
