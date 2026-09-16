"""TC-PORT-LLM-013: a real 4-worker soak hit "PermissionError: [Errno 13]
Permission denied: 'logs\\...campaign..._child0.shards.txt'" reading this
process's own just-written, single-owner shard-list file. Each child has a
distinct path (not a cross-worker race), and this repo lives under OneDrive,
whose sync client is documented to briefly hold a sharing lock on a
just-created file -- a short bounded retry absorbs exactly that transient
window without masking a real, persistent permission problem.
"""

from pathlib import Path

import pytest

from scripts.campaign import run_gate5_batch


def test_succeeds_immediately_when_there_is_no_contention(tmp_path: Path):
    target = tmp_path / "shards.txt"
    target.write_text("w0:a:b:c:d:1\n", encoding="utf-8")

    assert run_gate5_batch._read_text_with_retry(target) == "w0:a:b:c:d:1\n"


def test_retries_through_a_transient_permission_error(tmp_path: Path, monkeypatch):
    target = tmp_path / "shards.txt"
    target.write_text("w0:a:b:c:d:1\n", encoding="utf-8")

    real_read_text = Path.read_text
    attempts = {"n": 0}

    def _flaky_read_text(self, *args, **kwargs):
        if self == target and attempts["n"] < 2:
            attempts["n"] += 1
            raise PermissionError(13, "Permission denied", str(self))
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _flaky_read_text)
    monkeypatch.setattr(run_gate5_batch.time, "sleep", lambda _seconds: None)

    result = run_gate5_batch._read_text_with_retry(target)

    assert result == "w0:a:b:c:d:1\n"
    assert attempts["n"] == 2


def test_reraises_after_exhausting_attempts_on_a_persistent_failure(tmp_path: Path, monkeypatch):
    target = tmp_path / "shards.txt"
    target.write_text("w0:a:b:c:d:1\n", encoding="utf-8")

    def _always_denied(self, *args, **kwargs):
        raise PermissionError(13, "Permission denied", str(self))

    monkeypatch.setattr(Path, "read_text", _always_denied)
    monkeypatch.setattr(run_gate5_batch.time, "sleep", lambda _seconds: None)

    with pytest.raises(PermissionError):
        run_gate5_batch._read_text_with_retry(target, attempts=3)
