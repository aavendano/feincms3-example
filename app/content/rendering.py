"""
Rendering without persistence coupling.

feincms3's ``RegionRenderer`` and content-editor's ``Contents`` only need
objects with ``region`` and ``ordering`` attributes and a class registered
with a renderer function. The one ORM assumption is that a registered class
exposes ``_meta.proxy`` / ``_meta.label_lower`` (Django model metadata).
``Component`` provides exactly that on plain dataclasses, so the *same*
renderer machinery used for Page plugins renders filesystem documents.

This is the seed of a future ComponentRegistry (see
docs/content-repository.md): components described by schemas, rendered by
feincms3, stored anywhere.
"""

from dataclasses import dataclass
from types import SimpleNamespace

import markdown
from content_editor.contents import Contents
from content_editor.models import Region
from django.utils.html import mark_safe
from feincms3.renderer import RegionRenderer


MARKDOWN_EXTENSIONS = ["extra", "sane_lists"]


class Component:
    """
    Mixin for non-ORM content blocks rendered through ``RegionRenderer``.

    Adds the minimal ``_meta`` shim RegionRenderer reads; nothing else.
    """

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls._meta = SimpleNamespace(
            proxy=False, label_lower=f"component.{cls.__name__.lower()}"
        )


@dataclass
class MarkdownBlock(Component):
    text: str
    region: str = "main"
    ordering: int = 0


def render_markdown(text):
    return markdown.markdown(text, extensions=MARKDOWN_EXTENSIONS)


ARTICLE_REGIONS = [Region(key="main", title="Main")]

renderer = RegionRenderer()
renderer.register(
    MarkdownBlock, lambda block, context: mark_safe(render_markdown(block.text))
)


def article_regions(article, context=None):
    """
    Turn an article into rendered regions, the same shape a feincms3 page
    template receives (``{"main": "<p>…</p>"}``).
    """
    contents = Contents(ARTICLE_REGIONS)
    contents.add(MarkdownBlock(text=article.body))
    return renderer.render_regions(
        regions=ARTICLE_REGIONS, contents=contents, context=context or {}
    )
