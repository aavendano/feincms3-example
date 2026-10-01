import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from ..exceptions import (
    DocumentExists,
    DocumentNotFound,
    ReadOnlyError,
    StorageError,
    UnsafePathError,
)
from .base import ContentStore, FileStat


TEMP_PREFIX = ".filecontent-tmp-"


def normalize_path(path):
    """
    Return a clean relative POSIX path or raise ``UnsafePathError``.

    Rejects absolute paths, drive letters, ``..`` segments, NUL bytes, empty
    segments and backslashes (which would be separators on Windows).
    """
    if not isinstance(path, str) or not path.strip():
        raise UnsafePathError("Empty path.")
    if "\x00" in path or "\\" in path:
        raise UnsafePathError(f"Invalid characters in path: {path!r}")
    pure = PurePosixPath(path)
    if pure.is_absolute() or (len(path) > 1 and path[1] == ":"):
        raise UnsafePathError(f"Absolute paths are not allowed: {path!r}")
    parts = [part for part in pure.parts if part != "."]
    if not parts or any(part == ".." for part in parts):
        raise UnsafePathError(f"Path traversal is not allowed: {path!r}")
    return "/".join(parts)


class FileSystemContentStore(ContentStore):
    """
    ContentStore backed by a directory (normally a Git working tree).

    Writes go to a temporary file in the destination directory, are fsync'ed
    and then atomically renamed into place, so readers never observe a
    partially written document.
    """

    def __init__(self, root, *, read_only=False, exclude=(".git",)):
        self.root = Path(root).resolve()
        self.read_only = read_only
        self.exclude = frozenset(exclude) | {".git"}

    # Path safety ------------------------------------------------------------

    def resolve(self, path):
        """Return the absolute ``Path`` for ``path`` after all safety checks."""
        rel = normalize_path(path)
        if rel.split("/", 1)[0] in self.exclude:
            raise UnsafePathError(f"Path is excluded from the content store: {rel!r}")
        if any(part.startswith(TEMP_PREFIX) for part in rel.split("/")):
            raise UnsafePathError(f"Reserved file name: {rel!r}")
        candidate = self.root / rel
        # Resolve symlinks (also for not-yet-existing files via their parent).
        resolved = candidate.resolve()
        if resolved != self.root and self.root not in resolved.parents:
            raise UnsafePathError(f"Path escapes the content root: {rel!r}")
        return resolved

    def relative(self, absolute):
        return Path(absolute).resolve().relative_to(self.root).as_posix()

    def _check_writable(self):
        if self.read_only:
            raise ReadOnlyError("The content store is read-only.")

    # Reading ----------------------------------------------------------------

    def read_bytes(self, path):
        target = self.resolve(path)
        try:
            return target.read_bytes()
        except FileNotFoundError:
            raise DocumentNotFound(path) from None
        except IsADirectoryError:
            raise DocumentNotFound(path) from None

    def read(self, path):
        data = self.read_bytes(path)
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise StorageError(f"{path} is not valid UTF-8: {exc}") from exc

    def exists(self, path):
        try:
            return self.resolve(path).is_file()
        except UnsafePathError:
            return False

    def stat(self, path):
        target = self.resolve(path)
        try:
            st = target.stat()
        except FileNotFoundError:
            raise DocumentNotFound(path) from None
        return FileStat(
            path=normalize_path(path),
            size=st.st_size,
            modified_at=datetime.fromtimestamp(st.st_mtime, tz=timezone.utc),
            mtime_ns=st.st_mtime_ns,
        )

    def list(self, prefix="", *, suffixes=None):
        base = self.resolve(prefix) if prefix else self.root
        if not base.is_dir():
            return []
        suffixes = tuple(suffixes) if suffixes else None
        found = []
        for dirpath, dirnames, filenames in os.walk(base):
            current = Path(dirpath)
            rel_dir = "" if current == self.root else self.relative(current)
            # Prune excluded and hidden directories in place.
            dirnames[:] = sorted(
                d
                for d in dirnames
                if not d.startswith(".")
                and not (rel_dir == "" and d in self.exclude)
                and not (current / d).is_symlink()
            )
            for name in sorted(filenames):
                if name.startswith("."):
                    continue
                if suffixes and not name.endswith(suffixes):
                    continue
                rel = f"{rel_dir}/{name}".lstrip("/")
                if (current / name).is_symlink():
                    # Only follow symlinks that stay inside the root.
                    try:
                        self.resolve(rel)
                    except UnsafePathError:
                        continue
                found.append(rel)
        return found

    # Writing ----------------------------------------------------------------

    def write(self, path, content, *, create=True, overwrite=True):
        self._check_writable()
        target = self.resolve(path)
        exists = target.exists()
        if exists and not overwrite:
            raise DocumentExists(path)
        if not exists and not create:
            raise DocumentNotFound(path)
        if exists and not target.is_file():
            raise StorageError(f"{path} is not a regular file.")
        data = content.encode("utf-8") if isinstance(content, str) else content
        target.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_write(target, data)
        return self.stat(path)

    def _atomic_write(self, target, data):
        fd, tmp = tempfile.mkstemp(prefix=TEMP_PREFIX, dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            if target.exists():
                os.chmod(tmp, target.stat().st_mode & 0o777)
            else:
                os.chmod(tmp, 0o644)
            os.replace(tmp, target)
        except BaseException:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
            raise
        self._fsync_dir(target.parent)

    @staticmethod
    def _fsync_dir(directory):
        try:
            fd = os.open(directory, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(fd)
        except OSError:
            pass
        finally:
            os.close(fd)

    def delete(self, path):
        self._check_writable()
        target = self.resolve(path)
        try:
            target.unlink()
        except FileNotFoundError:
            raise DocumentNotFound(path) from None
        self._prune_empty_dirs(target.parent)

    def move(self, source, destination):
        self._check_writable()
        src = self.resolve(source)
        dst = self.resolve(destination)
        if not src.is_file():
            raise DocumentNotFound(source)
        if dst.exists():
            raise DocumentExists(destination)
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.replace(src, dst)
        self._fsync_dir(dst.parent)
        self._prune_empty_dirs(src.parent)
        return self.stat(destination)

    def _prune_empty_dirs(self, directory):
        directory = Path(directory)
        while directory != self.root and self.root in directory.parents:
            try:
                directory.rmdir()
            except OSError:
                return
            directory = directory.parent

    # Maintenance ------------------------------------------------------------

    def leftover_temp_files(self):
        """Temporary files left behind by an interrupted write."""
        leftovers = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d != ".git"]
            leftovers.extend(
                self.relative(Path(dirpath) / name)
                for name in filenames
                if name.startswith(TEMP_PREFIX)
            )
        return sorted(leftovers)

    def remove_temp_files(self):
        removed = self.leftover_temp_files()
        for rel in removed:
            (self.root / rel).unlink(missing_ok=True)
        return removed
