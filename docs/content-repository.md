# Content Repository (POC) — artículos filesystem-first

Estado: **prueba de concepto, sólo `Article`**. Hay dos backends: `filesystem`
(por defecto) y `git` (un commit por cambio, historial, diff y restore). El
modelo ORM `Article`, `Page` y el sistema de plugins de feincms3 siguen
intactos y funcionando.

Decisión de arquitectura (opción 3): este repositorio de contenido es el
modelo público (interfaz, schema por tipo, identidad por ruta, API JSON) y la
maquinaria de `packages/feincms3-filecontent` es su implementación interna
(Git, conflictos, lock; más adelante, el índice). El plugin `FileContent` del
paquete queda sólo como puente mientras `Page` siga en el ORM.

## Arquitectura actual

```text
React Admin  (/admin-react/content/articles/, ruta nativa vía CUSTOM_PAGES)
     │  fetch + cookie de sesión + X-CSRFToken
     ▼
Django API   (/api/content/…)              app/content/api.py
     │
     ▼
ContentRepository (interfaz)               app/content/repository.py
     │
     ▼
FilesystemArticleRepository                app/content/filesystem.py
     │
     ▼
content/{MARKET}/{locale}/articles/{slug}.md
```

Lectura pública:

```text
content/CA/en/articles/x.md → repository → app/content/views.py
    → RegionRenderer (feincms3) → templates/content/article_detail.html → HTML
```

| Pieza | Archivo | Responsabilidad |
| --- | --- | --- |
| Schema | `app/content/schemas.py` | Campos, validación, `serialize()` / `parse()` (Markdown + YAML front matter) |
| Interfaz | `app/content/repository.py` | `list/get/exists/create/update/delete` (+ `history/diff/commit/move` reservados) |
| Backend | `app/content/filesystem.py` | Rutas, lectura, escritura atómica, locking |
| API | `app/content/api.py` | JSON para el editor; auth, CSRF y permisos de Django |
| Editor | `app/content/editor.py`, `templates/content/editor.html` | UI editorial bajo `/admin-react/` |
| Público | `app/content/views.py`, `rendering.py` | Listado y detalle de artículos publicados |

### Documento

```markdown
---
title: Filesystem-first content
status: published            # draft | published
publication_date: '2026-09-15T09:00:00Z'
category: blog               # blog | publications
---

Cuerpo en **Markdown**.
```

* `market`, `locale` y `slug` **no** se guardan en el archivo: salen de la ruta
  `content/{MARKET}/{locale}/articles/{slug}.md`. Si un archivo trae `slug`,
  debe coincidir con el nombre; `market`/`locale` en el front matter son un
  error. Así un archivo no puede contradecir su ubicación.
* Identidad estable: `MARKET/locale/slug` (p. ej. `CA/en/filesystem-first`).
  El navegador sólo ve esa identidad, nunca rutas del disco.
* `version` = SHA-256 del archivo leído. `PUT` y `DELETE` la reciben
  (`version` / `If-Match`) para detectar ediciones concurrentes (HTTP 409).
* Publicado = `status: published` y `publication_date <= ahora`.

### Escritura segura

`create`/`update`/`delete` toman un lock de proceso (`flock` en
`content/.content.lock`). La escritura serializa el artículo, lo vuelve a
parsear como validación, lo escribe en un temporal del mismo directorio,
hace `fsync` y lo renombra de forma atómica. Un fallo deja el archivo
anterior intacto. Mover (cambiar market/locale/slug) escribe primero el
destino y luego borra el origen: un fallo intermedio deja un duplicado
visible, nunca una pérdida.

Las rutas se validan dos veces: formato de `market`/`locale`/`slug` (sólo los
mercados/locales de `settings.CONTENT_REPOSITORY["MARKETS"]`), y resolución
real dentro de `content/` (rechaza `..`, rutas absolutas y symlinks que
salgan del root). Las primitivas de bajo nivel (`FileSystemContentStore`,
`RepositoryLock`, `split_front_matter`) se reutilizan de
`packages/feincms3-filecontent`.

### API

| Método | URL | Permiso |
| --- | --- | --- |
| GET | `/api/content/meta/` | `articles.view_article` |
| GET | `/api/content/articles/?market=&locale=&category=&status=&order=` | `articles.view_article` |
| POST | `/api/content/articles/` | `articles.add_article` |
| GET | `/api/content/articles/<MARKET>/<locale>/<slug>/` | `articles.view_article` |
| PUT | ídem (puede mover) | `articles.change_article` |
| DELETE | ídem (`If-Match: <version>`) | `articles.delete_article` |
| GET | `…/<slug>/history/` | `articles.view_article` |
| GET | `…/<slug>/diff/?version=<sha>[&to=<sha>]` | `articles.view_article` |
| POST | `…/<slug>/restore/` `{"version", "expected_version"}` | `articles.change_article` |
| GET | `/api/content/repository/` | `articles.view_article` |
| POST | `/api/content/repository/sync/` | `articles.change_article` |

Las escrituras con el backend `git` devuelven además
`"commit": {"sha", "pushed", "push_error"}`.

Errores: `400 {"errors": {campo: [...]}}`, `401`, `403`, `404`, `409`
(versión obsoleta, o conflicto de repositorio con `"paths"`), `501`
(operación que el backend no soporta) y `503` (repositorio Git no disponible).
Se reutilizan los permisos del modelo `Article` para no crear filas de
permisos (que exigirían una migración).

### El editor dentro de la SPA (`CUSTOM_PAGES`)

django-admin-react pinta lo que expone la REST API a partir de los
`ModelAdmin`; no tenía punto de extensión para recursos que no son modelos.
El fork (`aavendano/django-admin-react`, rama `ccr-16241950-g2o8f6`) añade
uno **genérico**: `DJANGO_ADMIN_REACT["CUSTOM_PAGES"]`. Cada entrada es un
enlace en el sidebar + una ruta del cliente cuyo contenido es un módulo ES
del proyecto (`mount(element, context)`). El paquete no aprende nada de
artículos: no añade endpoints ni permisos, sólo hospeda el módulo.

* El editor vive en `app/static/content/article-editor.js` (un único
  código; estilos y markup acotados bajo `.fse`).
* `app/settings/base.py` lo registra en `CUSTOM_PAGES` (grupo *Content*,
  permiso `articles.view_article`) **sólo si** el django-admin-react
  instalado lo soporta (`find_spec("django_admin_react.custom_pages")`).
* Si no lo soporta (por ejemplo, `main` del fork antes de fusionar la rama),
  `app/urls.py` sirve el mismo módulo en una página independiente en la
  misma URL, `/admin-react/content/articles/`. Ningún modo rompe al otro.

Para usar la ruta nativa hasta que la rama del fork se fusione:

```bash
DJANGO_ADMIN_REACT_REF=ccr-16241950-g2o8f6 scripts/install-admin-react.sh
```

## Backend Git

```text
React Admin
      │
      ▼
Django API
      │
      ▼
Content Repository
      │
┌─────┴──────┐
▼            ▼
Filesystem   Git   (app/content/git.py)
             └── feincms3_filecontent.repository (git CLI, estados, conflictos, lock)
```

`GitArticleRepository` extiende el backend filesystem; las lecturas son
idénticas y **Git nunca corre en lectura**. Cada `create`/`update`/`delete`
(y `restore`) es exactamente un commit:

* autor = el usuario de Django (`ChangeContext`), committer = identidad del
  sistema (`GIT.COMMITTER_NAME/EMAIL`); mensaje generado o el del contexto;
* sólo se commitean las rutas tocadas; mover es un único commit con rename;
* si algo falla antes del commit, archivos e índice de Git vuelven a su
  estado previo;
* un cambio sin confirmar hecho a mano en esa ruta bloquea la escritura
  (`409` con `paths`), nunca se mezcla en silencio; `commit()` permite
  confirmarlo de forma explícita;
* con `AUTO_PUSH` se hace push tras cada commit. Si el push es rechazado, el
  commit queda local (estado `AHEAD`/`DIVERGED`) y la respuesta lo dice
  (`commit.push_error`);
* `sync()` hace fetch + fast-forward + push. Si las historias divergen lanza
  `DivergedError` con las rutas tocadas en ambos lados y no cambia nada:
  reconciliar es una decisión humana;
* `history()`, `diff()` y `restore()` trabajan por artículo; `restore()` crea
  un commit nuevo (también recrea artículos borrados). Nunca se reescribe la
  historia.

Configuración:

```python
CONTENT_REPOSITORY = {
    "BACKEND": "git",
    "ROOT": "/srv/content",  # raíz de SU PROPIO working tree Git
    "MARKETS": {"CA": ["en", "fr"], "US": ["en", "es"]},
    "GIT": {"BRANCH": "main", "AUTO_PUSH": True},
}
```

`ROOT` debe ser la raíz de un working tree propio: si es un subdirectorio de
otro repositorio (por ejemplo `content/` dentro de este proyecto) las
escrituras se rechazan con un error explícito. Por eso el ejemplo usa
`filesystem` por defecto. Para probar Git:

```bash
git init --bare -b main /tmp/content.git
git clone /tmp/content.git /tmp/content
cp -r content/. /tmp/content/ && git -C /tmp/content add -A \
  && git -C /tmp/content commit -m "Import articles" && git -C /tmp/content push origin main
CONTENT_REPOSITORY_BACKEND=git CONTENT_REPOSITORY_ROOT=/tmp/content ./manage.py runserver
```

El editor muestra entonces el estado del repositorio (rama, `clean`/`ahead`/…),
el historial con diffs, "Restore" por versión y "Sync with remote".

## Índice (proyección reconstruible)

```text
archivos (fuente de verdad) ──sync──▶ ArticleIndex (ORM, app/content/models.py)
                                          │
IndexedArticleRepository.list()/count() ◀─┘     get()/escrituras ──▶ backend (archivos)
```

`get_article_repository()` envuelve el backend en `IndexedArticleRepository`
(`app/content/index.py`) salvo que `CONTENT_REPOSITORY["INDEX"]` sea `False`.

* **`list()` / `count()`** consultan `ArticleIndex`: filtros por market,
  locale, categoría y estado, "publicado ahora", orden por fecha y paginación
  (`limit`/`offset`) en SQL, sin leer archivos (2 consultas). Devuelven
  `ArticleSummary` (sin `body`).
* **`get()`** sigue leyendo el archivo: el cuerpo nunca sale del índice.
* **Escrituras** (create/update/delete/move/restore/commit) actualizan las
  filas afectadas dentro del lock de escritura, releyendo el archivo escrito.
  En modo Git, si no había nada pendiente, `last_indexed_sha` avanza al nuevo
  commit y el índice sigue `current`.
* **Sincronización incremental**:
  * Git: archivos cambiados entre `last_indexed_sha` y `HEAD` (añadidos,
    modificados, borrados, renombrados), con el planificador de
    `feincms3_filecontent.sync`. Si el commit previo ya no existe (historia
    reescrita) o cambió el root: rebuild completo.
  * Filesystem: compara `mtime`/tamaño guardados y sólo reprocesa lo que
    cambió.
* **Cuándo se sincroniza**: escrituras por el repositorio (inmediato),
  `POST /api/content/repository/sync/` (botón *Sync with remote* / *Reindex*
  del editor), `./manage.py content_index [--rebuild|--status]`, y el primer
  listado con el índice vacío. Los cambios hechos por fuera (`git pull` a
  mano, edición directa de archivos) aparecen tras la siguiente sincronización.
* **Archivos inválidos** se indexan con su error, nunca se listan y se
  informan en `/api/content/meta/` (`invalid_documents`).
* **Desechable**: borrar `ArticleIndex` e `IndexState` y volver a listar
  produce el mismo resultado. Es dato operacional, no contenido (por eso sí
  tiene migración: `content.0001_initial`).

No se reutilizó la tabla `ContentIndex` del paquete: no distingue entre
roots de contenido y guarda los campos en JSON. Un índice tipado por tipo de
contenido permite filtrar y ordenar con índices de base de datos. El *patrón*
(proyección + estado + sync incremental por diff) sí es el del paquete.

## Primer arranque y estado

```bash
export CONTENT_REPOSITORY_BACKEND=git
export CONTENT_REPOSITORY_ROOT=/srv/content
export CONTENT_REPOSITORY_REMOTE_URL=git@github.com:org/content.git

./manage.py content_clone            # clona en ROOT y construye el índice
./manage.py content_status           # estado legible
./manage.py content_status --fetch --check   # para monitorización: exit 1 si algo requiere atención
./manage.py content_status --json    # salida para máquinas
```

* `content_clone` es idempotente: si `ROOT` ya es un clon del mismo remoto no
  hace nada; si es un clon de *otro* remoto, o un directorio no vacío que no es
  un working tree, se niega (nunca sobrescribe contenido). Avisa si la URL lleva
  credenciales y nunca las imprime.
* `content_status` muestra backend, remoto (sin credenciales), estado
  (`CLEAN/DIRTY/AHEAD/BEHIND/DIVERGED/CONFLICTED`), rama, HEAD, ahead/behind,
  archivos modificados/sin seguimiento/en conflicto, problemas y el estado del
  índice (`current`/`stale`/`missing`). `--check` falla si el repositorio no
  está limpio o el índice no está al día.

### Pendiente (siguientes pasos de la opción 3)

* **Ramas de revisión / pull requests** para artículos (el paquete ya tiene
  worktrees y proveedores GitHub/GitLab/Bitbucket).
* Retirar `FileContent` cuando `Page` pase al ComponentRegistry.

## ORM vs filesystem (lo que demuestra el POC)

| Aspecto | `Article` ORM | Artículo filesystem |
| --- | --- | --- |
| Autoridad | Tabla `articles_article` | `content/…/*.md` |
| Crear contenido | Fila en BD | Archivo (también a mano o por PR) |
| Migraciones al cambiar el schema | Sí | No (schema en código; documentos validados al leer) |
| Market / locale | No modelado | Parte de la identidad (ruta) |
| Diff / revisión legible | No | Sí (texto plano; Git después) |
| Consultas, orden, paginación | Sí | Sí, vía `ArticleIndex` (proyección reconstruible) |
| Imágenes (`Image` inline) | Sí | No (pendiente: referencias de media) |
| URLs vía feincms3 apps (`reverse_app`) | Sí | Rutas propias `/content/{market}/{locale}/articles/` |
| Edición concurrente | Último que guarda gana | 409 por versión |

## Propuesta: ComponentRegistry (no implementado)

Hoy cada plugin de página es un modelo Django:

```python
PagePlugin = create_plugin_base(Page)  # FK a Page, region, ordering


class RichText(richtext.RichText, PagePlugin): ...
```

Eso ata el *qué* (el schema del componente) al *dónde* (una tabla con FK a
`Page`). Para un editor visual React y para contenido en archivos, el
componente debe describirse sin el ORM:

```text
ComponentRegistry
    ├── RichText   {html: str}
    ├── Image      {src: MediaRef, alt: str, caption: str}
    ├── Hero       {title: str, image: MediaRef, cta: Link}
    ├── Columns    {columns: [[Component]]}
    └── custom components
```

```python
@registry.component("hero")
@dataclass
class Hero(Component):
    title: str
    image: MediaRef
    cta: Link | None = None
    region: str = "main"
    ordering: int = 0

    schema = {...}  # JSON Schema, para validar y para que React pinte el formulario
```

* **Schema** (JSON Schema): lo consume el editor React para generar formularios
  y lo usa el repositorio para validar documentos.
* **Almacenamiento**: el documento de página guarda una lista de bloques
  (`{"type": "hero", "region": "main", ...}`) en el front matter o en un
  archivo YAML/JSON. El ORM sólo guarda, como mucho, un índice reconstruible.
* **Render**: el POC demuestra que `feincms3.renderer.RegionRenderer` y
  `content_editor.Contents` funcionan con objetos que no son modelos. Sólo
  hace falta un shim de `_meta` (`app/content/rendering.Component`), así que
  templates y renderers existentes pueden reutilizarse.
* **Transición**: los plugins ORM actuales pueden mapearse 1:1 a componentes
  (`RichText.text` → `RichText.html`). Un adaptador `Page → documento` permite
  convivencia mientras se migra.

Esto **no** se ha refactorizado: `PagePlugin`, `RichText`, `Image` y
`FileContent` siguen siendo modelos.

## Cómo probarlo

```bash
./manage.py runserver
# Editor:  http://127.0.0.1:8000/admin-react/content/articles/   (login staff)
# Público: http://127.0.0.1:8000/content/ca/en/articles/
./manage.py test app.content
./manage.py content_index --status   # estado del índice; --rebuild para regenerarlo
```

Para no tocar `content/` del repositorio al experimentar, usa
`CONTENT_REPOSITORY_ROOT=/tmp/content ./manage.py runserver` con una copia
(y `CONTENT_REPOSITORY_BACKEND=git` si esa copia es un working tree Git).
