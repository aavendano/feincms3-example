"""
Admin: a read-only view of the content index plus an editor that writes
through the ContentWriter (validate -> write -> commit -> push) or opens a
review branch. Rows are never edited directly; they are a projection.
"""

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import render
from django.urls import path as url_path, reverse
from django.utils.html import format_html
from django.utils.http import urlencode
from django.utils.translation import gettext_lazy as _

from . import services
from .conf import get_settings
from .content.documents import content_hash
from .exceptions import (
    ConflictError,
    DocumentNotFound,
    DocumentValidationError,
    FileContentError,
    StaleDocumentError,
)
from .models import ContentIndex, RepositoryState
from .storage.filesystem import normalize_path
from .sync.engine import SyncEngine
from .workflow import rollback
from .workflow.commits import ContentWriter, author_for
from .workflow.proposals import propose_change


EDIT_PERMISSION = "feincms3_filecontent.edit_document"
MANAGE_PERMISSION = "feincms3_filecontent.manage_repository"


def admin_url(name, **params):
    url = reverse(f"admin:feincms3_filecontent_{name}")
    return f"{url}?{urlencode(params)}" if params else url


class DocumentForm(forms.Form):
    MODES = [
        ("direct", _("Commit to the main branch")),
        ("review", _("Propose on a review branch")),
    ]

    path = forms.CharField(label=_("path"), max_length=500)
    text = forms.CharField(
        label=_("content"),
        widget=forms.Textarea(
            attrs={
                "rows": 30,
                "style": "width:100%;font-family:monospace",
                "spellcheck": "true",
            }
        ),
        strip=False,
    )
    message = forms.CharField(label=_("commit message"), max_length=500)
    mode = forms.ChoiceField(label=_("mode"), choices=MODES, initial="direct")
    branch = forms.CharField(
        label=_("review branch"),
        max_length=200,
        required=False,
        help_text=_("Optional; defaults to content/update-<slug>."),
    )
    expected_hash = forms.CharField(widget=forms.HiddenInput, required=False)

    def __init__(self, *args, existing=False, **kwargs):
        super().__init__(*args, **kwargs)
        if existing:
            self.fields["path"].widget.attrs["readonly"] = True

    def clean_path(self):
        try:
            return normalize_path(self.cleaned_data["path"])
        except FileContentError as exc:
            raise forms.ValidationError(str(exc)) from exc


@admin.register(ContentIndex)
class ContentIndexAdmin(admin.ModelAdmin):
    change_list_template = "admin/feincms3_filecontent/contentindex/change_list.html"
    list_display = [
        "path",
        "title",
        "locale",
        "status_badge",
        "short_sha",
        "modified_at",
    ]
    list_filter = ["status", "locale", "content_type"]
    search_fields = ["path", "title", "slug"]
    readonly_fields = [f.name for f in ContentIndex._meta.fields]

    @admin.display(description=_("status"), ordering="status")
    def status_badge(self, obj):
        if obj.status == ContentIndex.Status.OK:
            return obj.get_status_display()
        return format_html(
            '<strong style="color:#c00" title="{}">{}</strong>',
            obj.error,
            obj.get_status_display(),
        )

    @admin.display(description=_("Git SHA"), ordering="git_sha")
    def short_sha(self, obj):
        return obj.git_sha[:10]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return request.user.has_perm(
            "feincms3_filecontent.view_contentindex"
        ) or request.user.has_perm(EDIT_PERMISSION)

    def get_urls(self):
        view = self.admin_site.admin_view
        return [
            url_path(
                "document/edit/", view(self.edit_view), name="feincms3_filecontent_edit"
            ),
            url_path(
                "document/history/",
                view(self.history_view),
                name="feincms3_filecontent_history",
            ),
            url_path(
                "document/diff/", view(self.diff_view), name="feincms3_filecontent_diff"
            ),
            url_path(
                "document/restore/",
                view(self.restore_view),
                name="feincms3_filecontent_restore",
            ),
            url_path(
                "repository/sync/",
                view(self.sync_view),
                name="feincms3_filecontent_sync",
            ),
            url_path(
                "repository/rebuild/",
                view(self.rebuild_view),
                name="feincms3_filecontent_rebuild",
            ),
            *super().get_urls(),
        ]

    def changelist_view(self, request, extra_context=None):
        conf = get_settings()
        repo = services.get_repository()
        extra_context = extra_context or {}
        try:
            extra_context["repository_status"] = (
                repo.status() if repo.exists() else None
            )
        except FileContentError as exc:
            extra_context["repository_error"] = exc
        extra_context["repository_state"] = RepositoryState.objects.filter(
            branch=conf.branch
        ).first()
        extra_context["can_edit"] = (
            request.user.has_perm(EDIT_PERMISSION) and not conf.read_only
        )
        extra_context["can_manage"] = request.user.has_perm(MANAGE_PERMISSION)
        return super().changelist_view(request, extra_context)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        obj = self.get_object(request, object_id)
        if obj is None:
            raise Http404
        return HttpResponseRedirect(admin_url("edit", path=obj.path))

    # Helpers ---------------------------------------------------------------

    def _context(self, request, **kwargs):
        return {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "app_label": self.model._meta.app_label,
            **kwargs,
        }

    def _require(self, request, permission):
        if not request.user.has_perm(permission):
            raise PermissionDenied

    def _changelist_url(self):
        return admin_url("contentindex_changelist")

    # Views -----------------------------------------------------------------

    def edit_view(self, request):
        self._require(request, EDIT_PERMISSION)
        conf = get_settings()
        store = services.get_store()
        path = request.POST.get("path") or request.GET.get("path") or ""
        existing = bool(path) and store.exists(path)

        if request.method == "POST" and not conf.read_only:
            form = DocumentForm(request.POST, existing=existing)
            if form.is_valid():
                response = self._save(request, form)
                if response:
                    return response
        else:
            initial = {"path": path, "mode": "direct", "expected_hash": ""}
            if existing:
                raw = store.read_bytes(path)
                initial.update(
                    text=raw.decode("utf-8", errors="replace"),
                    expected_hash=content_hash(raw),
                    message=f"Update {path}",
                )
            else:
                initial.update(
                    text="---\ntitle: \n---\n\n", message=f"Add {path}" if path else ""
                )
            form = DocumentForm(initial=initial, existing=existing)

        return render(
            request,
            "admin/feincms3_filecontent/editor.html",
            self._context(
                request,
                title=_("Edit %(path)s") % {"path": path}
                if path
                else _("New document"),
                form=form,
                path=path,
                existing=existing,
                read_only=conf.read_only,
            ),
        )

    def _save(self, request, form):
        data = form.cleaned_data
        author = author_for(request.user)
        try:
            if data["mode"] == "review":
                proposal = propose_change(
                    data["path"],
                    data["text"],
                    message=data["message"],
                    branch=data["branch"] or None,
                    author=author,
                    expected_hash=data["expected_hash"],
                )
                if proposal.pull_request:
                    messages.success(
                        request,
                        format_html(
                            'Proposed on {} — <a href="{}">pull request #{}</a>.',
                            proposal.branch,
                            proposal.pull_request.url,
                            proposal.pull_request.number,
                        ),
                    )
                else:
                    messages.success(
                        request,
                        f"Committed to branch {proposal.branch}"
                        + (
                            " and pushed."
                            if proposal.pushed
                            else " (not pushed: no remote)."
                        ),
                    )
            else:
                result = ContentWriter.default().save(
                    data["path"],
                    data["text"],
                    message=data["message"],
                    author=author,
                    expected_hash=data["expected_hash"],
                )
                if not result.changed:
                    messages.info(request, _("No changes."))
                else:
                    messages.success(request, f"Committed {result.sha[:10]}.")
                if result.push_error:
                    messages.warning(
                        request,
                        f"Committed locally but not pushed: {result.push_error}",
                    )
                if result.sync_error:
                    messages.warning(
                        request, f"Content index not updated: {result.sync_error}"
                    )
        except DocumentValidationError as exc:
            for error in exc.errors:
                form.add_error("text", error)
            return None
        except StaleDocumentError as exc:
            form.add_error(
                None, f"{exc}. Copy your changes, reload the page and apply them again."
            )
            return None
        except ConflictError as exc:
            form.add_error(None, f"Repository conflict: {exc}")
            return None
        except FileContentError as exc:
            form.add_error(None, str(exc))
            return None
        return HttpResponseRedirect(admin_url("edit", path=data["path"]))

    def history_view(self, request):
        self._require(request, EDIT_PERMISSION)
        path = request.GET.get("path", "")
        try:
            entries = rollback.history(path)
        except FileContentError as exc:
            messages.error(request, str(exc))
            return HttpResponseRedirect(self._changelist_url())
        store = services.get_store()
        current_hash = (
            content_hash(store.read_bytes(path)) if store.exists(path) else ""
        )
        return render(
            request,
            "admin/feincms3_filecontent/history.html",
            self._context(
                request,
                title=_("History of %(path)s") % {"path": path},
                path=path,
                entries=entries,
                current_hash=current_hash,
                read_only=get_settings().read_only,
            ),
        )

    def diff_view(self, request):
        self._require(request, EDIT_PERMISSION)
        path, sha = request.GET.get("path", ""), request.GET.get("sha", "")
        try:
            diff = rollback.version_diff(path, sha)
        except FileContentError as exc:
            messages.error(request, str(exc))
            return HttpResponseRedirect(self._changelist_url())
        return render(
            request,
            "admin/feincms3_filecontent/diff.html",
            self._context(
                request, title=f"{path} @ {sha[:10]}", path=path, sha=sha, diff=diff
            ),
        )

    def restore_view(self, request):
        self._require(request, EDIT_PERMISSION)
        if request.method != "POST":
            return HttpResponseRedirect(self._changelist_url())
        path, sha = request.POST.get("path", ""), request.POST.get("sha", "")
        history_url = admin_url("history", path=path)
        try:
            result = rollback.restore(
                path,
                sha,
                author=author_for(request.user),
                expected_hash=request.POST.get("expected_hash"),
            )
        except DocumentNotFound:
            messages.error(request, f"{path} did not exist at {sha[:10]}.")
        except (FileContentError, ValueError) as exc:
            messages.error(request, str(exc))
        else:
            if result.changed:
                messages.success(
                    request, f"Restored {path} to {sha[:10]} as {result.sha[:10]}."
                )
            else:
                messages.info(request, _("The document already has this content."))
            if result.push_error:
                messages.warning(request, f"Not pushed: {result.push_error}")
        return HttpResponseRedirect(history_url)

    def sync_view(self, request):
        self._require(request, MANAGE_PERMISSION)
        return self._repository_action(request, "sync")

    def rebuild_view(self, request):
        self._require(request, MANAGE_PERMISSION)
        return self._repository_action(request, "rebuild")

    def _repository_action(self, request, action):
        if request.method != "POST":
            return HttpResponseRedirect(self._changelist_url())
        try:
            if action == "rebuild":
                summary = SyncEngine.default().rebuild().summary()
            else:
                repo = services.get_repository()
                if repo.exists():
                    conf = get_settings()
                    outcome = ContentWriter.default().synchronize(
                        push=not conf.read_only
                    )
                    summary = outcome.sync.summary()
                else:
                    summary = SyncEngine.default().sync().summary()
        except ConflictError as exc:
            messages.error(request, f"Repository conflict: {exc}")
        except FileContentError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, summary)
        return HttpResponseRedirect(self._changelist_url())


@admin.register(RepositoryState)
class RepositoryStateAdmin(admin.ModelAdmin):
    list_display = [
        "branch",
        "last_indexed_sha",
        "indexed_at",
        "last_sync_mode",
        "last_error",
    ]
    readonly_fields = [f.name for f in RepositoryState._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
