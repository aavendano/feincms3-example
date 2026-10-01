"""
ContentStore contract: the only component allowed to touch document files.

Paths are always POSIX-style strings relative to the content root
(``"en/about.md"``). Implementations must reject anything that would resolve
outside the root.
"""

import abc
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class FileStat:
    path: str
    size: int
    modified_at: datetime
    # Nanosecond mtime, cheap cache key for parsed documents.
    mtime_ns: int


class ContentStore(abc.ABC):
    read_only = False

    @abc.abstractmethod
    def read(self, path) -> str: ...

    @abc.abstractmethod
    def read_bytes(self, path) -> bytes: ...

    @abc.abstractmethod
    def write(self, path, content, *, create=True, overwrite=True) -> FileStat: ...

    @abc.abstractmethod
    def delete(self, path) -> None: ...

    @abc.abstractmethod
    def move(self, source, destination) -> FileStat: ...

    @abc.abstractmethod
    def exists(self, path) -> bool: ...

    @abc.abstractmethod
    def list(self, prefix="", *, suffixes=None) -> list[str]: ...

    @abc.abstractmethod
    def stat(self, path) -> FileStat: ...
