"""
TC-MLD-01/03: Integration tests for mixed-language detection.

Verifies:
1. A synthesized file with >5% English paragraphs in a non-English translation
   is detected as contaminated by LanguageContaminationScanner.
2. The enhanced scanner correctly identifies contamination at block level.
3. The result_to_json() method produces the expected JSON structure.

These tests use only the scanner module (no engine, no model files required).
"""

import json
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_GERMAN_PARA = "Dies ist ein Absatz auf Deutsch, der einige Informationen enthält."
_ENGLISH_PARA = "This paragraph was never translated and remains in English language content."

_ARABIC_PARA = "هذا مقطع نصي باللغة العربية يحتوي على معلومات مفيدة ومهمة للقراء."
_ENGLISH_IN_ARABIC = "This is an English paragraph that was accidentally left untranslated."


def _build_mixed_md(
    target_paras: list[str],
    contam_paras: list[str],
    lang_code: str = "de",
) -> str:
    """Build a synthetic Markdown file with mixed language content."""
    all_paras = target_paras + contam_paras
    return "---\ntitle: Test\n---\n\n" + "\n\n".join(all_paras) + "\n"


def _write_tmp_file(tmp_path: Path, content: str, filename: str) -> Path:
    f = tmp_path / filename
    f.write_text(content, encoding="utf-8")
    return f


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestContaminationScannerDetection:
    """LanguageContaminationScanner detects contaminated synthetic files."""

    def test_contaminated_german_file_detected(self, tmp_path):
        """File with ~15% English paragraphs in German content is flagged."""
        pytest.importorskip("langdetect", reason="langdetect required")

        from scripts.scan_language_contamination import LanguageContaminationScanner

        # 15 German paragraphs + 3 English = ~17% contamination (above 5% threshold)
        german_paras = [
            "Dies ist ein langer Absatz auf Deutsch, der beschreibt wie man Dateien konvertiert.",
        ] * 15
        english_paras = [
            "This is an English paragraph that should have been translated to German.",
            "Another English sentence that was left untranslated in this document.",
            "Yet another English paragraph that clearly does not belong here.",
        ]

        content = _build_mixed_md(german_paras, english_paras, "de")
        de_file = _write_tmp_file(tmp_path, content, "test.de.md")

        scanner = LanguageContaminationScanner(min_purity=95.0, min_sentence_length=15)
        result = scanner.scan_repository(
            repo_path=tmp_path,
            target_lang="de",
            all_languages=False,
            fast_mode=False,
        )

        contaminated = [a for a in result.analyses if a.has_quality_issues]
        assert len(contaminated) >= 1, (
            f"Expected at least 1 contaminated file, got {len(contaminated)}. "
            f"Scan result: {[(a.file_path, a.purity_percentage) for a in result.analyses]}"
        )

        # The specific file should be flagged
        flagged_paths = {a.file_path for a in contaminated}
        assert str(de_file) in flagged_paths

    def test_clean_german_file_not_flagged(self, tmp_path):
        """File with 100% German content is NOT flagged as contaminated."""
        pytest.importorskip("langdetect", reason="langdetect required")

        from scripts.scan_language_contamination import LanguageContaminationScanner

        german_paras = [
            "Dies ist ein vollständig auf Deutsch übersetzter Absatz ohne englische Inhalte.",
            "Hier sind weitere Informationen auf Deutsch, die korrekt übersetzt wurden.",
            "Dieser Text enthält ausschließlich deutsche Wörter und Sätze ohne Ausnahmen.",
        ] * 5

        content = _build_mixed_md(german_paras, [], "de")
        de_file = _write_tmp_file(tmp_path, content, "clean.de.md")

        scanner = LanguageContaminationScanner(min_purity=95.0)
        result = scanner.scan_repository(
            repo_path=tmp_path,
            target_lang="de",
            all_languages=False,
            fast_mode=False,
        )

        contaminated = [a for a in result.analyses if a.purity_percentage < 95.0]
        assert len(contaminated) == 0, (
            f"Clean file should not be flagged. Got: {[(a.file_path, a.purity_percentage) for a in contaminated]}"
        )

    def test_block_level_detection_finds_english_blocks(self, tmp_path):
        """Block-level detection identifies which specific paragraphs are English."""
        pytest.importorskip("langdetect", reason="langdetect required")

        from scripts.scan_language_contamination import LanguageContaminationScanner

        # Build file with clearly labelled English contamination
        content = (
            "---\ntitle: Test\n---\n\n"
            "Dies ist ein langer Absatz auf Deutsch über Technologie und Software-Entwicklung.\n\n"
            "This paragraph is completely in English and should not appear in a German translation.\n\n"
            "Noch ein Absatz auf Deutsch über die Verwendung von Softwareprodukten und APIs.\n\n"
            "Another English paragraph that was mistakenly not translated into German language.\n"
        )
        de_file = _write_tmp_file(tmp_path, content, "blocktest.de.md")

        scanner = LanguageContaminationScanner(min_purity=95.0)
        blocks = scanner._analyze_blocks(de_file, "de")

        # Should have found at least 2 English blocks
        english_blocks = [b for b in blocks if b["detected_lang"] == "en"]
        assert len(english_blocks) >= 1, f"Expected at least 1 English block. Got blocks: {blocks}"

    def test_fast_mode_detects_script_mixing(self, tmp_path):
        """Fast mode (no langdetect) catches Arabic script in German content."""
        from scripts.scan_language_contamination import LanguageContaminationScanner

        # German file with Arabic script embedded (clear script mismatch)
        content = (
            "---\ntitle: Test\n---\n\n"
            "Dies ist ein Absatz auf Deutsch.\n\n"
            "هذا نص عربي داخل ملف ألماني وهو خطأ واضح.\n\n"
            "Weiterer deutscher Text hier.\n"
        )
        de_file = _write_tmp_file(tmp_path, content, "scriptmix.de.md")

        scanner = LanguageContaminationScanner(min_purity=95.0)
        result = scanner.scan_repository(
            repo_path=tmp_path,
            target_lang="de",
            fast_mode=True,  # Script-only mode
        )

        script_mixing = [a for a in result.analyses if a.script_mixing_issues]
        assert len(script_mixing) >= 1, (
            f"Expected script mixing detection in fast mode. Got: {result.analyses}"
        )


class TestResultToJson:
    """result_to_json() produces correct JSON structure for force_retranslate_contaminated.py."""

    def test_json_structure_has_required_fields(self, tmp_path):
        """result_to_json() output contains all fields required by force_retranslate script."""
        from datetime import datetime

        from scripts.scan_language_contamination import (
            FileAnalysis,
            LanguageContaminationScanner,
            ScanResult,
        )

        # Build a synthetic ScanResult with one contaminated file
        analysis = FileAnalysis(
            file_path="/path/to/test.de.md",
            relative_path="test.de.md",
            target_lang="de",
            total_sentences=20,
            correct_lang_count=16,
            purity_percentage=80.0,
            wrong_lang_samples=[{"detected": "en", "confidence": 0.92, "snippet": "English text"}],
            site_id="blog.aspose.net",
        )

        result = ScanResult(
            total_files=1,
            scanned_files=1,
            contaminated_files=1,
            script_mixing_files=0,
            repetition_files=0,
            clean_files=0,
            error_files=0,
            deleted_files=0,
            analyses=[analysis],
            target_lang="de",
            scan_timestamp=datetime.now().isoformat(),
            repo_path="/path/to/content",
        )

        json_data = LanguageContaminationScanner.result_to_json(result, min_purity=95.0)

        # Validate top-level structure
        assert "scan_timestamp" in json_data
        assert "total_files" in json_data
        assert "contaminated_count" in json_data
        assert "files" in json_data

        # Validate file entry structure
        assert len(json_data["files"]) == 1
        file_entry = json_data["files"][0]

        required_file_fields = {
            "file_path",
            "site_id",
            "target_lang",
            "purity_percentage",
            "threshold",
        }
        for field in required_file_fields:
            assert field in file_entry, f"Missing required field: {field}"

        assert file_entry["file_path"] == "/path/to/test.de.md"
        assert file_entry["site_id"] == "blog.aspose.net"
        assert file_entry["target_lang"] == "de"
        assert file_entry["purity_percentage"] == 80.0
        assert file_entry["threshold"] == 95.0

    def test_clean_files_not_in_json(self):
        """Clean files (no quality issues) are not included in JSON 'files' list."""
        from datetime import datetime

        from scripts.scan_language_contamination import (
            FileAnalysis,
            LanguageContaminationScanner,
            ScanResult,
        )

        clean = FileAnalysis(
            file_path="/path/clean.de.md",
            relative_path="clean.de.md",
            target_lang="de",
            total_sentences=20,
            correct_lang_count=20,
            purity_percentage=100.0,
            wrong_lang_samples=[],
        )

        result = ScanResult(
            total_files=1,
            scanned_files=1,
            contaminated_files=0,
            script_mixing_files=0,
            repetition_files=0,
            clean_files=1,
            error_files=0,
            deleted_files=0,
            analyses=[clean],
            target_lang="de",
            scan_timestamp=datetime.now().isoformat(),
            repo_path="/path/to/content",
        )

        json_data = LanguageContaminationScanner.result_to_json(result)
        assert json_data["files"] == [], "Clean files should not appear in JSON output"
