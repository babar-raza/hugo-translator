"""
TC-HT-002: safe-write choke point + fence-aware repairs.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS_QUALITY = str(Path(__file__).resolve().parents[3] / "scripts" / "quality")
if _SCRIPTS_QUALITY not in sys.path:
    sys.path.insert(0, _SCRIPTS_QUALITY)

import pytest


class TestFenceSpans:
    def test_unfenced_and_fenced_segments_split_correctly(self):
        from fence_spans import split_fenced_segments

        body = "prose line one\n```python\ncode line\n```\nprose line two\n"
        segments = split_fenced_segments(body)
        flags = [is_fenced for is_fenced, _ in segments]
        assert flags == [False, True, False]
        assert "".join(segments[0][1]) == "prose line one\n"
        assert "".join(segments[1][1]) == "```python\ncode line\n```\n"
        assert "".join(segments[2][1]) == "prose line two\n"

    def test_no_fence_returns_single_unfenced_segment(self):
        from fence_spans import split_fenced_segments

        body = "just prose\nmore prose\n"
        segments = split_fenced_segments(body)
        assert len(segments) == 1
        assert segments[0][0] is False


class TestSafeIoSave:
    def _valid_content(self, description: str = "A valid description for testing purposes today.") -> str:
        return f"---\ntitle: Test\ndescription: {description}\n---\nSome body text here.\n"

    def test_save_writes_when_gate_passes(self, tmp_path):
        import safe_io

        out_path = tmp_path / "out.md"
        frontmatter, body = safe_io.parse_content(self._valid_content())
        result = safe_io.save(
            out_path, out_path, frontmatter, body,
            source_content=self._valid_content(), target_lang="es",
        )
        assert result.written is True
        assert out_path.exists()
        assert "Some body text" in out_path.read_text(encoding="utf-8")

    def test_save_quarantines_on_gate_failure(self, tmp_path, monkeypatch):
        import safe_io

        monkeypatch.chdir(tmp_path)
        out_path = tmp_path / "out.md"
        # Trip Gate 19/26-style fence-loss: source has many fences, target has none.
        source_content = (
            "---\ntitle: Test\ndescription: fine\n---\n"
            "```python\ncode a\n```\n\n```python\ncode b\n```\n\n"
            "```python\ncode c\n```\n"
        )
        bad_body = "All fences silently dropped here, only prose remains now.\n"
        frontmatter, _ = safe_io.parse_content(source_content)
        result = safe_io.save(
            out_path, out_path, frontmatter, bad_body,
            source_content=source_content, target_lang="es",
        )
        assert result.written is False
        assert not out_path.exists()
        assert result.quarantined is True
        assert result.quarantine_path is not None
        assert result.quarantine_path.exists()

    def test_save_no_frontmatter_is_blocked_not_written(self, tmp_path, monkeypatch):
        import safe_io

        monkeypatch.chdir(tmp_path)
        out_path = tmp_path / "out.md"
        result = safe_io.save(
            out_path, out_path, {}, "Body with no frontmatter at all.\n",
            source_content=self._valid_content(), target_lang="es",
        )
        assert result.written is False


class TestFenceAwareRepairs:
    def test_artifact_pattern_inside_fence_survives(self):
        from surgical_retranslate import _fix_artifact_corruption

        content = (
            "---\ntitle: Test\n---\n"
            "```text\nExample garbled output: ????\n```\n"
            "Real prose with artifact ???? outside the fence.\n"
        )
        fixed = _fix_artifact_corruption(content)
        assert "Example garbled output: ????" in fixed  # inside fence: untouched
        assert "Real prose with artifact ???? outside the fence." not in fixed  # dropped

    def test_shortcode_leak_inside_fence_survives(self):
        from surgical_retranslate import _fix_shortcode_leak

        en_content = "---\ntitle: Test\n---\nNo shortcodes in source body here.\n"
        tr_content = (
            "---\ntitle: Test\n---\n"
            "```text\n{{< ref \"example\" >}}\n```\n"
            "{{< ref \"leaked\" >}}\n"
        )
        fixed = _fix_shortcode_leak(en_content, tr_content)
        assert '{{< ref "example" >}}' in fixed  # inside fence: untouched
        assert '{{< ref "leaked" >}}' not in fixed  # leaked shortcode dropped

    def test_eu_hallucination_inside_fence_survives(self):
        from surgical_retranslate import _fix_eu_hallucination

        en_content = "---\ntitle: Test\n---\nSome unrelated prose about rendering scenes.\n"
        tr_content = (
            "---\ntitle: Test\n---\n"
            "```text\n// This example mentions cookie handling in code.\n```\n\n"
            "This paragraph hallucinates a GDPR privacy policy notice out of nowhere.\n"
        )
        fixed = _fix_eu_hallucination(en_content, tr_content)
        assert "cookie handling in code" in fixed  # inside fence: untouched
        assert "GDPR privacy policy notice" not in fixed  # hallucinated paragraph dropped


class TestInlineCodeZipRepairHardBail:
    def test_line_count_mismatch_skips_repair_no_line_drop(self):
        from surgical_retranslate import _apply_no_gpu_repairs

        # NLLB-style corruption: EN ASCII code span becomes non-ASCII in TR.
        en_content = "---\ntitle: Test\n---\nLine one `code_a`\nLine two `code_b`\nLine three `code_c`\n"
        # tr has FEWER lines than en (mismatch) -- must hard-bail, not silently
        # truncate via zip(), even though line 0 alone would otherwise trip the
        # inline-code-translation detector.
        tr_content = "---\ntitle: Test\n---\nLinea uno `códe_a`\nLinea dos `códe_b`\n"
        repaired, applied = _apply_no_gpu_repairs(en_content, tr_content)
        assert "inline_code_translation_skipped_line_count_mismatch" in applied
        # Content unchanged by the inline-code repair (no lines silently dropped/altered)
        assert repaired == tr_content


class TestNoRawWritesOutsideSafeIo:
    """Lint guard: the known translated-content repair scripts must route all
    content writes through safe_io.py. Scoped to these specific files (not
    the whole scripts/quality/ directory) because many sibling scripts in
    that directory legitimately write non-content JSON/report output using
    similarly-named path variables (e.g. check_deployment_safety.py,
    validate-evidence.py) — those are out of TC-HT-002's scope.
    """

    _CONTENT_REPAIR_SCRIPTS = (
        "surgical_retranslate.py",
        "delete_for_retranslate.py",
        "heal_english_headings.py",
        "backfill_frontmatter_ids.py",
        "aspose_org_governed_retranslate.py",
        "products_org_governed_retranslate.py",
        "audit_linguistic.py",
    )
    _CONTENT_WRITE_HEURISTIC = ("target", "tr_path", "out_path", "output_path")

    def test_no_raw_content_writes_outside_safe_io(self):
        import re

        quality_dir = Path(__file__).resolve().parents[3] / "scripts" / "quality"
        offenders = []
        for name in self._CONTENT_REPAIR_SCRIPTS:
            py_file = quality_dir / name
            text = py_file.read_text(encoding="utf-8", errors="replace")
            for match in re.finditer(r"(\w+)\.write_text\(", text):
                var = match.group(1)
                if var in self._CONTENT_WRITE_HEURISTIC:
                    offenders.append(f"{py_file.name}: {match.group(0)}")
        assert offenders == [], f"Raw content write_text() found outside safe_io.py: {offenders}"
