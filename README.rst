========================
feincms3 example project
========================

Clone this repository::

    git clone https://github.com/matthiask/feincms3-example/
    cd feincms3-example

Setup a virtualenv and install **development** dependencies::

    python3 -m venv venv
    . venv/bin/activate
    pip install -r requirements/development.txt
    scripts/install-admin-react.sh --editable   # builds the SPA bundle

``requirements.txt`` is an alias for the development set. For a production-style
install (example stack: gunicorn, Postgres driver, whitenoise)::

    pip install -r requirements/production.txt
    scripts/install-admin-react.sh              # clone fork, build SPA, install

Settings live under ``app/settings/``:

- ``app.settings.development`` — default for ``./manage.py`` (DEBUG, SQLite)
- ``app.settings.production`` — example deploy template (default for ``app.wsgi``);
  set ``DJANGO_SECRET_KEY`` and adapt hosts / database before use

Override the settings module when needed::

    DJANGO_SETTINGS_MODULE=app.settings.production ./manage.py check

Maybe adapt the database connection in ``app/settings/development.py`` (or the
production template) if you don’t want the defaults.

Run migrations and create a superuser::

    ./manage.py migrate
    ./manage.py createsuperuser

Import the fixtures::

    ./manage.py loaddata fixtures/pages.json
    ./manage.py loaddata fixtures/articles.json

Start the runserver::

    ./manage.py runserver

Open ``http://127.0.0.1:8000/`` and ``http://127.0.0.1:8000/admin/`` and
dive in!

Markdown content from Git (feincms3-filecontent)
================================================

``packages/feincms3-filecontent`` is a reusable app that lets pages render
Markdown documents stored in a Git repository (see its ``README.md``). The
example wires it as the *file content* plugin. To try it with a throwaway local
"remote" built from ``fixtures/content``::

    git init --bare -b main /tmp/content.git
    git clone /tmp/content.git /tmp/content-seed
    cp -r fixtures/content/. /tmp/content-seed/
    git -C /tmp/content-seed add -A
    git -C /tmp/content-seed commit -m "Sample content"
    git -C /tmp/content-seed push origin main

    export FILECONTENT_REMOTE_URL=/tmp/content.git
    ./manage.py filecontent_sync   # clones into ./filecontent and indexes it

Then add a *file content* plugin to a page and pick ``about.md``. Documents
can be edited, committed, reviewed on branches and restored from history in
the admin under *File content › Documents*.

Filesystem articles (proof of concept)
======================================

``app/content`` stores articles as Markdown files in
``content/{MARKET}/{locale}/articles/{slug}.md`` — no database rows. Edit
them at ``http://127.0.0.1:8000/admin-react/content/articles/`` and view
published ones at ``http://127.0.0.1:8000/content/ca/en/articles/``. Tests:
``./manage.py test app.content``. Set ``CONTENT_REPOSITORY_BACKEND=git``
(with a root that is its own Git working tree) for one commit per edit,
history and restore; see ``docs/content-repository.md``.

The React admin SPA is at ``http://127.0.0.1:8000/admin-react/`` (same
staff login). In development it is installed editable from the sibling
checkout ``../django-admin-react``; production builds and installs the
fork's ``main`` branch. The SPA bundle is not committed in the fork, so a
plain ``pip install git+…`` leaves it out (``django_admin_react.W002``);
``scripts/install-admin-react.sh`` runs the Vite build first. It needs node
>= 20 and pnpm (``corepack enable``).
