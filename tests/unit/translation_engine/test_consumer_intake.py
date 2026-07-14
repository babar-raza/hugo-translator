"""
TC-HT-007: cross-repo intake handshake (vendored aspose.org checks).

Reuses the three wave-3 corruption-class fixtures rather than inventing
new ones: truncated description, code-fence strip, prompt-leak title.
"""
from __future__ import annotations

from src.translation_engine.consumer_intake import check_pair, check_text


class TestCheckText:
    def test_valid_frontmatter_passes(self):
        text = "---\ntitle: Test\ndescription: A fine description here.\n---\nBody.\n"
        assert check_text(text, "test.md") == []

    def test_no_frontmatter_passes(self):
        assert check_text("Just body, no frontmatter.\n", "test.md") == []

    def test_missing_closing_delimiter_fails(self):
        text = "---\ntitle: Test\ndescription: no closing delimiter\nBody.\n"
        failures = check_text(text, "test.md")
        assert any("F3" in f for f in failures)

    def test_unparseable_yaml_fails(self):
        # Unterminated single-quoted scalar swallows the next key (wave-3 signature).
        text = (
            "---\ntitle: Test\ndescription: 'This quote never closes\n"
            "date: 2026-03-29\n---\nBody.\n"
        )
        failures = check_text(text, "test.md")
        assert any("F1" in f for f in failures)

    def test_non_mapping_frontmatter_fails(self):
        text = "---\n- just\n- a\n- list\n---\nBody.\n"
        failures = check_text(text, "test.md")
        assert any("F2" in f for f in failures)


class TestCheckPair:
    def test_clean_pair_passes(self):
        cur = "---\ntitle: Test\ndescription: Une belle description en francais ici.\n---\nCorps.\n"
        old = cur
        assert check_pair(cur, old, "fr") == []

    def test_description_reverted_to_english_blocks_r1(self):
        cur = (
            "---\ntitle: Test\ndescription: Learn how to use the tool with all "
            "your files and export them from the app for your project.\n---\nBody.\n"
        )
        old = "---\ntitle: Test\ndescription: Une description qui etait deja traduite avant.\n---\nCorps.\n"
        failures = check_pair(cur, old, "fr")
        assert "R1" in failures

    def test_pre_existing_english_does_not_block(self):
        """Only a REGRESSION blocks -- if the OLD version was already
        English, staying English is not a new regression."""
        cur = "---\ntitle: Test\ndescription: A description that reads clearly as English for the reader.\n---\nBody.\n"
        old = "---\ntitle: Test\ndescription: Another description that also reads as English text here.\n---\nBody.\n"
        failures = check_pair(cur, old, "fr")
        assert "R1" not in failures

    def test_prompt_leak_phrase_blocks_r2(self):
        cur = "---\ntitle: Test\ndescription: fine\n---\nOutput ONLY the translation, nothing else.\n"
        failures = check_pair(cur, None, "fr")
        assert "R2" in failures

    def test_fence_strip_blocks_r3(self):
        old = "---\ntitle: Test\n---\n```python\ncode\n```\n\n```python\nmore\n```\n"
        cur = "---\ntitle: Test\n---\ncode without any fences at all now.\n"
        failures = check_pair(cur, old, "fr")
        assert "R3" in failures

    def test_matching_fence_count_passes_r3(self):
        old = "---\ntitle: Test\n---\n```python\ncode\n```\n"
        cur = "---\ntitle: Test\n---\n```python\ncodigo\n```\n"
        failures = check_pair(cur, old, "fr")
        assert "R3" not in failures

    def test_no_old_text_skips_regression_checks(self):
        """A brand-new file (no old version) can't regress."""
        cur = "---\ntitle: Test\ndescription: fine\n---\nBody.\n"
        failures = check_pair(cur, None, "fr")
        assert failures == []


class TestSafeIoIntegration:
    """safe_io.save() must consult consumer_intake for existing targets."""

    def test_save_blocks_english_regression_over_existing_translation(self, tmp_path, monkeypatch):
        import sys
        from pathlib import Path

        scripts_quality = str(Path(__file__).resolve().parents[3] / "scripts" / "quality")
        if scripts_quality not in sys.path:
            sys.path.insert(0, scripts_quality)
        import safe_io

        monkeypatch.chdir(tmp_path)
        out_path = tmp_path / "target.md"
        out_path.write_text(
            "---\ntitle: Test\ndescription: Une description qui etait deja traduite avant.\n---\nCorps.\n",
            encoding="utf-8",
        )

        english_regression = (
            "---\ntitle: Test\ndescription: Learn how to use the tool with all "
            "your files and export them from the app for your project.\n---\nBody.\n"
        )
        frontmatter, body = safe_io.parse_content(english_regression)
        result = safe_io.save(
            out_path, out_path, frontmatter, body,
            source_content=english_regression,
            target_lang="fr",
        )
        assert result.written is False
        assert any("consumer_intake:R1" in r for r in result.reasons)
        # Existing good translation must be untouched.
        assert "Une description" in out_path.read_text(encoding="utf-8")
