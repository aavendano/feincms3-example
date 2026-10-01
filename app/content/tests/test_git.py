import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase, override_settings
from feincms3_filecontent.exceptions import DirtyWorkingTree, DivergedError

from app.content import get_article_repository, schemas
from app.content.exceptions import DocumentNotFound, VersionConflict
from app.content.git import GitArticleRepository
from app.content.repository import ChangeContext

from .base import MARKETS, make_article


ADA = ChangeContext(author_name="Ada Lovelace", author_email="ada@example.com")


def git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()


class GitContentMixin:
    """A content working tree cloned from a local bare "remote" (no network)."""

    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp(prefix="content-git-tests-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        config = self.tmp / "gitconfig"
        config.write_text("[init]\n\tdefaultBranch = main\n")
        env = {
            "GIT_CONFIG_GLOBAL": str(config),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "Seed",
            "GIT_AUTHOR_EMAIL": "seed@example.com",
            "GIT_COMMITTER_NAME": "Seed",
            "GIT_COMMITTER_EMAIL": "seed@example.com",
        }
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.remote = self.tmp / "remote.git"
        git(self.tmp, "init", "-q", "--bare", "-b", "main", str(self.remote))
        seed = self.tmp / "seed"
        git(self.tmp, "clone", "-q", str(self.remote), str(seed))
        (seed / "CA/en/articles").mkdir(parents=True)
        (seed / "CA/en/articles/hello.md").write_text(schemas.serialize(make_article()))
        git(seed, "add", "-A")
        git(seed, "commit", "-qm", "Seed")
        git(seed, "push", "-q", "origin", "main")
        self.root = self.tmp / "content"
        git(self.tmp, "clone", "-q", str(self.remote), str(self.root))
        self.repo = GitArticleRepository(self.root, markets=MARKETS)

    def remote_log(self, fmt="%s"):
        return git(self.remote, "log", f"--format={fmt}", "main").splitlines()

    def other_clone(self):
        other = self.tmp / "other"
        git(self.tmp, "clone", "-q", str(self.remote), str(other))
        return other


class GitRepositoryTests(GitContentMixin, SimpleTestCase):
    def test_each_write_is_one_pushed_commit_by_the_editor(self):
        self.repo.create(make_article(slug="new", title="New"), context=ADA)
        info = self.repo.last_commit()
        self.assertTrue(info.pushed)
        self.assertEqual(info.sha, git(self.remote, "rev-parse", "main"))
        self.assertEqual(
            git(self.remote, "log", "-1", "--format=%an <%ae>|%cn|%s", "main"),
            "Ada Lovelace <ada@example.com>|feincms3 content|Add article CA/en/new",
        )
        current = self.repo.get(schemas.ArticleKey("CA", "en", "new"))
        self.repo.update(
            current.key,
            make_article(slug="new", title="Newer"),
            expected_version=current.version,
            context=ADA,
        )
        self.repo.delete(current.key, context=ADA)
        self.assertEqual(
            self.remote_log()[:3],
            [
                "Delete article CA/en/new",
                "Update article CA/en/new",
                "Add article CA/en/new",
            ],
        )
        self.assertEqual(self.repo.status()["state"], "clean")

    def test_move_is_a_single_rename_commit(self):
        key = schemas.ArticleKey("CA", "en", "hello")
        self.repo.update(key, make_article(market="US", locale="es", slug="hola"))
        self.assertEqual(self.remote_log()[0], "Move article CA/en/hello to US/es/hola")
        changes = git(self.root, "show", "--name-status", "-M", "--format=", "HEAD")
        self.assertTrue(changes.startswith("R100"))

    def test_custom_commit_message(self):
        context = ChangeContext("Ada", "ada@example.com", "Fix typo in hello")
        self.repo.update(
            schemas.ArticleKey("CA", "en", "hello"),
            make_article(title="Hello!"),
            context=context,
        )
        self.assertEqual(self.remote_log()[0], "Fix typo in hello")

    def test_failed_commit_restores_files_and_index(self):
        before = (self.root / "CA/en/articles/hello.md").read_bytes()
        with mock.patch.object(
            self.repo.git, "commit", side_effect=RuntimeError("boom")
        ):
            with self.assertRaises(RuntimeError):
                self.repo.update(
                    schemas.ArticleKey("CA", "en", "hello"), make_article(title="X")
                )
            with self.assertRaises(RuntimeError):
                self.repo.create(make_article(slug="ghost"))
        self.assertEqual((self.root / "CA/en/articles/hello.md").read_bytes(), before)
        self.assertFalse((self.root / "CA/en/articles/ghost.md").exists())
        self.assertEqual(self.repo.status()["state"], "clean")

    def test_uncommitted_hand_edit_is_never_overwritten(self):
        path = self.root / "CA/en/articles/hello.md"
        path.write_text(path.read_text() + "\nHand edit\n")
        with self.assertRaises(DirtyWorkingTree):
            self.repo.update(
                schemas.ArticleKey("CA", "en", "hello"), make_article(title="X")
            )
        self.assertIn("Hand edit", path.read_text())
        # ...but it can be committed explicitly.
        self.repo.commit([schemas.ArticleKey("CA", "en", "hello")], context=ADA)
        self.assertEqual(self.remote_log()[0], "Update articles")

    def test_rejected_push_keeps_the_commit_and_reports_it(self):
        other = self.other_clone()
        (other / "CA/en/articles/remote.md").write_text(
            schemas.serialize(make_article(slug="remote"))
        )
        git(other, "add", "-A")
        git(other, "commit", "-qm", "Remote change")
        git(other, "push", "-q", "origin", "main")

        self.repo.create(make_article(slug="local"), context=ADA)
        info = self.repo.last_commit()
        self.assertFalse(info.pushed)
        self.assertIn("rejected", info.push_error)
        self.assertTrue((self.root / "CA/en/articles/local.md").exists())

        # Different files on each side: sync refuses to merge silently.
        with self.assertRaises(DivergedError):
            self.repo.sync()
        self.assertEqual(self.repo.status()["state"], "diverged")

    def test_sync_fast_forwards_and_pushes(self):
        other = self.other_clone()
        (other / "CA/en/articles/remote.md").write_text(
            schemas.serialize(make_article(slug="remote"))
        )
        git(other, "add", "-A")
        git(other, "commit", "-qm", "Remote change")
        git(other, "push", "-q", "origin", "main")
        status = self.repo.sync()
        self.assertEqual(status["state"], "clean")
        self.assertTrue(self.repo.exists(schemas.ArticleKey("CA", "en", "remote")))

        repo = GitArticleRepository(self.root, markets=MARKETS, auto_push=False)
        repo.create(make_article(slug="later"))
        self.assertEqual(repo.status()["ahead"], 1)
        self.assertEqual(repo.sync()["ahead"], 0)
        self.assertEqual(self.remote_log()[0], "Add article CA/en/later")

    def test_history_diff_and_non_destructive_restore(self):
        key = schemas.ArticleKey("CA", "en", "hello")
        self.repo.update(key, make_article(title="Second"), context=ADA)
        self.repo.update(key, make_article(title="Third"), context=ADA)
        history = self.repo.history(key)
        self.assertEqual(
            [h["message"] for h in history],
            ["Update article CA/en/hello", "Update article CA/en/hello", "Seed"],
        )
        first = history[-1]["version"]
        self.assertIn("+title: Third", self.repo.diff(key, history[0]["version"]))
        self.assertIn(
            "-title: Hello", self.repo.diff(key, first, history[1]["version"])
        )
        self.assertEqual(self.repo.version(key, first).title, "Hello")

        current = self.repo.get(key)
        with self.assertRaises(VersionConflict):
            self.repo.restore(key, first, expected_version="stale", context=ADA)
        restored = self.repo.restore(
            key, first[:8], expected_version=current.version, context=ADA
        )
        self.assertEqual(restored.title, "Hello")
        self.assertEqual(len(self.repo.history(key)), 4)  # nothing rewritten
        self.assertEqual(
            self.remote_log()[0], f"Restore article CA/en/hello to {first[:10]}"
        )

    def test_restore_recreates_a_deleted_article(self):
        key = schemas.ArticleKey("CA", "en", "hello")
        seed = self.repo.history(key)[0]["version"]
        self.repo.delete(key)
        self.repo.restore(key, seed)
        self.assertEqual(self.repo.get(key).title, "Hello")
        with self.assertRaises(DocumentNotFound):
            self.repo.restore(schemas.ArticleKey("CA", "en", "never"), seed)
        with self.assertRaises(DocumentNotFound):
            self.repo.restore(key, "0" * 40)

    def test_reads_never_run_git(self):
        with mock.patch.object(
            self.repo.git, "run", side_effect=AssertionError("git!")
        ):
            self.assertEqual(len(self.repo.list()), 1)
            self.assertEqual(
                self.repo.get(schemas.ArticleKey("CA", "en", "hello")).title, "Hello"
            )

    def test_content_dir_inside_another_repository_is_refused(self):
        nested = self.root / "nested"
        nested.mkdir()
        repo = GitArticleRepository(nested, markets=MARKETS)
        self.assertFalse(repo.status()["ok"])
        with self.assertRaises(Exception) as ctx:
            repo.create(make_article())
        self.assertIn("not the root of a Git working tree", str(ctx.exception))


class GitAPITests(GitContentMixin, TestCase):
    def setUp(self):
        super().setUp()
        override = override_settings(
            CONTENT_REPOSITORY={
                "BACKEND": "git",
                "ROOT": str(self.root),
                "MARKETS": MARKETS,
            }
        )
        override.enable()
        self.addCleanup(override.disable)
        self.client.force_login(
            User.objects.create_superuser(
                "ada", "ada@example.com", "pw", first_name="Ada", last_name="L"
            )
        )
        self.url = "/api/content/articles/CA/en/hello/"

    def test_factory_builds_git_backend(self):
        self.assertIsInstance(get_article_repository().inner, GitArticleRepository)
        meta = self.client.get("/api/content/meta/").json()
        self.assertEqual(meta["source"], "git")
        self.assertIn("history", meta["capabilities"])

    def test_write_returns_commit_and_history_restore_work(self):
        current = self.client.get(self.url).json()
        response = self.client.put(
            self.url,
            {**current, "title": "Edited"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["commit"]["pushed"])
        self.assertEqual(git(self.remote, "log", "-1", "--format=%an", "main"), "Ada L")

        history = self.client.get(self.url + "history/").json()["entries"]
        self.assertEqual(len(history), 2)
        diff = self.client.get(
            self.url + "diff/", {"version": history[0]["version"]}
        ).json()["diff"]
        self.assertIn("+title: Edited", diff)

        response = self.client.post(
            self.url + "restore/",
            {"version": history[1]["version"]},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["title"], "Hello")
        self.assertEqual(
            len(self.client.get(self.url + "history/").json()["entries"]), 3
        )

    def test_repository_status_and_conflicts(self):
        status = self.client.get("/api/content/repository/").json()
        self.assertEqual((status["backend"], status["state"]), ("git", "clean"))
        path = self.root / "CA/en/articles/hello.md"
        path.write_text(path.read_text() + "hand edit\n")
        current = self.client.get(self.url).json()
        response = self.client.put(
            self.url, {**current, "title": "X"}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["paths"], ["CA/en/articles/hello.md"])
        self.assertEqual(
            self.client.post("/api/content/repository/sync/").status_code, 200
        )


class FilesystemBackendTests(TestCase):
    def test_versioned_endpoints_answer_501(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        with override_settings(CONTENT_REPOSITORY={"ROOT": root, "MARKETS": MARKETS}):
            get_article_repository().create(make_article())
            self.client.force_login(User.objects.create_superuser("a", "a@e.com", "pw"))
            url = "/api/content/articles/CA/en/hello/"
            self.assertEqual(self.client.get(url + "history/").status_code, 501)
            self.assertEqual(
                self.client.post(
                    url + "restore/", {}, content_type="application/json"
                ).status_code,
                501,
            )
            # Without Git, "sync" means reindex.
            response = self.client.post("/api/content/repository/sync/")
            self.assertEqual(response.status_code, 200)
            self.assertIn("index", response.json())
            self.assertEqual(
                self.client.get("/api/content/repository/").json()["backend"],
                "filesystem",
            )
