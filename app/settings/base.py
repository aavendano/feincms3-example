"""
Shared Django settings for the feincms3 example project.

Environment-specific values live in ``development`` / ``production``.
"""

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
    # Our app
    "app",
    "app.pages",
    "app.articles",
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