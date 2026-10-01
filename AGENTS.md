# AGENTS.md

## What this is

A minimal but complete feincms3 example project (pages CMS + an articles app
mounted through feincms3's applications support). It exists to be read and run,
not to be deployed — keep it small and obvious.

## Environments

| Concern | Development | Production (example template) |
| --- | --- | --- |
| Settings | `app.settings.development` | `app.settings.production` |
| Default entry | `manage.py` | `app.wsgi` |
| Requirements | `requirements/development.txt` | `requirements/production.txt` |

Shared settings live in `app/settings/base.py`. Shared packages live in
`requirements/base.txt`. Root `requirements.txt` installs the development set.

`django-admin-react` is installed per environment:

- development: editable from `/home/alejandro/apps/django-admin-react`
- production: `git+https://github.com/aavendano/django-admin-react.git@main`

SPA mount: `/admin-react/` (legacy admin remains at `/admin/`).

## feincms3-filecontent

`packages/feincms3-filecontent/` is a reusable app (own `pyproject.toml`,
`README.md`, tests) installed editable in development. Keep it free of
project-specific code; the example only uses its public pieces
(`FileContent` abstract plugin, `FileContentInline`, `render_filecontent`,
`FILECONTENT` setting). Its tests run without network against local Git repos:

```
cd packages/feincms3-filecontent && pytest
```

The content working tree (`content/`) and `content.worktrees/` are git-ignored;
`./manage.py filecontent_sync` clones them from `FILECONTENT_REMOTE_URL`.

## Linting

Run all hooks over the whole tree:

```
prek -a
```

Hooks fix most things themselves; stage the result and run again. Ruff is
configured in `pyproject.toml` (`RUF012` and `E501` are ignored on purpose).
`prek` is listed in `requirements/development.txt`.

## Running the project

The example project itself has no test suite (the filecontent package does,
see above). Verify changes by running the app:

```
python3 -m venv venv
. venv/bin/activate
pip install -r requirements/development.txt
./manage.py migrate
./manage.py loaddata fixtures/pages.json fixtures/articles.json
./manage.py createsuperuser
./manage.py runserver
```

`./manage.py check` should only ever report the two `feincms3.W007` CKEditor 4
warnings; those come from feincms3's own rich text plugin.

## Migrations

Model definitions drift as the feincms3 / django-content-editor /
django-imagefield dependencies evolve. Add new migrations on top rather than
regenerating the initial ones, and keep `./manage.py makemigrations --check
--dry-run` clean.
