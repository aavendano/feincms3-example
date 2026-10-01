from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from app.content import editor
from app.content.urls import api_patterns, public_patterns


urlpatterns = [
    path("admin/", admin.site.urls),
    # Filesystem articles editor: inside the SPA's URL space (same session /
    # CSRF / staff login), declared before the SPA catch-all.
    path(
        "admin-react/content/articles/",
        editor.article_editor,
        name="content-editor",
    ),
    path("admin-react/", include("django_admin_react.urls")),
    path("api/content/", include(api_patterns)),
    path("content/", include(public_patterns)),
]
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
