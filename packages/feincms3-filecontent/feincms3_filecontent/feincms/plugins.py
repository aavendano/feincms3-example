from content_editor.admin import ContentEditorInline
from django import forms

from ..models import ContentIndex
from .models import FileContent, validate_content_path
from .renderer import load_document, render_filecontent


__all__ = (
    "FileContent",
    "FileContentForm",
    "FileContentInline",
    "load_document",
    "render_filecontent",
    "validate_content_path",
)


def document_choices(current=None):
    rows = ContentIndex.objects.filter(status=ContentIndex.Status.OK).values_list(
        "path", "title", "locale"
    )
    choices = [
        (path, f"{path} — {title}" + (f" [{locale}]" if locale else ""))
        for path, title, locale in rows
    ]
    if current and current not in {c[0] for c in choices}:
        choices.insert(0, (current, current))
    return choices


class FileContentForm(forms.ModelForm):
    """Offers indexed documents as choices; falls back to a text input."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        field = self.fields.get("content_path")
        if field is None:
            return
        choices = document_choices(self.initial.get("content_path"))
        if choices:
            field.widget = forms.Select(choices=[("", "---------"), *choices])


class FileContentInline(ContentEditorInline):
    form = FileContentForm
    button = '<span class="material-icons">description</span>'
