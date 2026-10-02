"""
JSON API over the article repository, used by the admin editor.

Authentication, sessions and CSRF are Django's own (no tokens, no parallel
auth). Authorization reuses the existing ``articles`` permissions
(view/add/change/delete_article) so no new permission rows — and no
migration — are needed for the proof of concept.

    GET    /api/content/meta/
    GET    /api/content/articles/?market=CA&locale=en&category=blog&status=draft&limit=20&offset=0
    POST   /api/content/articles/
    GET    /api/content/articles/<MARKET>/<locale>/<slug>/
    PUT    /api/content/articles/<MARKET>/<locale>/<slug>/   (body may move it)
    DELETE /api/content/articles/<MARKET>/<locale>/<slug>/   (If-Match: <version>)

Versioned backends (``"history" in capabilities``) add:

    GET    /api/content/articles/<MARKET>/<locale>/<slug>/history/
    GET    /api/content/articles/<MARKET>/<locale>/<slug>/diff/?version=<sha>[&to=<sha>]
    POST   /api/content/articles/<MARKET>/<locale>/<slug>/restore/  {"version": sha}
    GET    /api/content/repository/            backend state (AHEAD, DIVERGED, …)
    POST   /api/content/repository/sync/       fetch + fast-forward + push, never merges

The browser only ever sees article ids (``CA/en/example``), never paths.
"""

import functools
import json

from django.http import JsonResponse
from django.urls import NoReverseMatch, reverse
from django.views.decorators.http import require_http_methods
from feincms3_filecontent.exceptions import ConflictError, RepositoryError
from feincms3_filecontent.repository.git import redact

from . import get_article_repository, schemas
from .exceptions import (
    DocumentAlreadyExists,
    DocumentNotFound,
    InvalidDocument,
    OperationNotSupported,
    VersionConflict,
)
from .repository import ORDER_OLDEST_FIRST, ArticleFilter, ChangeContext


PERMISSIONS = {
    "GET": "articles.view_article",
    "POST": "articles.add_article",
    "PUT": "articles.change_article",
    "DELETE": "articles.delete_article",
}


def error(status, message, **extra):
    return JsonResponse({"error": message, **extra}, status=status)


def staff_api(view=None, *, permission=None):
    """
    Session auth + staff + permission (per HTTP method unless ``permission``
    is given), with content and repository errors answered as JSON.
    """
    if view is None:
        return functools.partial(staff_api, permission=permission)

    @functools.wraps(view)
    def wrapper(request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            return error(401, "Authentication required.")
        if not user.is_staff:
            return error(403, "Staff access required.")
        required = permission or PERMISSIONS.get(request.method)
        if required and not user.has_perm(required):
            return error(403, f"Missing permission {required}.")
        try:
            return view(request, *args, **kwargs)
        except InvalidDocument as exc:
            return error(400, "Invalid article.", errors=exc.errors)
        except DocumentNotFound:
            return error(404, "Article not found.")
        except DocumentAlreadyExists as exc:
            return error(
                409, "An article already exists at this location.", id=str(exc)
            )
        except VersionConflict as exc:
            return error(
                409,
                "The article was changed by someone else; reload it.",
                current_version=exc.current_version,
            )
        except OperationNotSupported as exc:
            return error(501, str(exc))
        except ConflictError as exc:
            # Dirty tree, divergence, unfinished merge, rejected push: never
            # resolved automatically; the paths tell a human where to look.
            return error(
                409, f"Repository conflict: {redact(str(exc))}", paths=exc.paths
            )
        except RepositoryError as exc:
            return error(503, f"Content repository unavailable: {redact(str(exc))}")

    return wrapper


def public_url(article):
    if not article.is_published():
        return None
    try:
        return reverse(
            "content:article-detail",
            kwargs={
                "market": article.market.lower(),
                "locale": article.locale,
                "slug": article.slug,
            },
        )
    except NoReverseMatch:
        return None


def to_json(article, *, repository, with_body=True):
    data = {
        "id": article.id,
        "market": article.market,
        "locale": article.locale,
        "slug": article.slug,
        "title": article.title,
        "status": article.status,
        "is_published": article.is_published(),
        "publication_date": schemas._format_datetime(article.publication_date),
        "category": article.category,
        "version": article.version,
        "source": repository.backend,
        "location": repository.describe_location(article.key),
        "public_url": public_url(article),
    }
    if with_body:
        data["body"] = article.body
    return data


def commit_payload(repository):
    """The commit a versioned backend made for this request's write, if any."""
    commit = getattr(repository, "last_commit", lambda: None)()
    return {"commit": commit.as_dict()} if commit is not None else {}


def written(article, repository, status=200):
    return JsonResponse(
        {**to_json(article, repository=repository), **commit_payload(repository)},
        status=status,
    )


MAX_PAGE_SIZE = 200


def _int_param(params, name, default, *, maximum=None):
    raw = params.get(name)
    if raw in (None, ""):
        return default
    try:
        value = int(raw)
    except ValueError:
        raise InvalidDocument({name: ["Must be an integer."]}) from None
    if value < 0 or (maximum is not None and value > maximum):
        limit = f" and at most {maximum}" if maximum is not None else ""
        raise InvalidDocument({name: [f"Must be at least 0{limit}."]})
    return value


def read_json(request):
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        raise InvalidDocument(
            {"document": ["Request body is not valid JSON."]}
        ) from None
    if not isinstance(data, dict):
        raise InvalidDocument({"document": ["Expected a JSON object."]})
    return data


def context_for(request):
    user = request.user
    return ChangeContext(
        author_name=user.get_full_name() or user.get_username(),
        author_email=getattr(user, "email", ""),
    )


def article_from(data, repository):
    key = schemas.ArticleKey(
        str(data.get("market", "")),
        str(data.get("locale", "")),
        str(data.get("slug", "")),
    )
    try:
        key.validate(markets=repository.markets)
        key_errors = {}
    except InvalidDocument as exc:
        key_errors = exc.errors
    try:
        fields = schemas.validate_fields(data)
    except InvalidDocument as exc:
        raise InvalidDocument({**key_errors, **exc.errors}) from exc
    if key_errors:
        raise InvalidDocument(key_errors)
    return schemas.Article(key=key, **fields)


@require_http_methods(["GET"])
@staff_api
def meta(request):
    repository = get_article_repository()
    return JsonResponse(
        {
            "source": repository.backend,
            "root": repository.root.name,
            "markets": {m: list(locs) for m, locs in repository.markets.items()},
            "categories": list(schemas.CATEGORIES),
            "statuses": list(schemas.STATUSES),
            "capabilities": sorted(repository.capabilities),
            "invalid_documents": repository.invalid_documents(),
        }
    )


@require_http_methods(["GET", "POST"])
@staff_api
def article_collection(request):
    repository = get_article_repository()
    if request.method == "POST":
        article = repository.create(
            article_from(read_json(request), repository), context=context_for(request)
        )
        return written(article, repository, status=201)

    params = request.GET
    status = params.get("status") or None
    if status and status not in schemas.STATUSES:
        raise InvalidDocument({"status": ["Unknown status."]})
    query = ArticleFilter(
        market=params.get("market") or None,
        locale=params.get("locale") or None,
        category=params.get("category") or None,
        status=status,
        order=ORDER_OLDEST_FIRST
        if params.get("order") == "publication_date"
        else "-publication_date",
        limit=_int_param(params, "limit", None, maximum=MAX_PAGE_SIZE),
        offset=_int_param(params, "offset", 0),
    )
    articles = repository.list(query)
    return JsonResponse(
        {
            "count": repository.count(query),
            "limit": query.limit,
            "offset": query.offset,
            "results": [
                to_json(a, repository=repository, with_body=False) for a in articles
            ],
        }
    )


@require_http_methods(["GET", "PUT", "DELETE"])
@staff_api
def article_detail(request, market, locale, slug):
    repository = get_article_repository()
    key = schemas.ArticleKey(market, locale, slug)
    if request.method == "GET":
        return JsonResponse(to_json(repository.get(key), repository=repository))
    if request.method == "DELETE":
        version = request.headers.get("If-Match") or request.GET.get("version")
        repository.delete(key, expected_version=version, context=context_for(request))
        return JsonResponse({"deleted": key.id, **commit_payload(repository)})

    data = read_json(request)
    # Location fields default to the current ones; changing them is a move.
    data = {"market": market, "locale": locale, "slug": slug, **data}
    article = repository.update(
        key,
        article_from(data, repository),
        expected_version=data.get("version"),
        context=context_for(request),
    )
    return written(article, repository)


@require_http_methods(["GET"])
@staff_api
def article_history(request, market, locale, slug):
    repository = get_article_repository()
    key = schemas.ArticleKey(market, locale, slug)
    return JsonResponse({"id": key.id, "entries": repository.history(key)})


@require_http_methods(["GET"])
@staff_api
def article_diff(request, market, locale, slug):
    repository = get_article_repository()
    key = schemas.ArticleKey(market, locale, slug)
    version = request.GET.get("version", "")
    diff = repository.diff(key, version, request.GET.get("to") or None)
    return JsonResponse({"id": key.id, "version": version, "diff": diff})


@require_http_methods(["POST"])
@staff_api(permission="articles.change_article")
def article_restore(request, market, locale, slug):
    repository = get_article_repository()
    key = schemas.ArticleKey(market, locale, slug)
    data = read_json(request)
    article = repository.restore(
        key,
        str(data.get("version", "")),
        expected_version=data.get("expected_version"),
        context=context_for(request),
    )
    return written(article, repository)


@require_http_methods(["GET"])
@staff_api
def repository_status(request):
    return JsonResponse(get_article_repository().status())


@require_http_methods(["POST"])
@staff_api(permission="articles.change_article")
def repository_sync(request):
    """Git: fetch/fast-forward/push. Indexed repositories: then reindex."""
    repository = get_article_repository()
    if not hasattr(repository, "sync"):
        raise OperationNotSupported("sync requires a Git backend or the index")
    return JsonResponse(repository.sync())
