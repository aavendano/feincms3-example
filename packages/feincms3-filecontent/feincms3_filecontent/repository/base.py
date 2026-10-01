import fcntl
import os
import threading
import time
from pathlib import Path

from ..exceptions import RepositoryLocked


class RepositoryLock:
    """
    Inter-process advisory lock (``flock``) serializing every operation that
    mutates the working tree, the Git index or the content index.

    Readers (HTTP rendering) never take this lock: atomic file replacement
    keeps them consistent without it.

    The lock is re-entrant per thread. Each thread opens its own file
    descriptor, so ``flock`` also serializes threads of the same process.
    """

    def __init__(self, path, *, timeout=30):
        self.path = Path(path)
        self.timeout = timeout
        self._local = threading.local()

    @property
    def _depth(self):
        return getattr(self._local, "depth", 0)

    @_depth.setter
    def _depth(self, value):
        self._local.depth = value

    @property
    def _fd(self):
        return getattr(self._local, "fd", None)

    @_fd.setter
    def _fd(self, value):
        self._local.fd = value

    def acquire(self):
        if self._depth:
            self._depth += 1
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    os.close(fd)
                    raise RepositoryLocked(
                        f"Could not acquire {self.path} within {self.timeout}s."
                    ) from None
                time.sleep(0.05)
        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode())
        self._fd = fd
        self._depth = 1

    def release(self):
        if not self._depth:
            return
        self._depth -= 1
        if self._depth:
            return
        fcntl.flock(self._fd, fcntl.LOCK_UN)
        os.close(self._fd)
        self._fd = None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()
