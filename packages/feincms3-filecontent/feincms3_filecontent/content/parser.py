"""
Document parsers.

A parser turns raw file text into a :class:`Document` and a document into
HTML. The MVP ships Markdown + YAML front matter; other formats register a
parser class for their file extensions through ``FILECONTENT["PARSERS"]``.
"""

import datetime as dt
import re
from pathlib import PurePosixPath

import markdown
import yaml
from django.conf import settings as django_settings
from django.utils.html import escape, linebreaks
from django.utils.module_loading import import_string

from ..exceptions import DocumentValidationError, UnsupportedDocumentType
from .documents import Document, content_hash


FRONT_MATTER_RE = re.compile(
    r"\A---[ \t]*\r?\n(?P<meta>.*?)(?:\r?\n)?^(?:---|\.\.\.)[ \t]*(?:\r?\n|\Z)",
    re.DOTALL | re.MULTILINE,
)
MODIFIED_KEYS = ("modified_at", "updated_at", "updated", "modified")
LOCALE_KEYS = ("locale", "language", "lang")


def split_front_matter(text):
    """
    Split ``text`` into ``(metadata, body)``.

    Raises ``DocumentValidationError`` for malformed YAML or non-mapping front
    matter. Text without front matter yields an empty mapping.
    """
    text = text.removeprefix("﻿")
    match = FRONT_MATTER_RE.match(text)
    if not match:
        if text.startswith(("---\n", "---\r\n")):
            raise DocumentValidationError(["Front matter is not closed with '---'."])
        return {}, text
    try:
        metadata = yaml.safe_load(match.group("meta")) or {}
    except yaml.YAMLError as exc:
        raise DocumentValidationError([f"Invalid YAML front matter: {exc}"]) from exc
    if not isinstance(metadata, dict):
        raise DocumentValidationError(["Front matter must be a mapping."])
    return {str(key): value for key, value in metadata.items()}, text[match.end() :]


def jsonable(value):
    """Make YAML values JSON-serializable (dates become ISO strings)."""
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(v) for v in value]
    if isinstance(value, (dt.date, dt.datetime, dt.time)):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _as_datetime(value):
    if isinstance(value, dt.datetime):
        moment = value
    elif isinstance(value, dt.date):
        moment = dt.datetime.combine(value, dt.time.min)
    elif isinstance(value, str):
        try:
            moment = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    return moment


def known_locales():
    return {code.lower() for code, _name in getattr(django_settings, "LANGUAGES", ())}


class DocumentParser:
    content_type = "text/plain"

    def __init__(self, conf=None):
        self.conf = conf

    def parse(self, path, text, *, modified_at=None):
        metadata, body = self.split(text)
        locale, slug = self.locale_and_slug(path, metadata)
        modified = None
        for key in MODIFIED_KEYS:
            if key in metadata:
                modified = _as_datetime(metadata[key])
                if modified:
                    break
        return Document(
            path=path,
            content_type=self.content_type,
            locale=locale,
            slug=slug,
            title=self.title(metadata, body, slug),
            metadata=jsonable(metadata),
            body=body,
            content_hash=content_hash(text),
            modified_at=modified or modified_at,
        )

    def split(self, text):
        return split_front_matter(text)

    def locale_and_slug(self, path, metadata):
        pure = PurePosixPath(path)
        locales = known_locales()
        name_parts = pure.name.split(".")
        stem = name_parts[0]

        locale = ""
        for key in LOCALE_KEYS:
            if metadata.get(key):
                locale = str(metadata[key])
                break
        # "about.fr.md" -> locale suffix
        if not locale and len(name_parts) >= 3 and name_parts[-2].lower() in locales:
            locale = name_parts[-2]
        # "fr/about.md" -> locale directory
        if not locale and len(pure.parts) > 1 and pure.parts[0].lower() in locales:
            locale = pure.parts[0]

        slug = str(metadata.get("slug") or stem)
        return locale, slug

    def title(self, metadata, body, slug):
        if metadata.get("title"):
            return str(metadata["title"])
        return slug.replace("-", " ").replace("_", " ").strip().capitalize()

    def render(self, document):
        return linebreaks(escape(document.body))

    def check(self, document):
        """Parser-specific validation; return a list of error messages."""
        return []


class MarkdownParser(DocumentParser):
    content_type = "text/markdown"
    HEADING_RE = re.compile(r"^#\s+(?P<title>.+?)\s*#*\s*$", re.MULTILINE)

    def title(self, metadata, body, slug):
        if metadata.get("title"):
            return str(metadata["title"])
        match = self.HEADING_RE.search(body)
        if match:
            return match.group("title")
        return super().title(metadata, body, slug)

    def _markdown(self):
        extensions = self.conf.markdown_extensions if self.conf else ["extra"]
        configs = self.conf.markdown_extension_configs if self.conf else {}
        return markdown.Markdown(extensions=extensions, extension_configs=configs)

    def render(self, document):
        return self._markdown().convert(document.body)

    def check(self, document):
        try:
            self.render(document)
        except Exception as exc:  # noqa: BLE001 - surface any renderer failure
            return [f"Markdown rendering failed: {exc}"]
        return []


class ParserRegistry:
    def __init__(self, parsers, conf=None):
        self._by_suffix = {}
        for suffix, parser in parsers.items():
            cls = import_string(parser) if isinstance(parser, str) else parser
            self._by_suffix[suffix.lower()] = cls(conf)

    @property
    def suffixes(self):
        return tuple(self._by_suffix)

    def supports(self, path):
        return PurePosixPath(path).suffix.lower() in self._by_suffix

    def for_path(self, path):
        try:
            return self._by_suffix[PurePosixPath(path).suffix.lower()]
        except KeyError:
            raise UnsupportedDocumentType(
                f"No parser registered for {path!r}"
            ) from None

    def parse(self, path, text, **kwargs):
        return self.for_path(path).parse(path, text, **kwargs)

    def render(self, document):
        return self.for_path(document.path).render(document)
