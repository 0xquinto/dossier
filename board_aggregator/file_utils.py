"""Reusable file-write helpers: UTF-8, lock-aware retry, atomic rename.

Centralizes the I/O failure modes the first user session hit on Windows:
cp1252 encoding crashes (force UTF-8), and EBUSY/WinError-5 when a target
file is open in an editor (retry with backoff, then a plain "close it"
message instead of a raw errno). Atomic temp+rename keeps a half-written
file from clobbering a good one. Other modules import from here.
"""

import errno
import os
import time
from pathlib import Path

# errnos that mean "the file is locked / busy", not "you lack permission".
# EACCES (13) is included because Windows surfaces an open-handle lock as
# PermissionError/WinError 5 -> errno 13.
_LOCK_ERRNOS = {errno.EBUSY, errno.EACCES, errno.EPERM}


def _is_lock_error(exc: OSError) -> bool:
    return exc.errno in _LOCK_ERRNOS


def atomic_write_text(
    path: Path,
    text: str,
    *,
    overwrite: bool = True,
    retries: int = 5,
    initial_delay: float = 0.1,
) -> None:
    """Write ``text`` to ``path`` as UTF-8, atomically and lock-aware.

    - UTF-8 always (no locale-dependent cp1252 crashes).
    - Atomic: write to a sibling ``.tmp`` then ``os.replace`` it into place.
    - Lock-aware: on EBUSY/WinError-5 (file open in an editor) retry with
      exponential backoff, then raise an OSError telling the user to close
      the file instead of leaking the raw errno.
    - ``overwrite=False`` enforces write-once: raise FileExistsError if the
      destination already exists (before doing any work).
    """
    path = Path(path)
    if not overwrite and path.exists():
        raise FileExistsError(
            f"Refusing to overwrite existing file: {path}. "
            "Use a fresh run directory or pass overwrite=True."
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")

    delay = initial_delay
    last_exc: OSError | None = None
    try:
        for attempt in range(retries):
            try:
                tmp.write_text(text, encoding="utf-8")
                os.replace(tmp, path)
                return
            except OSError as exc:
                last_exc = exc
                if not _is_lock_error(exc):
                    raise
                if attempt < retries - 1:
                    time.sleep(delay)
                    delay *= 2

        # Exhausted retries on a lock: surface an actionable message.
        raise OSError(
            f"File is locked (possibly open in an editor): {path}. "
            "Please close the file and try again."
        ) from last_exc
    finally:
        # Best-effort: never leave a scratch .tmp behind on a failure path.
        # On success os.replace already consumed it; on any error it may
        # remain (the good file is untouched since replace never ran).
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
