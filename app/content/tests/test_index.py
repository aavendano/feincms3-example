import os
from io import StringIO
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase

from app.content import schemas
from app.content.filesystem import FilesystemArticleRepository
from app.content.git import GitArticleRepository
from app.content.index import ArticleSummary, IndexedArticleRepository
from app.content.models import ArticleIndex, IndexState
from app.content.repository import ORDER_OLDEST_FIRST, ArticleFilter

from .base import DOC, MARKETS, TempContentMixin, make_article
from .test_git import ADA, GitContentMixin, git


def ids(articles):
    return [a.id for a in articles]


class FilesystemIndexTests(TempContentMixin, TestCase):
    index = True

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
        self.raw = FilesystemArticleRepository(self.root, markets=MARKETS)

    def touch(self, rel, text):
        """Write a file and make sure its mtime changes (coarse clocks)."""
        path = self.write_file(rel, text)
        st = path.stat()
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))

    def test_factory_wraps_backend(self):
        self.assertIsInstance(self.repo, IndexedArticleRepository)
        self.assertIn("index", self.repo.capabilities)

    def test_first_listing_builds_the_index(self):
        self.assertFalse(IndexState.objects.exists())
        articles = self.repo.list()
        self.assertEqual(ArticleIndex.objects.count(), 4)
        self.assertEqual(IndexState.objects.get().last_mode, "full")
        self.assertIsInstance(articles[0], ArticleSummary)
        self.assertFalse(hasattr(articles[0], "body"))

    def test_index_answers_like_the_files(self):
        queries = [
            ArticleFilter(),
            ArticleFilter(order=ORDER_OLDEST_FIRST),
            ArticleFilter(market="CA"),
            ArticleFilter(market="US", locale="en"),
            ArticleFilter(locale="en"),
            ArticleFilter(category="publications"),
            ArticleFilter(status="draft"),
            ArticleFilter(published_only=True),
            ArticleFilter(limit=2, offset=1),
        ]
        for query in queries:
            with self.subTest(query):
                self.assertEqual(ids(self.repo.list(query)), ids(self.raw.list(query)))
                self.assertEqual(self.repo.count(query), self.raw.count(query))

    def test_listing_reads_no_files(self):
        self.repo.list()
        with (
            mock.patch.object(
                self.repo.inner, "get", side_effect=AssertionError("read")
            ),
            self.assertNumQueries(2),
        ):  # index state + rows
            self.assertEqual(len(self.repo.list(ArticleFilter(market="CA"))), 2)

    def test_writes_go_through_to_the_index(self):
        self.repo.list()
        self.repo.create(make_article(slug="new", title="New"))
        self.assertEqual(ArticleIndex.objects.get(slug="new").title, "New")
        current = self.repo.get(schemas.ArticleKey("CA", "en", "new"))
        self.repo.update(
            current.key, make_article(market="US", locale="es", slug="nuevo")
        )
        self.assertFalse(ArticleIndex.objects.filter(slug="new").exists())
        self.assertTrue(ArticleIndex.objects.filter(market="US", slug="nuevo").exists())
        self.repo.delete(schemas.ArticleKey("US", "es", "nuevo"))
        self.assertFalse(ArticleIndex.objects.filter(slug="nuevo").exists())
        # Nothing left for a sync to do.
        self.assertEqual(self.repo.indexer.sync().mode, "noop")

    def test_out_of_band_changes_appear_after_sync(self):
        self.repo.list()
        self.touch(
            "CA/en/articles/hello.md", DOC.replace("title: Hello", "title: Edited")
        )
        self.write_file("CA/en/articles/added.md", DOC)
        (self.root / "US/es/articles/borrador.md").unlink()
        self.assertEqual(
            ArticleIndex.objects.get(market="CA", slug="hello").title, "Hello"
        )
        result = self.repo.indexer.sync()
        self.assertEqual(
            (result.mode, result.upserted, result.deleted), ("incremental", 2, 1)
        )
        self.assertEqual(
            ArticleIndex.objects.get(market="CA", slug="hello").title, "Edited"
        )
        self.assertIn("CA/en/added", ids(self.repo.list()))
        self.assertNotIn("US/es/borrador", ids(self.repo.list()))

    def test_invalid_files_are_indexed_but_never_listed(self):
        self.write_file("CA/en/articles/broken.md", "---\ntitle: [x\n---\n")
        self.assertNotIn("CA/en/broken", ids(self.repo.list()))
        self.assertIn("CA/en/broken", self.repo.invalid_documents())
        self.assertEqual(self.repo.indexer.status()["invalid"], 1)

    def test_index_is_disposable(self):
        before = ids(self.repo.list())
        ArticleIndex.objects.all().delete()
        IndexState.objects.all().delete()
        self.assertEqual(ids(self.repo.list()), before)

    def test_a_different_root_rebuilds(self):
        self.repo.list()
        IndexState.objects.update(root="/somewhere/else")
        self.assertEqual(self.repo.indexer.sync().mode, "full")

    def test_management_command(self):
        out = StringIO()
        call_command("content_index", stdout=out)
        self.assertIn("full: 4 upserted", out.getvalue())
        call_command("content_index", stdout=out)
        self.assertIn("noop", out.getvalue())
        call_command("content_index", "--rebuild", stdout=out)
        call_command("content_index", "--status", stdout=out)
        self.assertIn("rows: 4", out.getvalue())

    def test_api_pagination_counts_everything(self):
        self.client.force_login(User.objects.create_superuser("a", "a@e.com", "pw"))
        data = self.client.get(
            "/api/content/articles/", {"limit": 2, "offset": 1}
        ).json()
        self.assertEqual((data["count"], len(data["results"])), (4, 2))
        self.assertEqual(
            self.client.get("/api/content/articles/", {"limit": "x"}).status_code, 400
        )
        status = self.client.get("/api/content/repository/").json()
        self.assertEqual(status["index"]["rows"], 4)


class GitIndexTests(GitContentMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.repo = IndexedArticleRepository(
            GitArticleRepository(self.root, markets=MARKETS)
        )

    def push_other(self, files, message="Remote change", remove=()):
        other = self.tmp / "other"
        if not other.exists():
            git(self.tmp, "clone", "-q", str(self.remote), str(other))
        else:
            git(other, "pull", "-q")
        for rel, text in files.items():
            (other / rel).parent.mkdir(parents=True, exist_ok=True)
            (other / rel).write_text(text)
        for rel in remove:
            git(other, "rm", "-q", rel)
        git(other, "add", "-A")
        git(other, "commit", "-qm", message)
        git(other, "push", "-q", "origin", "main")
        return other

    def test_incremental_sync_follows_git_diffs(self):
        self.repo.list()
        state = IndexState.objects.get()
        self.assertEqual(state.last_indexed_sha, self.repo.git.current_sha())
        self.assertEqual(self.repo.status()["index"]["state"], "current")

        other = self.push_other(
            {
                "US/en/articles/remote.md": schemas.serialize(
                    make_article(market="US", slug="remote")
                )
            }
        )
        git(other, "mv", "CA/en/articles/hello.md", "CA/en/articles/renamed.md")
        git(other, "commit", "-qm", "Rename")
        git(other, "push", "-q", "origin", "main")

        result = self.repo.sync()["index"]
        self.assertEqual(result["mode"], "incremental")
        self.assertEqual((result["upserted"], result["deleted"]), (2, 1))
        self.assertEqual(
            sorted(ids(self.repo.list())), ["CA/en/renamed", "US/en/remote"]
        )
        self.assertEqual(self.repo.status()["index"]["state"], "current")

    def test_write_through_keeps_the_index_current(self):
        self.repo.list()
        self.repo.create(make_article(slug="new"), context=ADA)
        self.assertEqual(self.repo.status()["index"]["state"], "current")
        self.assertEqual(self.repo.indexer.sync().mode, "noop")
        self.assertIn("CA/en/new", ids(self.repo.list()))
        self.repo.restore(
            schemas.ArticleKey("CA", "en", "new"),
            self.repo.history(schemas.ArticleKey("CA", "en", "new"))[0]["version"],
        )

    def test_rewritten_history_triggers_full_rebuild(self):
        self.repo.list()
        IndexState.objects.update(last_indexed_sha="0" * 40)
        result = self.repo.indexer.sync()
        self.assertEqual(result.mode, "full")
        self.assertIn("unknown", result.reason)
