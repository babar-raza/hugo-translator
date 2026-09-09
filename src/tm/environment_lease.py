"""Coordinate TM environment lifetimes with offline maintenance.

Every opener holds a distinct OS lock. Maintenance holds the admission lock
and probes existing leases, excluding both current and newly starting users.
Crash leftovers are harmless because the operating system releases locks.
"""

import os
from contextlib import ExitStack, contextmanager
from pathlib import Path
from uuid import uuid4


class EnvironmentBusy(RuntimeError):
    """An environment is open or maintenance is already running."""


class _OSLock:
    """Nonblocking lock with stable inode and fixed byte offset on Windows."""

    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = path.open("a+b")
        try:
            if self.file.seek(0, 2) == 0:
                self.file.write(b"0")
                self.file.flush()
            self.file.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close()
            raise EnvironmentBusy(f"active environment lease: {path}") from exc

    def close(self):
        if not self.file.closed:
            self.file.close()  # OS releases the lock, including on process exit.

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def _root(environment: Path) -> Path:
    environment = environment.resolve()
    return environment.parent / ".tm-leases" / environment.name


class EnvironmentLease:
    def __init__(self, environment: Path):
        root = _root(environment)
        with _OSLock(root / "admission.lock"):
            self.lock = _OSLock(root / f"user-{uuid4().hex}.lock")

    def close(self):
        self.lock.close()


@contextmanager
def maintenance(environments):
    """Exclude active and newly starting users across both merge stores."""
    with ExitStack() as stack:
        roots = sorted({_root(Path(path)) for path in environments})
        for root in roots:
            stack.enter_context(_OSLock(root / "admission.lock"))
        for root in roots:
            for path in sorted(root.glob("user-*.lock")):
                stack.enter_context(_OSLock(path))
        yield
