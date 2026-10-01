"""
Rendering path: Page -> FileContent -> ContentStore -> Document -> HTML.

Only the local filesystem is touched; parsed documents are cached in-process
and invalidated by the file's mtime and size, so an atomic replace by a write
or a ``git pull`` is picked up on the next request.
"""

import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass

from django.template.loader import render_to_string
from django.utils.html import mark_safe

from .. import services
from ..conf import get_settings
from ..exceptions import FileContentError


logger = logging.getLogger(__name__)

TEMPLATE = "feincms3_filecontent/plugins/filecontent.html"
ERROR_TEMPLATE = "feincms3_filecontent/plugins/error.html"


@dataclass(frozen=True)
class Rendered:
    document: object
    html: str


class DocumentLoader:
    def __init__(self, maxsize=512):
        self.maxsize = maxsize
        self._cache = OrderedDict()
        self._lock = threading.Lock()

    def clear(self):
        with self._lock:
            self._cache.clear()

    def load(self, path):
        store = services.get_store()
        stat = store.stat(path)
        key = (stat.path, stat.mtime_ns, stat.size)
        with self._lock:
            hit = self._cache.get(stat.path)
            if hit and hit[0] == key:
                self._cache.move_to_end(stat.path)
                return hit[1]
        registry = services.get_registry()
        document = registry.parse(
            stat.path, store.read(stat.path), modified_at=stat.modified_at
        )
        html = registry.render(document)
        sanitizer = get_settings().sanitizer
        if sanitizer:
            html = sanitizer(html)
        rendered = Rendered(document=document, html=mark_safe(html))
        with self._lock:
            self._cache[stat.path] = (key, rendered)
            self._cache.move_to_end(stat.path)
            while len(self._cache) > self.maxsize:
                self._cache.popitem(last=False)
        return rendered


loader = DocumentLoader()


def load_document(path):
    """Return ``Rendered(document, html)`` for ``path``; raises on errors."""
    return loader.load(path)


def _request(context):
    try:
        return context.get("request") if context is not None else None
    except AttributeError:
        return None


def render_filecontent(plugin, context=None, *, template_name=TEMPLATE):
    """
    feincms3 renderer for ``FileContent`` plugins::

        renderer.register(models.FileContent, render_filecontent)

    Missing or broken documents never break the page: they render as an empty
    string (and are logged), or as a visible error box when ``SHOW_ERRORS``.
    """
    try:
        rendered = loader.load(plugin.content_path)
    except FileContentError as exc:
        logger.error("Cannot render %s: %s", plugin.content_path, exc)
        if get_settings().show_errors:
            return render_to_string(
                ERROR_TEMPLATE,
                {"plugin": plugin, "error": exc},
                request=_request(context),
            )
        return ""
    return render_to_string(
        template_name,
        {"plugin": plugin, "document": rendered.document, "html": rendered.html},
        request=_request(context),
    )
