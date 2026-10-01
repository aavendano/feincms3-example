from django.urls import path

from . import api, views


SLUG = "<slug:slug>"

public_patterns = (
    [
        path(
            "<str:market>/<str:locale>/articles/",
            views.article_list,
            name="article-list",
        ),
        path(
            f"<str:market>/<str:locale>/articles/{SLUG}/",
            views.article_detail,
            name="article-detail",
        ),
    ],
    "content",
)

api_patterns = (
    [
        path("meta/", api.meta, name="meta"),
        path("articles/", api.article_collection, name="articles"),
        path(
            f"articles/<str:market>/<str:locale>/{SLUG}/",
            api.article_detail,
            name="article",
        ),
    ],
    "content-api",
)
