import datetime as dt

from django.test import SimpleTestCase

from app.content import schemas
from app.content.exceptions import InvalidDocument

from .base import DOC, make_article


KEY = schemas.ArticleKey("CA", "en", "hello")


class ParseTests(SimpleTestCase):
    def test_parse_front_matter_and_markdown_body(self):
        article = schemas.parse(KEY, DOC)
        self.assertEqual(article.title, "Hello")
        self.assertEqual(article.status, "published")
        self.assertEqual(article.category, "blog")
        self.assertEqual(
            article.publication_date,
            dt.datetime(2026, 1, 2, 3, 4, 5, tzinfo=dt.timezone.utc),
        )
        self.assertEqual(article.body, "Some **body**.\n")
        # Derived from the path, not the file.
        self.assertEqual(
            (article.market, article.locale, article.slug), ("CA", "en", "hello")
        )
        self.assertEqual(article.id, "CA/en/hello")
        self.assertEqual(len(article.version), 64)

    def test_yaml_dates_and_naive_datetimes_become_utc(self):
        for value in ("2026-01-02", "2026-01-02T03:04:05", "2026-01-02T05:04:05+02:00"):
            text = DOC.replace("'2026-01-02T03:04:05Z'", value)
            moment = schemas.parse(KEY, text).publication_date
            self.assertEqual(moment.tzinfo, dt.timezone.utc, value)

    def test_slug_in_front_matter_must_match_file_name(self):
        schemas.parse(KEY, DOC.replace("title: Hello", "title: Hello\nslug: hello"))
        with self.assertRaises(InvalidDocument) as ctx:
            schemas.parse(KEY, DOC.replace("title: Hello", "title: Hello\nslug: other"))
        self.assertIn("slug", ctx.exception.errors)

    def test_location_is_never_read_from_front_matter(self):
        with self.assertRaises(InvalidDocument) as ctx:
            schemas.parse(KEY, DOC.replace("title: Hello", "title: Hello\nmarket: US"))
        self.assertIn("Unknown front matter keys: market", str(ctx.exception))

    def test_malformed_documents(self):
        cases = {
            "no front matter": "Just text",
            "unclosed": "---\ntitle: x\n",
            "bad yaml": "---\ntitle: [x\n---\n",
            "not a mapping": "---\n- a\n---\n",
        }
        for name, text in cases.items():
            with self.subTest(name), self.assertRaises(InvalidDocument):
                schemas.parse(KEY, text)

    def test_invalid_metadata_reports_every_field(self):
        text = "---\ntitle: ''\nstatus: live\npublication_date: soon\ncategory: news\n---\n"
        with self.assertRaises(InvalidDocument) as ctx:
            schemas.parse(KEY, text)
        self.assertEqual(
            set(ctx.exception.errors),
            {"title", "status", "publication_date", "category"},
        )


class SerializeTests(SimpleTestCase):
    def test_round_trip(self):
        article = make_article(body="Line 1\n\nLine 2")
        text = schemas.serialize(article)
        self.assertTrue(text.startswith("---\ntitle: Hello\nstatus: published\n"))
        self.assertIn("publication_date: '2026-01-02T03:04:05Z'", text)
        self.assertNotIn("market", text)
        self.assertNotIn("slug", text)
        parsed = schemas.parse(article.key, text)
        self.assertEqual(
            (
                parsed.title,
                parsed.status,
                parsed.publication_date,
                parsed.category,
                parsed.body,
            ),
            (
                article.title,
                article.status,
                article.publication_date,
                article.category,
                "Line 1\n\nLine 2\n",
            ),
        )

    def test_unicode_and_yaml_special_characters(self):
        article = make_article(title="Ça: «quotes» # and --- dashes")
        self.assertEqual(
            schemas.parse(article.key, schemas.serialize(article)).title, article.title
        )


class KeyTests(SimpleTestCase):
    def test_valid_and_invalid_keys(self):
        markets = {"CA": ["en"]}
        schemas.ArticleKey("CA", "en", "a-b-1").validate(markets=markets)
        bad = [
            ("ca", "en", "x"),
            ("CA", "EN", "x"),
            ("CA", "en", "Has Spaces"),
            ("CA", "en", "../etc"),
            ("CA", "en", ""),
            ("US", "en", "x"),  # market not enabled
            ("CA", "fr", "x"),  # locale not enabled for market
        ]
        for parts in bad:
            with self.subTest(parts), self.assertRaises(InvalidDocument):
                schemas.ArticleKey(*parts).validate(markets=markets)

    def test_published_vs_draft(self):
        now = dt.datetime(2026, 6, 1, tzinfo=dt.timezone.utc)
        self.assertTrue(make_article().is_published(now))
        self.assertFalse(make_article(status="draft").is_published(now))
        self.assertFalse(
            make_article(publication_date="2027-01-01T00:00:00Z").is_published(now)
        )
