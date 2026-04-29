from pathlib import Path
from types import SimpleNamespace

from src.cli import _write_dry_run_manifest


class _FakeEngine:
    def __init__(self, output_root: Path):
        self.output_root = output_root

    def _get_output_path(self, source_path: Path, target_lang: str, site_profile) -> Path:
        return self.output_root / target_lang / source_path.name


def test_write_dry_run_manifest_records_translate_skip_and_fail(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source_dir = tmp_path / "content"
    source_dir.mkdir()
    output_root = tmp_path / "out"
    (output_root / "es").mkdir(parents=True)

    new_source = source_dir / "new.md"
    current_source = source_dir / "current.md"
    translated_source = source_dir / "current.es.md"
    new_source.write_text("---\ntitle: New\n---\n\nBody", encoding="utf-8")
    current_source.write_text("---\ntitle: Current\n---\n\nBody", encoding="utf-8")
    translated_source.write_text("---\ntitle: Ya\n---\n\nBody", encoding="utf-8")

    current_output = output_root / "es" / "current.md"
    current_output.write_text("---\ntitle: Actual\n---\n\nCuerpo", encoding="utf-8")
    future_mtime = current_source.stat().st_mtime + 10
    current_output.touch()
    import os
    os.utime(current_output, (future_mtime, future_mtime))

    def filter_source_files(files, site_profile, target_langs):
        return [p for p in files if not p.name.endswith(".es.md")]

    manifest_path = _write_dry_run_manifest(
        site_id="fixture.test",
        site_profile=SimpleNamespace(),
        input_path=source_dir,
        target_langs=["es"],
        model="test-model",
        engine=_FakeEngine(output_root),
        filter_source_files_func=filter_source_files,
    )

    import json
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["site"] == "fixture.test"
    assert manifest["model"] == "test-model"
    assert manifest["would_translate"] == [{
        "source_path": str(new_source),
        "target_lang": "es",
        "output_path": str(output_root / "es" / "new.md"),
    }]
    assert any(item["reason"] == "up_to_date" for item in manifest["would_skip"])
    assert any(item["reason"] == "filtered_or_translated" for item in manifest["would_skip"])
    assert manifest["would_fail"] == []

