# Content Repository (POC) — artículos filesystem-first

Estado: **prueba de concepto, sólo `Article`**. Git **todavía no está
implementado** en este repositorio de contenido. El modelo ORM `Article`,
`Page` y el sistema de plugins de feincms3 siguen intactos y funcionando.

## Arquitectura actual

```text
React Admin  (/admin-react/content/articles/)
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

Errores: `400 {"errors": {campo: [...]}}`, `401`, `403`, `404`, `409`.
Se reutilizan los permisos del modelo `Article` para no crear filas de
permisos (que exigirían una migración).

### ¿Por qué el editor no es una ruta nativa de la SPA?

django-admin-react pinta lo que expone la REST API a partir de los
`ModelAdmin`. No tiene un punto de extensión para recursos que no son
modelos: su único hook, las *custom views* de `get_urls()`, enlaza a la
página legacy en otra pestaña. Las alternativas eran:

1. Un modelo falso o *proxy* para colgarse del registry → genera migraciones
   y obliga a emular un QuerySet. Descartado.
2. Una ruta nueva dentro del fork de la SPA → cambio en otro repositorio,
   con su build. Es el siguiente paso natural (ver más abajo).
3. **Elegida para el POC:** una página servida bajo `/admin-react/content/articles/`
   (antes del catch-all de la SPA). Comparte sesión, cookie CSRF y login
   staff, y sólo habla con `/api/content/`. Es JavaScript sin dependencias ni
   build.

La API ya tiene la forma que necesitaría una ruta nativa de la SPA, así que
migrar el editor allí no toca el backend.

## Arquitectura futura

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
Filesystem   Git   ← NO implementado todavía
```

`GitArticleRepository` (o un `FilesystemArticleRepository` envuelto en un
working tree Git) añadiría `clone`, `pull/fetch`, `branch`, `commit`,
`history`, `diff`, `merge` y `push`. El contrato ya lo prepara:

* `ContentRepository.history/diff/commit` existen y hoy lanzan
  `OperationNotSupported`; `capabilities` anuncia qué soporta cada backend.
* Toda escritura recibe un `ChangeContext` (autor, mensaje) que hoy se ignora
  y mañana será el autor y el mensaje del commit.
* `version` es un hash de contenido: un backend Git puede mantener la misma
  semántica de bloqueo optimista.
* Las identidades son rutas estables, legibles y sin IDs de base de datos:
  diffs y merges de Git se entienden sin el ORM.
* `packages/feincms3-filecontent` ya contiene una capa Git explícita
  (estados, sync incremental, rollback no destructivo) que puede convertirse
  en ese backend.

## ORM vs filesystem (lo que demuestra el POC)

| Aspecto | `Article` ORM | Artículo filesystem |
| --- | --- | --- |
| Autoridad | Tabla `articles_article` | `content/…/*.md` |
| Crear contenido | Fila en BD | Archivo (también a mano o por PR) |
| Migraciones al cambiar el schema | Sí | No (schema en código; documentos validados al leer) |
| Market / locale | No modelado | Parte de la identidad (ruta) |
| Diff / revisión legible | No | Sí (texto plano; Git después) |
| Consultas complejas, joins, paginación de BD | Sí | Lineal sobre archivos; requiere índice para escalar |
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
```

Para no tocar `content/` del repositorio al experimentar, usa
`CONTENT_REPOSITORY_ROOT=/tmp/content ./manage.py runserver` con una copia.
