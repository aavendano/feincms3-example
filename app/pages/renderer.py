from django.utils.html import mark_safe
from feincms3.renderer import RegionRenderer, template_renderer
from feincms3_filecontent.feincms.renderer import render_filecontent

from app.pages import models


renderer = RegionRenderer()
renderer.register(
    models.RichText,
    lambda plugin, context: mark_safe(plugin.text),
)
renderer.register(
    models.Image,
    template_renderer("plugins/image.html"),
)
renderer.register(models.FileContent, render_filecontent)
