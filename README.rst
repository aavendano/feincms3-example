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

``requirements.txt`` is an alias for the development set. For a production-style
install (example stack: gunicorn, Postgres driver, whitenoise)::

    pip install -r requirements/production.txt

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

The React admin SPA is at ``http://127.0.0.1:8000/admin-react/`` (same
staff login). In development it is installed editable from the sibling
checkout ``../django-admin-react``; production installs from the GitHub
``main`` branch (see ``requirements/production.txt``).
