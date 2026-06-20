import errno
from unittest.mock import patch

import pytest

from board_aggregator.file_utils import atomic_write_text


def test_atomic_write_text_writes_utf8(tmp_path):
    path = tmp_path / "sub" / "out.txt"  # parent does not exist yet
    atomic_write_text(path, "café ñ 🚀 mañana")
    assert path.read_text(encoding="utf-8") == "café ñ 🚀 mañana"
    # No leftover scratch file from the atomic rename.
    assert not (path.parent / (path.name + ".tmp")).exists()


def test_atomic_write_text_replaces_existing(tmp_path):
    path = tmp_path / "out.txt"
    path.write_text("old", encoding="utf-8")
    atomic_write_text(path, "new")  # overwrite defaults True here
    assert path.read_text(encoding="utf-8") == "new"


def test_atomic_write_text_write_once(tmp_path):
    path = tmp_path / "out.txt"
    path.write_text("old", encoding="utf-8")
    with pytest.raises(FileExistsError):
        atomic_write_text(path, "new", overwrite=False)
    assert path.read_text(encoding="utf-8") == "old"  # untouched


def test_atomic_write_retries_on_lock_then_succeeds(tmp_path):
    """EBUSY on the first 2 attempts, success on the 3rd (T3-2)."""
    path = tmp_path / "locked.txt"
    real_replace = __import__("os").replace
    calls = {"n": 0}

    def flaky_replace(src, dst):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise OSError(errno.EBUSY, "Resource busy")
        return real_replace(src, dst)

    with patch("board_aggregator.file_utils.os.replace", side_effect=flaky_replace), \
            patch("board_aggregator.file_utils.time.sleep"):
        atomic_write_text(path, "done", retries=5, initial_delay=0.0)

    assert calls["n"] == 3  # retried twice, succeeded on third
    assert path.read_text(encoding="utf-8") == "done"


def test_atomic_write_raises_friendly_message_after_retries(tmp_path):
    """After exhausting retries on a lock, surface a 'close the file' message."""
    path = tmp_path / "stuck.txt"

    def always_busy(src, dst):
        raise OSError(errno.EBUSY, "Resource busy")

    with patch("board_aggregator.file_utils.os.replace", side_effect=always_busy), \
            patch("board_aggregator.file_utils.time.sleep"):
        with pytest.raises(OSError) as exc_info:
            atomic_write_text(path, "x", retries=5, initial_delay=0.0)

    msg = str(exc_info.value)
    assert "locked" in msg.lower()
    assert "close the file" in msg.lower()
    assert "EBUSY" not in msg  # raw errno not leaked to the user


def test_atomic_write_cleans_up_tmp_on_lock_failure(tmp_path):
    """After the friendly lock error, no sibling .tmp is left behind (I4)."""
    path = tmp_path / "stuck.txt"
    tmp = path.parent / (path.name + ".tmp")

    def always_busy(src, dst):
        raise OSError(errno.EBUSY, "Resource busy")

    with patch("board_aggregator.file_utils.os.replace", side_effect=always_busy), \
            patch("board_aggregator.file_utils.time.sleep"):
        with pytest.raises(OSError):
            atomic_write_text(path, "x", retries=5, initial_delay=0.0)

    assert not tmp.exists()  # scratch file removed on the failure path
    assert not path.exists()  # the good file was never clobbered (replace never ran)


def test_atomic_write_does_not_retry_non_lock_errors(tmp_path):
    """A non-lock OSError (e.g. ENOSPC) propagates immediately, no retry."""
    path = tmp_path / "nospace.txt"
    calls = {"n": 0}

    def no_space(src, dst):
        calls["n"] += 1
        raise OSError(errno.ENOSPC, "No space left on device")

    with patch("board_aggregator.file_utils.os.replace", side_effect=no_space), \
            patch("board_aggregator.file_utils.time.sleep"):
        with pytest.raises(OSError) as exc_info:
            atomic_write_text(path, "x", retries=5, initial_delay=0.0)

    assert calls["n"] == 1  # no retry on a non-lock error
    assert exc_info.value.errno == errno.ENOSPC
