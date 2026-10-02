from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from app.content import editor
from app.content.urls import api_patterns, public_patterns


urlpatterns = [
    path("admin/", admin.site.urls),
]
if not settings.CONTENT_EDITOR_IN_SPA:
    # Older django-admin-react without CUSTOM_PAGES: serve the editor module
    # from a standalone page inside the SPA's URL space (same session / CSRF
    # / staff login), declared before the SPA catch-all.
    urlpatterns.append(
        path(
            "admin-react/content/articles/",
            editor.article_editor,
            name="content-editor",
        )
    )
urlpatterns += [
    path("admin-react/", include("django_admin_react.urls")),
    path("api/content/", include(api_patterns)),
    path("content/", include(public_patterns)),
]
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
