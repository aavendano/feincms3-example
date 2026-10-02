import json
import shutil
from io import StringIO

from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

from app.content import get_article_repository
from app.content.models import ArticleIndex

from .base import MARKETS
from .test_git import GitContentMixin, git


def run(*args):
    out, err = StringIO(), StringIO()
    call_command(*args, stdout=out, stderr=err)
    return out.getvalue() + err.getvalue()


class CloneAndStatusTests(GitContentMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.target = self.tmp / "fresh"
        override = override_settings(
            CONTENT_REPOSITORY={
                "BACKEND": "git",
                "ROOT": str(self.target),
                "MARKETS": MARKETS,
                "GIT": {"REMOTE_URL": str(self.remote)},
            }
        )
        override.enable()
        self.addCleanup(override.disable)

    def status(self, *args):
        return json.loads(run("content_status", "--json", *args))

    def test_status_before_first_clone(self):
        data = self.status()
        self.assertFalse(data["cloned"])
        self.assertFalse(data["healthy"])
        self.assertIn("content_clone", data["problems"][0])
        with self.assertRaises(CommandError):
            run("content_status", "--check")

    def test_first_run_clone_builds_index_and_is_idempotent(self):
        output = run("content_clone")
        self.assertIn("Cloned", output)
        self.assertIn("Index: full (1 upserted", output)
        self.assertTrue((self.target / "CA/en/articles/hello.md").exists())
        self.assertEqual(ArticleIndex.objects.count(), 1)

        data = self.status()
        self.assertEqual(
            (data["state"], data["branch"], data["ahead"]), ("clean", "main", 0)
        )
        self.assertEqual(data["index"]["state"], "current")
        self.assertTrue(data["healthy"])
        run("content_status", "--check")  # exit 0

        self.assertIn("already a working tree", run("content_clone"))

    def test_status_reports_dirty_files_and_unpushed_commits(self):
        run("content_clone")
        (self.target / "CA/en/articles/hello.md").write_text("hand edit\n")
        data = self.status()
        self.assertEqual(data["state"], "dirty")
        self.assertEqual(data["modified"], ["CA/en/articles/hello.md"])
        self.assertFalse(data["healthy"])
        text = run("content_status")
        self.assertIn("modified: CA/en/articles/hello.md", text)
        self.assertIn("Needs attention", text)

    def test_fetch_reveals_remote_commits(self):
        run("content_clone")
        other = self.other_clone()
        (other / "CA/en/articles/new.md").write_text(
            (other / "CA/en/articles/hello.md").read_text()
        )
        git(other, "add", "-A")
        git(other, "commit", "-qm", "Remote")
        git(other, "push", "-q", "origin", "main")
        self.assertEqual(self.status()["behind"], 0)
        self.assertEqual(self.status("--fetch")["behind"], 1)

    def test_refuses_to_clone_over_existing_files(self):
        self.target.mkdir()
        (self.target / "keep.txt").write_text("precious")
        with self.assertRaisesMessage(CommandError, "refusing to clone"):
            run("content_clone")
        self.assertEqual((self.target / "keep.txt").read_text(), "precious")

    def test_refuses_a_different_remote(self):
        run("content_clone")
        with self.assertRaisesMessage(CommandError, "is a clone of"):
            run("content_clone", "--remote", str(self.tmp / "elsewhere.git"))

    def test_missing_remote_and_credentials(self):
        with (
            override_settings(
                CONTENT_REPOSITORY={
                    "BACKEND": "git",
                    "ROOT": str(self.target),
                    "MARKETS": MARKETS,
                }
            ),
            self.assertRaisesMessage(CommandError, "No remote configured"),
        ):
            run("content_clone")
        url = "https://user:s3cret@example.com/content.git"
        with override_settings(
            CONTENT_REPOSITORY={
                "BACKEND": "git",
                "ROOT": str(self.target),
                "MARKETS": MARKETS,
                "GIT": {"REMOTE_URL": url},
            }
        ):
            data = self.status()
            self.assertNotIn("s3cret", json.dumps(data))
            self.assertIn("credentials", data["warnings"][0])

    def test_filesystem_backend(self):
        shutil.copytree(self.root, self.target, ignore=shutil.ignore_patterns(".git"))
        with override_settings(
            CONTENT_REPOSITORY={"ROOT": str(self.target), "MARKETS": MARKETS}
        ):
            with self.assertRaisesMessage(CommandError, "nothing to clone"):
                run("content_clone")
            get_article_repository().list()
            data = self.status()
            self.assertEqual(data["backend"], "filesystem")
            self.assertTrue(data["healthy"])
