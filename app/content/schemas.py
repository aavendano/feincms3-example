"""
Document schemas for filesystem-backed editorial content.

A schema owns three things and nothing else:

* the fields of a document and their validation rules,
* how a document is serialized to text (Markdown + YAML front matter),
* how text is parsed back into a document.

It knows nothing about directories, files or Django models; the storage
location (market, locale, slug) is passed in by the repository, which derives
it from the path. Values derivable from the path are never written into the
front matter, so a file cannot contradict its own location.
"""

import datetime as dt
import re
from dataclasses import dataclass, field, replace

import yaml
from django.utils import timezone
from feincms3_filecontent.content.documents import content_hash
from feincms3_filecontent.content.parser import split_front_matter
from feincms3_filecontent.exceptions import DocumentValidationError

from .exceptions import InvalidDocument


MARKET_RE = re.compile(r"^[A-Z]{2}$")
LOCALE_RE = re.compile(r"^[a-z]{2}(?:-[a-z]{2})?$")
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

STATUS_DRAFT = "draft"
STATUS_PUBLISHED = "published"
STATUSES = (STATUS_DRAFT, STATUS_PUBLISHED)

# Same values as app.articles.models.Article.CATEGORIES; each category needs a
# matching application page type to be reachable through feincms3 pages.
CATEGORIES = ("blog", "publications")

# Front matter keys a file may contain. ``slug`` is accepted for readability
# but must match the file name; ``market``/``locale`` are never stored.
FRONT_MATTER_FIELDS = ("title", "slug", "status", "publication_date", "category")
MAX_TITLE_LENGTH = 200
MAX_BODY_BYTES = 1024 * 1024


@dataclass(frozen=True)
class ArticleKey:
    """Stable identity of an article: where it lives, not what it says."""

    market: str
    locale: str
    slug: str

    @property
    def id(self):
        return f"{self.market}/{self.locale}/{self.slug}"

    @classmethod
    def from_id(cls, value):
        parts = str(value).split("/")
        if len(parts) != 3:
            raise InvalidDocument({"id": ["Expected MARKET/locale/slug."]})
        key = cls(*parts)
        key.validate()
        return key

    def validate(self, *, markets=None):
        errors = {}
        if not MARKET_RE.match(self.market or ""):
            errors["market"] = ["Market must be two uppercase letters, e.g. CA."]
        elif markets is not None and self.market not in markets:
            errors["market"] = [f"Unknown market {self.market!r}."]
        if not LOCALE_RE.match(self.locale or ""):
            errors["locale"] = ["Locale must look like 'en' or 'en-ca'."]
        elif (
            markets is not None
            and self.market in markets
            and self.locale not in markets[self.market]
        ):
            errors["locale"] = [
                f"Locale {self.locale!r} is not enabled for market {self.market}."
            ]
        if not SLUG_RE.match(self.slug or ""):
            errors["slug"] = ["Slug may contain lowercase letters, digits and '-'."]
        if errors:
            raise InvalidDocument(errors)
        return self


@dataclass(frozen=True)
class Article:
    """
    An article as editors see it. Plain value object: no ORM, no paths.

    ``version`` is the SHA-256 of the file as read; writers pass it back to
    detect concurrent edits. A Git backend can keep the same contract (the
    blob content still identifies the version a client started from).
    """

    key: ArticleKey
    title: str
    status: str
    publication_date: dt.datetime
    category: str
    body: str = field(repr=False)
    version: str = ""

    market = property(lambda self: self.key.market)
    locale = property(lambda self: self.key.locale)
    slug = property(lambda self: self.key.slug)
    id = property(lambda self: self.key.id)

    @property
    def is_draft(self):
        return self.status == STATUS_DRAFT

    def is_published(self, now=None):
        return self.status == STATUS_PUBLISHED and self.publication_date <= (
            now or timezone.now()
        )

    def with_key(self, key):
        return replace(self, key=key)


def _as_datetime(value):
    if isinstance(value, dt.datetime):
        moment = value
    elif isinstance(value, dt.date):
        moment = dt.datetime.combine(value, dt.time.min)
    elif isinstance(value, str) and value.strip():
        try:
            moment = dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if timezone.is_naive(moment):
        moment = moment.replace(tzinfo=dt.timezone.utc)
    return moment


def validate_fields(data):
    """
    Validate editable fields; return cleaned values or raise ``InvalidDocument``
    with every problem found.
    """
    errors = {}
    cleaned = {}

    title = data.get("title")
    if not isinstance(title, str) or not title.strip():
        errors["title"] = ["Title is required."]
    elif len(title.strip()) > MAX_TITLE_LENGTH:
        errors["title"] = [f"Title may be at most {MAX_TITLE_LENGTH} characters."]
    else:
        cleaned["title"] = title.strip()

    status = data.get("status", STATUS_DRAFT)
    if status not in STATUSES:
        errors["status"] = [f"Status must be one of {', '.join(STATUSES)}."]
    else:
        cleaned["status"] = status

    publication_date = _as_datetime(data.get("publication_date"))
    if publication_date is None:
        errors["publication_date"] = ["A valid ISO 8601 date/time is required."]
    else:
        cleaned["publication_date"] = publication_date.astimezone(dt.timezone.utc)

    category = data.get("category")
    if category not in CATEGORIES:
        errors["category"] = [f"Category must be one of {', '.join(CATEGORIES)}."]
    else:
        cleaned["category"] = category

    body = data.get("body", "")
    if not isinstance(body, str):
        errors["body"] = ["Body must be text."]
    elif "\x00" in body:
        errors["body"] = ["Body contains NUL bytes."]
    elif len(body.encode("utf-8")) > MAX_BODY_BYTES:
        errors["body"] = [f"Body may be at most {MAX_BODY_BYTES} bytes."]
    else:
        cleaned["body"] = body

    if errors:
        raise InvalidDocument(errors)
    return cleaned


def build_article(key, data, *, version=""):
    return Article(key=key, version=version, **validate_fields(data))


def _format_datetime(value):
    return value.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def serialize(article):
    """Article -> Markdown text with YAML front matter (stable key order)."""
    meta = {
        "title": article.title,
        "status": article.status,
        "publication_date": _format_datetime(article.publication_date),
        "category": article.category,
    }
    front_matter = yaml.safe_dump(
        meta, sort_keys=False, allow_unicode=True, default_flow_style=False
    )
    body = article.body
    if body and not body.endswith("\n"):
        body += "\n"
    return f"---\n{front_matter}---\n\n{body}"


def parse(key, text):
    """
    Markdown text -> Article located at ``key``.

    Raises ``InvalidDocument`` for malformed front matter, unknown keys,
    a ``slug`` that contradicts the file name, or invalid field values.
    """
    try:
        meta, body = split_front_matter(text)
    except DocumentValidationError as exc:
        raise InvalidDocument({"document": exc.errors}) from exc
    if not meta:
        raise InvalidDocument({"document": ["Missing YAML front matter."]})
    unknown = sorted(set(meta) - set(FRONT_MATTER_FIELDS))
    if unknown:
        raise InvalidDocument(
            {"document": [f"Unknown front matter keys: {', '.join(unknown)}."]}
        )
    if "slug" in meta and meta["slug"] != key.slug:
        raise InvalidDocument(
            {
                "slug": [
                    f"Front matter slug {meta['slug']!r} does not match the file name."
                ]
            }
        )
    return build_article(
        key, {**meta, "body": body.lstrip("\n")}, version=content_hash(text)
    )
