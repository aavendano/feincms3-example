import os

from django.test import SimpleTestCase

from app.content import schemas
from app.content.exceptions import (
    DocumentAlreadyExists,
    DocumentNotFound,
    InvalidDocument,
    OperationNotSupported,
    VersionConflict,
)
from app.content.repository import ORDER_OLDEST_FIRST, ArticleFilter

from .base import DOC, TempContentMixin, make_article


class ReadTests(TempContentMixin, SimpleTestCase):
    def setUp(self):
        super().setUp()
        self.write_file("CA/en/articles/hello.md", DOC)
        self.write_file(
            "CA/fr/articles/bonjour.md",
            DOC.replace("2026-01-02", "2026-03-01").replace("blog", "publications"),
        )
        self.write_file(
            "US/en/articles/hello.md", DOC.replace("2026-01-02", "2026-02-01")
        )
        self.write_file("US/es/articles/borrador.md", DOC.replace("published", "draft"))

    def ids(self, **query):
        return [a.id for a in self.repo.list(ArticleFilter(**query))]

    def test_list_orders_newest_first(self):
        self.assertEqual(
            self.ids(),
            ["CA/fr/bonjour", "US/en/hello", "CA/en/hello", "US/es/borrador"],
        )
        self.assertEqual(
            self.ids(order=ORDER_OLDEST_FIRST)[0], "CA/en/hello"
        )  # ties broken by id

    def test_market_and_locale_isolation(self):
        self.assertEqual(self.ids(market="CA"), ["CA/fr/bonjour", "CA/en/hello"])
        self.assertEqual(self.ids(market="US", locale="en"), ["US/en/hello"])
        self.assertEqual(self.ids(locale="en"), ["US/en/hello", "CA/en/hello"])
        # Same slug in two markets = two different articles.
        ca = self.repo.get(schemas.ArticleKey("CA", "en", "hello"))
        us = self.repo.get(schemas.ArticleKey("US", "en", "hello"))
        self.assertNotEqual(ca.publication_date, us.publication_date)

    def test_category_and_status_filters(self):
        self.assertEqual(self.ids(category="publications"), ["CA/fr/bonjour"])
        self.assertEqual(self.ids(status="draft"), ["US/es/borrador"])
        self.assertNotIn("US/es/borrador", self.ids(published_only=True))

    def test_future_publication_date_is_not_published(self):
        self.repo.create(make_article(slug="later", publication_date=self.future()))
        self.assertIn("CA/en/later", self.ids())
        self.assertNotIn("CA/en/later", self.ids(published_only=True))

    def test_get_and_exists(self):
        key = schemas.ArticleKey("CA", "en", "hello")
        self.assertTrue(self.repo.exists(key))
        self.assertEqual(self.repo.get(key).title, "Hello")
        missing = schemas.ArticleKey("CA", "en", "nope")
        self.assertFalse(self.repo.exists(missing))
        with self.assertRaises(DocumentNotFound):
            self.repo.get(missing)

    def test_unknown_markets_locales_and_stray_files_are_ignored(self):
        self.write_file("MX/es/articles/hola.md", DOC)  # market not configured
        self.write_file("CA/de/articles/hallo.md", DOC)  # locale not enabled
        self.write_file("CA/en/articles/notes.txt", "x")
        self.write_file("CA/en/articles/Bad Name.md", DOC)
        self.write_file("CA/en/articles/nested/deep.md", DOC)
        self.write_file("CA/en/pages/about.md", DOC)
        self.assertEqual(len(self.ids()), 4)

    def test_invalid_files_are_skipped_and_reported(self):
        self.write_file("CA/en/articles/broken.md", "---\ntitle: [x\n---\n")
        self.assertNotIn("CA/en/broken", self.ids())
        self.assertIn("CA/en/broken", self.repo.invalid_documents())
        with self.assertRaises(InvalidDocument):
            self.repo.get(schemas.ArticleKey("CA", "en", "broken"))


class WriteTests(TempContentMixin, SimpleTestCase):
    def path(self, rel):
        return self.root / rel

    def test_create_writes_markdown_file(self):
        stored = self.repo.create(make_article())
        text = self.path("CA/en/articles/hello.md").read_text()
        self.assertEqual(text, schemas.serialize(stored))
        self.assertEqual(stored.version, schemas.parse(stored.key, text).version)
        # Survives a "restart": a brand-new repository instance reads it back.
        fresh = type(self.repo)(self.root, markets=self.repo.markets)
        self.assertEqual(fresh.get(stored.key).title, "Hello")

    def test_duplicate_path_is_rejected(self):
        self.repo.create(make_article())
        with self.assertRaises(DocumentAlreadyExists):
            self.repo.create(make_article(title="Other"))
        # Same slug elsewhere is fine.
        self.repo.create(make_article(market="US"))

    def test_update_with_optimistic_locking(self):
        stored = self.repo.create(make_article())
        updated = self.repo.update(
            stored.key, make_article(title="Changed"), expected_version=stored.version
        )
        self.assertEqual(self.repo.get(stored.key).title, "Changed")
        with self.assertRaises(VersionConflict) as ctx:
            self.repo.update(
                stored.key, make_article(title="Stale"), expected_version=stored.version
            )
        self.assertEqual(ctx.exception.current_version, updated.version)
        self.assertEqual(self.repo.get(stored.key).title, "Changed")

    def test_update_can_move_without_overwriting(self):
        stored = self.repo.create(make_article())
        self.repo.create(make_article(slug="taken"))
        with self.assertRaises(DocumentAlreadyExists):
            self.repo.update(stored.key, make_article(slug="taken"))
        moved = self.repo.update(
            stored.key, make_article(market="US", locale="es", slug="hola")
        )
        self.assertEqual(moved.id, "US/es/hola")
        self.assertFalse(self.path("CA/en/articles/hello.md").exists())
        self.assertTrue(self.path("US/es/articles/hola.md").exists())

    def test_delete(self):
        stored = self.repo.create(make_article())
        with self.assertRaises(VersionConflict):
            self.repo.delete(stored.key, expected_version="0" * 64)
        self.repo.delete(stored.key, expected_version=stored.version)
        self.assertFalse(self.path("CA/en/articles/hello.md").exists())
        with self.assertRaises(DocumentNotFound):
            self.repo.delete(stored.key)

    def test_failed_write_leaves_previous_content(self):
        stored = self.repo.create(make_article())
        before = self.path("CA/en/articles/hello.md").read_bytes()
        real_replace = os.replace

        def crash(*args):
            raise OSError("disk full")

        os.replace = crash
        try:
            with self.assertRaises(OSError):
                self.repo.update(stored.key, make_article(title="Half"))
        finally:
            os.replace = real_replace
        self.assertEqual(self.path("CA/en/articles/hello.md").read_bytes(), before)
        leftovers = [p.name for p in self.path("CA/en/articles").iterdir()]
        self.assertEqual(leftovers, ["hello.md"])

    def test_path_traversal_is_impossible(self):
        for parts in [
            ("CA", "en", "../../../etc/passwd"),
            ("CA", "../..", "x"),
            ("..", "en", "x"),
            ("/tmp", "en", "x"),
            ("CA", "en", "a/b"),
        ]:
            key = schemas.ArticleKey(*parts)
            with self.subTest(parts):
                with self.assertRaises(InvalidDocument):
                    self.repo.get(key)
                with self.assertRaises(InvalidDocument):
                    self.repo.exists(key)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_symlinked_directory_escaping_root_is_refused(self):
        outside = self.root.parent / f"{self.root.name}-outside"
        outside.mkdir()
        self.addCleanup(
            lambda: __import__("shutil").rmtree(outside, ignore_errors=True)
        )
        (self.root / "CA" / "en").mkdir(parents=True)
        os.symlink(outside, self.root / "CA" / "en" / "articles")
        with self.assertRaises(InvalidDocument):
            self.repo.create(make_article())
        self.assertEqual(list(outside.iterdir()), [])

    def test_versioned_operations_are_explicitly_unsupported(self):
        key = self.repo.create(make_article()).key
        for call in (
            lambda: self.repo.history(key),
            lambda: self.repo.diff(key, "a"),
            lambda: self.repo.commit([key], context=None),
        ):
            with self.assertRaises(OperationNotSupported):
                call()
