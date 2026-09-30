"""Local development settings (default for ``manage.py``)."""

import os

from .base import *  # noqa: F403
from .base import BASE_DIR


SECRET_KEY = "=l8r3p_(egb1n%j&i*r5zr=0lo68@!7y=dx^p(5eip%6kpt-3p"

DEBUG = True

ALLOWED_HOSTS = []

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.path.join(BASE_DIR, "db.sqlite3"),
    }
}
