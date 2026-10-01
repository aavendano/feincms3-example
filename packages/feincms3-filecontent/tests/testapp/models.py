from content_editor.models import Region, create_plugin_base
from feincms3.pages import AbstractPage

from feincms3_filecontent.feincms.models import FileContent as AbstractFileContent


class Page(AbstractPage):
    regions = [Region(key="main", title="Main")]


PagePlugin = create_plugin_base(Page)


class FileContent(AbstractFileContent, PagePlugin):
    pass
