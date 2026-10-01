"""
Editorial UI for filesystem articles, mounted inside ``/admin-react/``.

django-admin-react renders whatever ``ModelAdmin``s the REST API exposes; it
has no extension point for non-model resources (its only hook, ModelAdmin
custom views, links out to legacy pages). Rather than inventing a fake model
— which would need a migration — this page is served under the SPA's URL
prefix, shares its session, CSRF cookie and staff login, and talks only to
``/api/content/``. A native SPA route consuming the same API is the
follow-up (see docs/content-repository.md).
"""

from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render


@staff_member_required
def article_editor(request):
    return render(request, "content/editor.html", {})
