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
        path(
            f"articles/<str:market>/<str:locale>/{SLUG}/history/",
            api.article_history,
            name="article-history",
        ),
        path(
            f"articles/<str:market>/<str:locale>/{SLUG}/diff/",
            api.article_diff,
            name="article-diff",
        ),
        path(
            f"articles/<str:market>/<str:locale>/{SLUG}/restore/",
            api.article_restore,
            name="article-restore",
        ),
        path("repository/", api.repository_status, name="repository"),
        path("repository/sync/", api.repository_sync, name="repository-sync"),
    ],
    "content-api",
)
