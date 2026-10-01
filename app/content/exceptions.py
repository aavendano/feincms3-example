# ruff: noqa: N818 - DocumentNotFound / VersionConflict read better without "Error".


class ContentError(Exception):
    """Base class for content repository errors."""


class InvalidDocument(ContentError):
    """Validation failed; ``errors`` maps field names to messages."""

    def __init__(self, errors):
        self.errors = {key: list(messages) for key, messages in errors.items()}
        super().__init__(
            "; ".join(f"{k}: {' '.join(v)}" for k, v in self.errors.items())
        )


class InvalidPath(InvalidDocument):
    """A key or path would escape the content root."""


class DocumentNotFound(ContentError):
    pass


class DocumentAlreadyExists(ContentError):
    pass


class VersionConflict(ContentError):
    """The document changed since the client read it (optimistic locking)."""

    def __init__(self, current_version):
        self.current_version = current_version
        super().__init__("The document was changed by someone else.")


class OperationNotSupported(ContentError):
    """The backend does not implement this capability (e.g. history)."""
