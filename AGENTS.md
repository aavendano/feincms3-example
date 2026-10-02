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

- development: editable from `/home/alejandro/apps/django-admin-react`;
  build its SPA bundle with `scripts/install-admin-react.sh --editable`
- production: `scripts/install-admin-react.sh` clones
  `https://github.com/aavendano/django-admin-react.git@main`, builds the
  bundle and pip-installs it (not listed in `requirements/production.txt`)

The fork does not commit the built bundle, so installing it without the
Vite build triggers `django_admin_react.W002` and the SPA shows "not built
yet". Needs node >= 20 and pnpm (`corepack enable`).

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

The content working tree (`filecontent/`) and `filecontent.worktrees/` are git-ignored;
`./manage.py filecontent_sync` clones them from `FILECONTENT_REMOTE_URL`.

## Filesystem articles (POC)

`app/content/` is a content repository for articles stored as Markdown in
`content/{MARKET}/{locale}/articles/*.md` (settings: `CONTENT_REPOSITORY`).
The ORM `Article` model is untouched and independent. Backends:
`filesystem` (default) and `git` (`app/content/git.py`, built on
`feincms3_filecontent.repository`; one commit per change). Listings come
from a rebuildable ORM index (`ArticleIndex`, `./manage.py content_index
[--rebuild]`); bodies are always read from the files. Git backend first run:
`./manage.py content_clone`; health: `./manage.py content_status [--fetch]
[--check] [--json]`. Design, API and
limitations: `docs/content-repository.md`. Tests use temporary directories:

```
./manage.py test app.content
```

The editor UI is `app/static/content/article-editor.js` (`mount(element,
context)`): mounted natively in `/admin-react/` through django-admin-react's
`CUSTOM_PAGES` when the installed fork supports it, otherwise served by
`app/content/editor.py` at the same URL.

Never point tests or experiments at the real `content/`; set
`CONTENT_REPOSITORY_ROOT` to a copy.

## Linting

Run all hooks over the whole tree:

```
prek -a
```

Hooks fix most things themselves; stage the result and run again. Ruff is
configured in `pyproject.toml` (`RUF012` and `E501` are ignored on purpose).
`prek` is listed in `requirements/development.txt`.

## Running the project

The example project's only test suite is `app.content` (plus the
filecontent package, see above). Verify changes by running the app:

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
