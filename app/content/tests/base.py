import datetime as dt
import shutil
import tempfile
from pathlib import Path

from django.test import override_settings

from app.content import get_article_repository, schemas


MARKETS = {"CA": ["en", "fr"], "US": ["en", "es"]}

DOC = """---
title: Hello
status: published
publication_date: '2026-01-02T03:04:05Z'
category: blog
---

Some **body**.
"""


def make_article(market="CA", locale="en", slug="hello", **fields):
    data = {
        "title": "Hello",
        "status": "published",
        "publication_date": "2026-01-02T03:04:05Z",
        "category": "blog",
        "body": "Some **body**.\n",
        **fields,
    }
    return schemas.build_article(schemas.ArticleKey(market, locale, slug), data)


class TempContentMixin:
    """
    Every test gets its own empty content root; real content is untouched.

    ``index = False`` tests the raw backend (no database); ``True`` the full
    stack used by the API and views (backend wrapped by the ORM index).
    """

    index = False

    def setUp(self):
        super().setUp()
        self.root = Path(tempfile.mkdtemp(prefix="content-tests-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        override = override_settings(
            CONTENT_REPOSITORY={
                "ROOT": str(self.root),
                "MARKETS": MARKETS,
                "INDEX": self.index,
            }
        )
        override.enable()
        self.addCleanup(override.disable)
        self.repo = get_article_repository()

    def write_file(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def past(self, days=1):
        return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat()

    def future(self, days=1):
        return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=days)).isoformat()
