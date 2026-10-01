from django.core import checks

from .conf import get_settings
from .exceptions import ConfigurationError
from .repository.git import has_credentials


@checks.register()
def filecontent_settings(app_configs, **kwargs):
    try:
        conf = get_settings()
    except ConfigurationError as exc:
        return [checks.Error(str(exc), id="feincms3_filecontent.E001")]
    messages = []
    if has_credentials(conf.remote_url):
        messages.append(
            checks.Warning(
                'FILECONTENT["REMOTE_URL"] embeds credentials.',
                hint="Use an SSH key or a Git credential helper instead.",
                id="feincms3_filecontent.W001",
            )
        )
    if conf.worktrees_dir == conf.root or conf.root in conf.worktrees_dir.parents:
        messages.append(
            checks.Error(
                'FILECONTENT["WORKTREES_DIR"] must be outside of ROOT.',
                id="feincms3_filecontent.E002",
            )
        )
    return messages
