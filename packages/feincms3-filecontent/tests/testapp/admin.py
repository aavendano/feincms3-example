from content_editor.admin import ContentEditor
from django.contrib import admin
from feincms3.admin import TreeAdmin

from feincms3_filecontent.feincms.plugins import FileContentInline

from . import models


@admin.register(models.Page)
class PageAdmin(ContentEditor, TreeAdmin):
    inlines = [FileContentInline.create(model=models.FileContent)]
