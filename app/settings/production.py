"""
Production settings template.

These values are examples only — adapt them before a real deploy.
Export ``DJANGO_SECRET_KEY`` (and adjust hosts / database) in the environment.
"""

import os

from .base import *  # noqa: F403
from .base import BASE_DIR


DEBUG = False

# Example: export DJANGO_SECRET_KEY='…' before starting the WSGI process.
SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]

# Example hostnames — replace with your real domain(s).
ALLOWED_HOSTS = ["example.com", "www.example.com"]

# Example Postgres connection — replace with your real credentials / env vars.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "feincms3_example"),
        "USER": os.environ.get("POSTGRES_USER", "feincms3"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "change-me"),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}

STATIC_ROOT = os.path.join(BASE_DIR, "staticfiles")

# Example hardening flags for HTTPS deployments.
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
