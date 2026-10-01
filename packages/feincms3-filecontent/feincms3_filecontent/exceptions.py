"""
Explicit error hierarchy. Every failure mode surfaces as its own type so
callers (admin views, management commands, monitoring) can react to it
instead of guessing from a message string.
"""


class FileContentError(Exception):
    """Base class for all feincms3-filecontent errors."""


class ConfigurationError(FileContentError):
    """The ``FILECONTENT`` setting is missing or invalid."""


# Storage --------------------------------------------------------------------


class StorageError(FileContentError):
    pass


class UnsafePathError(StorageError):
    """A path escapes the content root (path traversal, symlinks, ``.git``)."""


class DocumentNotFound(StorageError):
    pass


class DocumentExists(StorageError):
    pass


class ReadOnlyError(StorageError):
    """A write was attempted while the store or repository is read-only."""


# Content --------------------------------------------------------------------


class DocumentError(FileContentError):
    pass


class UnsupportedDocumentType(DocumentError):
    pass


class DocumentValidationError(DocumentError):
    def __init__(self, errors, path=None):
        self.errors = list(errors)
        self.path = path
        prefix = f"{path}: " if path else ""
        super().__init__(prefix + "; ".join(self.errors))


# Repository -----------------------------------------------------------------


class RepositoryError(FileContentError):
    pass


class NotARepository(RepositoryError):
    pass


class GitCommandError(RepositoryError):
    def __init__(self, args, returncode, stdout="", stderr=""):
        self.args_ = list(args)
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(
            f"git {' '.join(self.args_)} failed with exit code {returncode}: "
            f"{(stderr or stdout).strip()}"
        )


class RepositoryLocked(RepositoryError):
    """Another process holds the repository write lock."""


class ConflictError(RepositoryError):
    """
    Base class for conflicts. Conflicts are never resolved silently; they are
    raised with enough detail for a human to decide.
    """

    def __init__(self, message, paths=()):
        self.paths = sorted(paths)
        if self.paths:
            message = f"{message} ({', '.join(self.paths)})"
        super().__init__(message)


class DirtyWorkingTree(ConflictError):
    pass


class DivergedError(ConflictError):
    pass


class MergeConflict(ConflictError):
    pass


class PushRejected(ConflictError):
    pass


class StaleDocumentError(ConflictError):
    """The document changed since the editor loaded it (concurrent edit)."""


# Providers ------------------------------------------------------------------


class ProviderError(FileContentError):
    pass
