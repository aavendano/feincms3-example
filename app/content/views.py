"""
Public rendering of filesystem articles:

    content/{MARKET}/{locale}/articles/{slug}.md
        -> FilesystemArticleRepository
        -> these views
        -> RegionRenderer (via app.content.rendering)
        -> templates/content/*.html

Only published articles (status ``published`` and publication date reached)
are visible. No ORM query is made for the article itself.
"""

from django.http import Http404
from django.shortcuts import render

from . import get_article_repository, rendering, schemas
from .exceptions import DocumentNotFound, InvalidDocument
from .repository import ArticleFilter


def _location(market, locale):
    market = market.upper()
    repository = get_article_repository()
    if locale not in repository.markets.get(market, ()):
        raise Http404("Unknown market or locale.")
    return repository, market


def article_list(request, market, locale):
    repository, market = _location(market, locale)
    articles = repository.list(
        ArticleFilter(
            market=market,
            locale=locale,
            category=request.GET.get("category") or None,
            published_only=True,
        )
    )
    return render(
        request,
        "content/article_list.html",
        {"articles": articles, "market": market, "locale": locale},
    )


def article_detail(request, market, locale, slug):
    repository, market = _location(market, locale)
    try:
        article = repository.get(schemas.ArticleKey(market, locale, slug))
    except (DocumentNotFound, InvalidDocument):
        raise Http404("Article not found.") from None
    if not article.is_published():
        raise Http404("Article not found.")
    return render(
        request,
        "content/article_detail.html",
        {
            "article": article,
            "regions": rendering.article_regions(article, {"request": request}),
        },
    )
