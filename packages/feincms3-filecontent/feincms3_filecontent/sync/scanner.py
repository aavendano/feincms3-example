class Scanner:
    """Enumerates the documents of a ContentStore that a parser can handle."""

    def __init__(self, store, registry):
        self.store = store
        self.registry = registry

    def is_document(self, path):
        if not self.registry.supports(path):
            return False
        parts = path.split("/")
        if parts[0] in self.store.exclude:
            return False
        return not any(part.startswith(".") for part in parts)

    def paths(self, prefix=""):
        return [
            path
            for path in self.store.list(prefix, suffixes=self.registry.suffixes)
            if self.is_document(path)
        ]
