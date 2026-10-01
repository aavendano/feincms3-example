import pytest

from feincms3_filecontent import services
from feincms3_filecontent.content.parser import split_front_matter
from feincms3_filecontent.exceptions import DocumentValidationError

from .conftest import HELLO


pytestmark = pytest.mark.usefixtures("content")


def parse(path, text):
    return services.get_registry().parse(path, text)


def test_front_matter_split():
    meta, body = split_front_matter("---\ntitle: X\n---\nBody\n")
    assert meta == {"title": "X"}
    assert body == "Body\n"
    assert split_front_matter("No front matter") == ({}, "No front matter")
    assert split_front_matter("---\n---\nBody") == ({}, "Body")


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("---\ntitle: [unclosed\n---\n", "Invalid YAML"),
        ("---\n- a\n- b\n---\n", "must be a mapping"),
        ("---\ntitle: x\n", "not closed"),
    ],
)
def test_front_matter_errors(text, message):
    with pytest.raises(DocumentValidationError, match=message):
        split_front_matter(text)


def test_document_normalization():
    doc = parse("blog/hello.md", HELLO)
    assert doc.content_type == "text/markdown"
    assert doc.slug == "hello-world"
    assert doc.title == "Hello world"
    assert doc.metadata["date"] == "2026-01-15"  # JSON-safe
    assert doc.metadata["tags"] == ["news", "launch"]
    assert doc.body.strip() == "First post."
    assert len(doc.content_hash) == 64


@pytest.mark.parametrize(
    ("path", "text", "locale", "slug"),
    [
        ("de/about.md", "x", "de", "about"),
        ("about.fr.md", "x", "fr", "about"),
        ("about.md", "---\nlocale: de\n---\n", "de", "about"),
        ("misc/about.md", "x", "", "about"),
    ],
)
def test_locale_detection(path, text, locale, slug):
    doc = parse(path, text)
    assert (doc.locale, doc.slug) == (locale, slug)


def test_title_falls_back_to_heading_then_slug():
    assert parse("x.md", "# Heading\n\ntext").title == "Heading"
    assert parse("my-page.md", "text").title == "My page"


def test_markdown_rendering():
    doc = parse("x.md", "---\ntitle: X\n---\n# H\n\n*em*\n")
    html = services.get_registry().render(doc)
    assert '<h1 id="h">H</h1>' in html
    assert "<em>em</em>" in html


def test_validation_collects_all_errors():
    validator = services.get_validator()
    with pytest.raises(DocumentValidationError) as info:
        validator.validate(
            "bad.md", "---\nslug: 'no spaces allowed'\nlocale: xx\n---\n"
        )
    errors = " ".join(info.value.errors)
    assert "'title' is required" in errors
    assert "Slug" in errors
    assert "Unknown locale" in errors


@pytest.mark.parametrize(
    "path", ["../escape.md", ".git/x.md", ".hidden.md", "image.png", "dir/.secret.md"]
)
def test_validation_rejects_paths(path):
    with pytest.raises(DocumentValidationError):
        services.get_validator().validate(path, "---\ntitle: x\n---\n")


def test_validation_size_limit(settings, content):
    settings.FILECONTENT = {**settings.FILECONTENT, "MAX_DOCUMENT_SIZE": 10}
    with pytest.raises(DocumentValidationError, match="limit"):
        services.get_validator().validate("x.md", "---\ntitle: long enough\n---\n")
