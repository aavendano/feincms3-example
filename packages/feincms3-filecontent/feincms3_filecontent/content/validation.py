"""
Validation run before any write and by ``filecontent_check``.

Validation never mutates content; it returns the parsed document or raises
``DocumentValidationError`` with every problem found, not only the first.
"""

import re

from ..exceptions import (
    DocumentValidationError,
    UnsafePathError,
    UnsupportedDocumentType,
)
from ..storage.filesystem import normalize_path
from .parser import known_locales


SLUG_RE = re.compile(r"^[\w-]+$")


class DocumentValidator:
    def __init__(self, registry, conf):
        self.registry = registry
        self.conf = conf

    def validate_path(self, path):
        try:
            path = normalize_path(path)
        except UnsafePathError as exc:
            raise DocumentValidationError([str(exc)], path=path) from exc
        if path.split("/", 1)[0] in self.conf.exclude:
            raise DocumentValidationError(["Path is excluded."], path=path)
        if any(part.startswith(".") for part in path.split("/")):
            raise DocumentValidationError(["Hidden files are not allowed."], path=path)
        if not self.registry.supports(path):
            raise DocumentValidationError(
                [
                    f"Unsupported file type; expected one of {', '.join(self.registry.suffixes)}."
                ],
                path=path,
            )
        return path

    def validate(self, path, text):
        path = self.validate_path(path)
        errors = []
        raw = text.encode("utf-8") if isinstance(text, str) else text
        if len(raw) > self.conf.max_document_size:
            errors.append(
                f"Document is {len(raw)} bytes, the limit is {self.conf.max_document_size}."
            )
        if isinstance(text, bytes):
            try:
                text = text.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise DocumentValidationError(
                    [f"Not valid UTF-8: {exc}"], path=path
                ) from exc
        if "\x00" in text:
            errors.append("Document contains NUL bytes.")

        try:
            parser = self.registry.for_path(path)
            document = parser.parse(path, text)
        except DocumentValidationError as exc:
            raise DocumentValidationError(errors + exc.errors, path=path) from exc
        except UnsupportedDocumentType as exc:
            raise DocumentValidationError([str(exc)], path=path) from exc

        for name in self.conf.required_fields:
            if name not in document.metadata or document.metadata[name] in (None, ""):
                errors.append(f"Front matter field {name!r} is required.")
        if not SLUG_RE.match(document.slug):
            errors.append(
                f"Slug {document.slug!r} may only contain letters, digits, '-' and '_'."
            )
        locales = known_locales()
        if document.locale and locales and document.locale.lower() not in locales:
            errors.append(
                f"Unknown locale {document.locale!r}; expected one of {', '.join(sorted(locales))}."
            )
        errors.extend(parser.check(document))

        if errors:
            raise DocumentValidationError(errors, path=path)
        return document
