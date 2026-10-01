import json

from django.contrib.auth.models import Permission, User
from django.test import TestCase

from app.content import schemas

from .base import TempContentMixin, make_article


API = "/api/content/"


class APITests(TempContentMixin, TestCase):
    index = True

    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser("admin", "a@example.com", "pw")
        self.client.force_login(self.admin)
        self.repo.create(make_article())

    def send(self, method, url, data=None, **extra):
        return getattr(self.client, method)(
            url,
            data=json.dumps(data) if data is not None else None,
            content_type="application/json",
            **extra,
        )

    def test_meta(self):
        data = self.client.get(f"{API}meta/").json()
        self.assertEqual(data["source"], "filesystem")
        self.assertEqual(data["markets"]["CA"], ["en", "fr"])
        self.assertNotIn(str(self.root), json.dumps(data))  # no absolute paths

    def test_list_and_filters(self):
        self.repo.create(make_article(market="US", slug="other", status="draft"))
        data = self.client.get(f"{API}articles/").json()
        self.assertEqual(data["count"], 2)
        self.assertNotIn("body", data["results"][0])
        data = self.client.get(
            f"{API}articles/", {"market": "US", "status": "draft"}
        ).json()
        self.assertEqual([a["id"] for a in data["results"]], ["US/en/other"])

    def test_get(self):
        data = self.client.get(f"{API}articles/CA/en/hello/").json()
        self.assertEqual(data["title"], "Hello")
        self.assertEqual(data["body"], "Some **body**.\n")
        self.assertEqual(data["location"], f"{self.root.name}/CA/en/articles/hello.md")
        self.assertEqual(data["public_url"], "/content/ca/en/articles/hello/")
        self.assertEqual(
            self.client.get(f"{API}articles/CA/en/missing/").status_code, 404
        )

    def test_create(self):
        payload = {
            "market": "CA",
            "locale": "fr",
            "slug": "nouveau",
            "title": "Nouveau",
            "status": "draft",
            "category": "blog",
            "publication_date": "2026-05-01T10:00:00Z",
            "body": "Texte",
        }
        response = self.send("post", f"{API}articles/", payload)
        self.assertEqual(response.status_code, 201, response.content)
        self.assertTrue((self.root / "CA/fr/articles/nouveau.md").exists())
        self.assertEqual(self.send("post", f"{API}articles/", payload).status_code, 409)

    def test_create_validation_errors(self):
        response = self.send(
            "post", f"{API}articles/", {"market": "XX", "slug": "../x", "title": ""}
        )
        self.assertEqual(response.status_code, 400)
        self.assertTrue(
            {"market", "slug", "title", "category", "publication_date"}
            <= set(response.json()["errors"])
        )
        self.assertEqual(
            [p.name for p in (self.root / "CA/en/articles").iterdir()], ["hello.md"]
        )

    def test_update_writes_file_and_detects_conflicts(self):
        current = self.client.get(f"{API}articles/CA/en/hello/").json()
        payload = {**current, "title": "Edited", "body": "New body"}
        response = self.send("put", f"{API}articles/CA/en/hello/", payload)
        self.assertEqual(response.status_code, 200, response.content)
        text = (self.root / "CA/en/articles/hello.md").read_text()
        self.assertIn("title: Edited", text)
        self.assertIn("New body", text)
        stale = self.send("put", f"{API}articles/CA/en/hello/", payload)
        self.assertEqual(stale.status_code, 409)
        self.assertIn("current_version", stale.json())

    def test_delete(self):
        version = self.client.get(f"{API}articles/CA/en/hello/").json()["version"]
        bad = self.client.delete(f"{API}articles/CA/en/hello/", HTTP_IF_MATCH="x")
        self.assertEqual(bad.status_code, 409)
        ok = self.client.delete(f"{API}articles/CA/en/hello/", HTTP_IF_MATCH=version)
        self.assertEqual(ok.status_code, 200)
        self.assertFalse((self.root / "CA/en/articles/hello.md").exists())

    def test_authentication_and_permissions(self):
        self.client.logout()
        self.assertEqual(self.client.get(f"{API}articles/").status_code, 401)
        user = User.objects.create_user("editor", password="pw", is_staff=True)
        self.client.force_login(user)
        self.assertEqual(self.client.get(f"{API}articles/").status_code, 403)
        user.user_permissions.add(Permission.objects.get(codename="view_article"))
        user = User.objects.get(pk=user.pk)
        self.client.force_login(user)
        self.assertEqual(self.client.get(f"{API}articles/").status_code, 200)
        self.assertEqual(
            self.send("delete", f"{API}articles/CA/en/hello/").status_code, 403
        )

    def test_csrf_is_enforced(self):
        client = self.client_class(enforce_csrf_checks=True)
        client.force_login(self.admin)
        response = client.post(
            f"{API}articles/", data="{}", content_type="application/json"
        )
        self.assertEqual(response.status_code, 403)

    def test_no_orm_article_rows_involved(self):
        from app.articles.models import Article  # noqa: PLC0415

        self.assertEqual(Article.objects.count(), 0)
        self.assertEqual(self.client.get(f"{API}articles/").json()["count"], 1)


class PublicViewTests(TempContentMixin, TestCase):
    index = True

    def test_published_article_renders_from_markdown(self):
        self.repo.create(make_article(body="# Heading\n\n*emphasis*"))
        response = self.client.get("/content/ca/en/articles/hello/")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('data-source="filesystem"', html)
        self.assertIn("<em>emphasis</em>", html)
        self.assertIn('lang="en"', html)

    def test_list_only_shows_published_for_that_market_and_locale(self):
        self.repo.create(make_article(slug="visible"))
        self.repo.create(make_article(slug="hidden-draft", status="draft"))
        self.repo.create(make_article(slug="future", publication_date=self.future()))
        self.repo.create(make_article(market="US", slug="other-market"))
        html = self.client.get("/content/ca/en/articles/").content.decode()
        self.assertIn("/content/ca/en/articles/visible/", html)
        for slug in ("hidden-draft", "future", "other-market"):
            self.assertNotIn(slug, html)

    def test_drafts_unknown_locations_and_missing_files_404(self):
        self.repo.create(make_article(slug="draft", status="draft"))
        for url in (
            "/content/ca/en/articles/draft/",
            "/content/ca/en/articles/missing/",
            "/content/mx/es/articles/",
            "/content/ca/de/articles/",
        ):
            with self.subTest(url):
                self.assertEqual(self.client.get(url).status_code, 404)

    def test_editor_page_requires_staff_and_is_inside_admin_react(self):
        url = "/admin-react/content/articles/"
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(User.objects.create_superuser("a", "a@e.com", "pw"))
        response = self.client.get(url)
        self.assertContains(response, "Filesystem repository")
        # The SPA itself still answers next to it.
        self.assertEqual(self.client.get("/admin-react/").status_code, 200)


class RenderingTests(TempContentMixin, TestCase):
    index = True

    def test_region_renderer_renders_non_orm_component(self):
        from app.content.rendering import (  # noqa: PLC0415
            MarkdownBlock,
            article_regions,
            renderer,
        )

        article = make_article(body="**bold**")
        self.assertEqual(
            article_regions(article)["main"].strip(), "<p><strong>bold</strong></p>"
        )
        self.assertIn(MarkdownBlock, renderer.plugins())
        self.assertFalse(hasattr(schemas.Article, "objects"))
