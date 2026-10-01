from django.utils import timezone

from ..models import RepositoryState


def get_state(branch):
    state, _created = RepositoryState.objects.get_or_create(branch=branch)
    return state


def mark_indexed(branch, sha, *, mode):
    state = get_state(branch)
    state.last_indexed_sha = sha or ""
    state.indexed_at = timezone.now()
    state.last_sync_mode = mode
    state.last_error = ""
    state.save()
    return state


def mark_error(branch, error):
    state = get_state(branch)
    state.last_error = str(error)
    state.save(update_fields=["last_error", "updated_at"])
    return state
