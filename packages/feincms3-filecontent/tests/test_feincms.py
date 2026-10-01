import os

import pytest
from django.core.exceptions import ValidationError
from django.template import Context
from feincms3.renderer import RegionRenderer

from feincms3_filecontent import services
from feincms3_filecontent.feincms.plugins import FileContentForm, render_filecontent
from feincms3_filecontent.feincms.renderer import loader
from feincms3_filecontent.sync.engine import SyncEngine

from .testapp.models import FileContent, Page


pytestmark = pytest.mark.django_db


@pytest.fixture
def page(content):
    page = Page.objects.create(title="About", slug="about")
    FileContent.objects.create(
        parent=page, region="main", ordering=10, content_path="about.md"
    )
    return page


def render_page(page):
    renderer = RegionRenderer()
    renderer.register(FileContent, render_filecontent)
    regions = renderer.regions_from_item(page)
    return regions.render("main", Context({}))


def test_page_renders_document_from_filesystem(page):
    html = render_page(page)
    assert '<div class="filecontent" data-path="about.md">' in html
    assert "<strong>things</strong>" in html
    # The body is not duplicated into the database.
    assert not any(
        "We sell" in str(v) for v in FileContent.objects.values()[0].values()
    )


def test_rendering_does_not_need_git(page, content, monkeypatch):
    def no_git(*args, **kwargs):
        raise AssertionError("Git must not run during rendering")

    monkeypatch.setattr(services.get_repository(), "run", no_git)
    assert "things" in render_page(page)


def test_changed_file_invalidates_cache(page, content):
    assert "things" in render_page(page)
    target = content / "about.md"
    target.write_text("---\ntitle: About\n---\nNew text\n")
    stat = target.stat()
    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    assert "New text" in render_page(page)


def test_missing_document_renders_empty_or_error(page, content, settings):
    (content / "about.md").unlink()
    loader.clear()
    assert render_page(page).strip() == ""
    settings.FILECONTENT = {**settings.FILECONTENT, "SHOW_ERRORS": True}
    assert "filecontent--error" in render_page(page)


def test_sanitizer_is_applied(page, settings):
    settings.FILECONTENT = {
        **settings.FILECONTENT,
        "SANITIZER": "tests.test_feincms.shout",
    }
    assert "THINGS" in render_page(page)


def shout(html):
    return html.upper()


def test_get_document(page):
    plugin = FileContent.objects.get()
    assert plugin.get_document().title == "About us"


@pytest.mark.parametrize("path", ["../etc/passwd", "missing.md", "README.txt"])
def test_content_path_validation(page, path):
    plugin = FileContent(parent=page, region="main", ordering=20, content_path=path)
    with pytest.raises(ValidationError):
        plugin.full_clean()


def test_form_offers_indexed_documents(page):
    SyncEngine.default().sync()

    class Form(FileContentForm):
        class Meta:
            model = FileContent
            fields = ["content_path"]

    choices = dict(Form().fields["content_path"].widget.choices)
    assert "blog/hello.md" in choices
    assert "Hello world" in choices["blog/hello.md"]
