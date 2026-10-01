# feincms3-filecontent

Aplicación Django reutilizable con la que feincms3 estructura y sirve
contenido editorial guardado en archivos planos (Markdown + Front Matter). Un
repositorio Git externo es la autoridad persistente y el sistema de versionado.

```text
Remote Git Repository
  ↓ clone/fetch/pull/push
GitRepository                 repository/
  ↓
Local Working Tree            FILECONTENT["ROOT"]
  ↓
ContentStore                  storage/        (lectura/escritura segura y atómica)
  ├─ Document → FileContent → feincms3         content/, feincms/
  └─ SyncEngine → ContentIndex → feincms3      sync/, models.py
```

## Principios

| Capa | Rol |
| --- | --- |
| Repositorio Git remoto | Autoridad persistente y versionada |
| Working tree local | Copia operacional |
| `ContentStore` | Única pieza que lee y escribe archivos |
| `ContentIndex` (BD) | Proyección **reconstruible**; se puede borrar y regenerar |
| feincms3 | Árbol de páginas, routing, regiones, templates y composición |

* Git **no** participa en el hot path HTTP: el render sólo lee el filesystem
  (con caché en proceso invalidada por `mtime`/tamaño).
* feincms3 no ejecuta Git; el plugin `FileContent` sólo guarda `content_path`.
* Los conflictos **nunca** se resuelven en silencio: se lanzan como excepciones
  tipadas que nombran los archivos afectados.

## Instalación

```python
INSTALLED_APPS = [
    ...,
    "feincms3",
    "content_editor",
    "feincms3_filecontent",
]

FILECONTENT = {
    "ROOT": BASE_DIR / "content",  # working tree local
    "REMOTE_URL": os.environ.get(
        "FILECONTENT_REMOTE_URL"
    ),  # SSH o HTTPS sin credenciales
    "BRANCH": "main",
}
```

```bash
./manage.py migrate
./manage.py filecontent_sync      # clona si falta, fast-forward, indexa
```

Integración en el modelo de páginas del proyecto:

```python
# pages/models.py
from feincms3_filecontent.feincms.models import FileContent as AbstractFileContent


class FileContent(AbstractFileContent, PagePlugin):
    pass


# pages/renderer.py
from feincms3_filecontent.feincms.renderer import render_filecontent

renderer.register(models.FileContent, render_filecontent)

# pages/admin.py
from feincms3_filecontent.feincms.plugins import FileContentInline

inlines = [..., FileContentInline.create(model=models.FileContent)]
```

El HTML se renderiza con `feincms3_filecontent/plugins/filecontent.html`
(`document`, `html`, `plugin` en el contexto); sobrescríbelo en el proyecto
para mostrar título, fecha, etc.

## Documentos

```markdown
---
title: Sobre nosotros
slug: sobre-nosotros        # opcional; por defecto el nombre del archivo
locale: es                  # opcional; también "es/about.md" o "about.es.md"
modified_at: 2026-09-30     # opcional; si no, mtime del archivo
---

# Sobre nosotros
...
```

`Document` normaliza: `path, content_type, locale, slug, title, metadata,
body, content_hash, modified_at`. Otros formatos se añaden registrando un
parser (subclase de `DocumentParser`) por extensión en `FILECONTENT["PARSERS"]`.

La validación (`DocumentValidator`) comprueba ruta segura, tipo soportado,
tamaño, UTF-8, YAML válido, campos obligatorios (`REQUIRED_FIELDS`), formato
del slug, locale conocido (`settings.LANGUAGES`) y que el parser pueda
renderizar. Devuelve **todos** los errores a la vez.

## Escritura (modo directo)

```python
from feincms3_filecontent.workflow.commits import ContentWriter, author_for

result = ContentWriter.default().save(
    "about.md",
    text,
    message="Actualiza Sobre nosotros",
    author=author_for(request.user),
    expected_hash=hash_cargado_por_el_editor,  # detecta edición concurrente
)
result.sha, result.pushed, result.push_error, result.sync
```

Secuencia: *validar → lock → comprobar estado → escritura atómica → `git add`
→ commit (sólo esas rutas) → sync incremental del índice → push*.

* Cualquier fallo **antes** del commit restaura el archivo y el índice de Git.
* Después del commit el cambio es durable; un push rechazado se devuelve en
  `result.push_error` y el repo queda en `AHEAD`/`DIVERGED`, sin merges
  automáticos.
* `ContentWriter.synchronize()` reconcilia explícitamente: fast-forward si
  `BEHIND`, push si `AHEAD`, y si `DIVERGED` hace rebase **sólo** cuando ningún
  archivo fue tocado en ambos lados (`CONFLICT_POLICY="strict"`, por defecto).
  Si no, lanza `DivergedError(paths)` sin tocar nada.

También: `delete()`, `move()`.

## Modo review (branches + pull requests)

```python
from feincms3_filecontent.workflow.proposals import propose_change, merge_proposal

proposal = propose_change("about.md", text, message="Nueva versión de About")
proposal.branch  # "content/update-about"
proposal.pull_request  # si hay GitProvider configurado
```

La rama se prepara en un `git worktree` temporal (`WORKTREES_DIR`), así el
working tree servido nunca cambia de rama. Convenciones de nombres:
`content_branch("update", "about")`, `translation_branch("fr", "article", 123)`.

## Historial y rollback

```python
from feincms3_filecontent.workflow import rollback

rollback.history("about.md")  # [HistoryEntry(sha, author, date, subject…)]
rollback.version_diff("about.md", sha)  # patch de ese commit
rollback.restore("about.md", sha)  # NUEVO commit con el contenido antiguo
```

Nunca se hace `reset` ni `push --force`.

## Sincronización incremental

`RepositoryState` guarda `branch`, `last_indexed_sha` e `indexed_at`. Entre
ese SHA y `HEAD`, Git entrega added/modified/deleted/renamed y sólo esos
documentos se reprocesan. Hay rebuild completo cuando no hay estado previo, el
SHA ya no existe (force-push, otro clon) o se pide explícitamente. Sin
repositorio Git (directorio plano, despliegues read-only) cada sync es un
rebuild. Los documentos inválidos se indexan con `status="invalid"` y su error.

## Comandos

| Comando | Qué hace |
| --- | --- |
| `filecontent_sync [--no-fetch] [--no-push] [--full]` | Clona si falta, fetch + fast-forward/rebase seguro, push pendiente, sync incremental |
| `filecontent_rebuild` | Borra y reconstruye `ContentIndex` completo |
| `filecontent_repository_status [--json] [--fetch]` | Estado (`CLEAN/DIRTY/AHEAD/BEHIND/DIVERGED/CONFLICTED`), SHA, índice |
| `filecontent_check [--fix] [--abort-operation]` | Configuración, temporales huérfanos, merges a medias, valida todos los documentos |
| `filecontent_history PATH [--diff SHA]` | Historial de un documento |
| `filecontent_rollback PATH SHA [--author "N <e>"]` | Restaura una versión con un commit nuevo |

Códigos de salida: `2` error, `3` conflicto.

## Admin

*Documents* (`ContentIndex`) es de sólo lectura y muestra el estado del
repositorio. Desde ahí: editor (validar y commitear o proponer en rama),
historial con diff y *Restaurar esta versión*, botones *Sync* y *Rebuild*.
Permisos: `feincms3_filecontent.edit_document` y
`feincms3_filecontent.manage_repository`.

## Proveedores (opcional)

```python
FILECONTENT["PROVIDER"] = {
    "CLASS": "feincms3_filecontent.providers.github.GitHubProvider",
    "OPTIONS": {"repository": "owner/name", "token_env": "GITHUB_TOKEN"},
}
```

`GitHubProvider`, `GitLabProvider` (`project=`), `BitbucketProvider`:
crear/buscar/consultar/mergear PRs y estado de CI. El núcleo sólo necesita Git.

## Seguridad

* Protección contra path traversal: rutas absolutas, `..`, backslashes, NUL,
  symlinks que salen del root, `.git` y nombres ocultos se rechazan.
* Credenciales fuera de documentos y commits: Git usa SSH/credential helper,
  los tokens de proveedores se leen de variables de entorno, las URLs con
  credenciales se redactan en errores y generan el warning
  `feincms3_filecontent.W001`.
* Git se ejecuta sin prompts (`GIT_TERMINAL_PROMPT=0`, `BatchMode=yes`) y con
  timeout.
* El HTML de Markdown se considera contenido editorial de confianza; para
  sanearlo, configura `SANITIZER` (p. ej. un wrapper de `nh3.clean`).

## Concurrencia

Todas las mutaciones (working tree, índice Git, `ContentIndex`) se serializan
con un `flock` en el directorio Git común (`filecontent.lock`), re-entrante
por hilo y compartido entre procesos del mismo host. Las lecturas HTTP no
toman el lock: la sustitución atómica de archivos les basta. Con varios hosts,
cada uno tiene su working tree y se coordinan a través del remoto (push
rechazado → `synchronize()`).

## Configuración

| Clave | Por defecto |
| --- | --- |
| `ROOT` | — (obligatoria) |
| `REMOTE_URL`, `REMOTE_NAME`, `BRANCH` | `None`, `"origin"`, `"main"` |
| `READ_ONLY` | `False` |
| `AUTO_PUSH` | `True` |
| `COMMIT_AUTHOR_NAME/EMAIL` | identidad del committer y autor por defecto |
| `WORKTREES_DIR` | `<ROOT>.worktrees` (debe estar fuera de `ROOT`) |
| `PARSERS` | `.md`, `.markdown` → `MarkdownParser` |
| `MARKDOWN_EXTENSIONS(_CONFIGS)` | `extra`, `sane_lists`, `toc` |
| `SANITIZER` | `None` |
| `REQUIRED_FIELDS` | `["title"]` |
| `MAX_DOCUMENT_SIZE` | 1 MiB |
| `EXCLUDE` | `.git`, `.github`, `.gitlab`, `node_modules` |
| `CONFLICT_POLICY` | `"strict"` (o `"git"`) |
| `GIT_BINARY`, `GIT_TIMEOUT`, `LOCK_TIMEOUT` | `"git"`, 120 s, 30 s |
| `PROVIDER` | `None` |
| `SHOW_ERRORS` | `settings.DEBUG` |

## Tests

Se ejecutan contra repositorios Git locales (un repo *bare* hace de remoto),
sin red ni proveedor:

```bash
cd packages/feincms3-filecontent
pip install -e '.[tests]'
pytest
```

## Limitaciones conocidas (MVP)

* `restore()` sobre un commit anterior a un rename falla con
  `DocumentNotFound` (la ruta histórica era otra).
* El lock usa `fcntl`: POSIX únicamente.
* `ContentIndex.git_sha` es el commit en el que se indexó, no el último commit
  que tocó el archivo (usa `history()` para eso).
