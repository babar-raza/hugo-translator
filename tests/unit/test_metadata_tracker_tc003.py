"""TC-APT-003: MetadataTracker extensions (sha256 primary, fingerprints, relative keys, backfill registration)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from src.utils.metadata_tracker import MetadataTracker


def _w(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_legacy_json_without_new_fields_still_loads(tmp_path):
    meta = tmp_path / "m.json"
    meta.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "site_id": "t",
                "tracking_config": {"hash_algorithm": "md5", "track_output_integrity": True},
                "files": {
                    "a.md": {
                        "source": {
                            "path": "a.md",
                            "hash": "abc",
                            "last_modified": "2025-01-01T00:00:00+00:00",
                            "size_bytes": 1,
                            "hash_computed_at": "2025-01-01T00:00:00+00:00",
                        },
                        "outputs": {
                            "es": {
                                "path": "es/a.md",
                                "hash": "def",
                                "translated_at": "2025-01-01T00:01:00+00:00",
                                "source_hash_at_translation": "abc",
                                "size_bytes": 1,
                                "status": "success",
                            }
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    tracker = MetadataTracker(meta)
    tracker.load()
    entry = tracker.entries()["a.md"]
    assert entry.source.sha256 is None and entry.source.profile_fingerprint is None
    assert entry.outputs["es"].sha256 is None


def test_relative_keys_sha256_and_fingerprints_roundtrip(tmp_path):
    root = tmp_path / "repo"
    src = _w(root / "content/site/en/a.md", "hello")
    out = _w(root / "content/site/de/a.md", "hallo")
    tracker = MetadataTracker(
        tmp_path / "m.json", hash_algorithm="sha256", site_id="site", root=root
    )
    tracker.update_source(src, profile_fingerprint="p" * 64, protection_fingerprint="q" * 64)
    tracker.update_output(
        src,
        out,
        "de",
        source_hash=tracker.get_source_hash(src),
        profile_fingerprint="p" * 64,
        protection_fingerprint="q" * 64,
    )
    tracker.save()

    reloaded = MetadataTracker(
        tmp_path / "m.json", hash_algorithm="sha256", site_id="site", root=root
    )
    entry = reloaded.entries()["content/site/en/a.md"]
    assert entry.source.path == "content/site/en/a.md"  # portable key/path
    assert entry.source.sha256 == hashlib.sha256(b"hello").hexdigest() == entry.source.hash
    assert entry.source.profile_fingerprint == "p" * 64
    assert entry.outputs["de"].path == "content/site/de/a.md"
    assert entry.outputs["de"].sha256 == hashlib.sha256(b"hallo").hexdigest()
    assert entry.outputs["de"].protection_fingerprint == "q" * 64
    assert reloaded.get_output(src, "de").status == "success"


def test_md5_tracker_still_records_explicit_sha256(tmp_path):
    src = _w(tmp_path / "a.md", "hello")
    tracker = MetadataTracker(tmp_path / "m.json", hash_algorithm="md5")
    tracker.update_source(src)
    entry = tracker.entries()[str(src)]
    assert entry.source.hash == hashlib.md5(b"hello").hexdigest()
    assert entry.source.sha256 == hashlib.sha256(b"hello").hexdigest()


def test_record_existing_output_never_claims_current_provenance(tmp_path):
    root = tmp_path / "repo"
    src = _w(root / "en/a.md", "hello")
    out = _w(root / "de/a.md", "hallo")
    tracker = MetadataTracker(tmp_path / "m.json", hash_algorithm="sha256", root=root)
    meta = tracker.record_existing_output(
        src, out, "de", sha256=hashlib.sha256(b"hallo").hexdigest()
    )
    assert meta.status == "unknown_provenance"
    assert meta.source_hash_at_translation == "" and meta.translated_at == ""
    assert meta.sha256 == hashlib.sha256(b"hallo").hexdigest()
    assert tracker.get_source_sha256(src) == hashlib.sha256(b"hello").hexdigest()


def test_check_source_changed_uses_sha256_not_mtime(tmp_path):
    src = _w(tmp_path / "a.md", "hello")
    tracker = MetadataTracker(tmp_path / "m.json", hash_algorithm="sha256")
    tracker.update_source(src)
    changed, reason = tracker.check_source_changed(src)
    assert changed is False and "sha256 match" in reason
    # Same mtime, different bytes: mtime fast path would lie; sha256 primary catches it.
    stat = src.stat()
    src.write_text("HELLO", encoding="utf-8")
    import os

    os.utime(src, (stat.st_atime, stat.st_mtime))
    changed, reason = tracker.check_source_changed(src)
    assert changed is True and "sha256" in reason
    # Explicit opt-in to the legacy mtime shortcut reproduces the old behaviour.
    changed_fast, reason_fast = tracker.check_source_changed(src, fast_path_mtime=True)
    assert changed_fast is False and "mtime unchanged" in reason_fast
