"""
Unit tests for LanguageDetectionCheck.

Tests:
- Pure target language passes
- Pure source language fails
- Mixed content detected with correct locations
- Technical content skipped
- Short strings skipped
- Confidence thresholds
"""

from unittest.mock import patch

import pytest

from src.verification.checks import LanguageDetectionCheck


class TestLanguageDetectionCheck:
    """Tests for LanguageDetectionCheck."""

    @pytest.fixture
    def check(self):
        """Default language detection check."""
        return LanguageDetectionCheck(
            min_text_length=10,
            confidence_threshold=0.7,
        )

    @pytest.fixture
    def german_text(self):
        """Sample German text."""
        return "Das ist ein deutscher Text zum Testen der Spracherkennung."

    @pytest.fixture
    def english_text(self):
        """Sample English text."""
        return "This is English text that should be flagged in German output."

    @pytest.fixture
    def mixed_frontmatter(self):
        """Frontmatter with mixed languages."""
        return {
            "frontmatter": {
                "title": "Das ist ein Testtitel",  # German
                "description": "This is an English description that wasn't translated",  # English
                "keywords": ["Schlüsselwort", "Test"],  # German
            }
        }

    def test_check_name(self, check):
        """Test check name property."""
        assert check.name == "language_detection"

    def test_pure_target_language_passes(self, check, german_text):
        """Test that pure German content passes when expecting German."""
        translated = {
            "frontmatter": {
                "title": german_text,
            }
        }

        issues = check.run({}, translated, "de")

        assert len(issues) == 0

    def test_pure_source_language_fails(self, check, english_text):
        """Test that pure English content fails when expecting German."""
        translated = {
            "frontmatter": {
                "description": english_text,
            }
        }

        issues = check.run({}, translated, "de")

        # Should detect English in German output
        assert len(issues) >= 1
        issue = issues[0]
        assert issue.severity == "error"
        assert issue.check_name == "language_detection"
        assert "frontmatter.description" in issue.location
        assert "de" in issue.message
        assert "en" in issue.message

    def test_mixed_content_detected(self, check, mixed_frontmatter):
        """Test that mixed language content is detected."""
        issues = check.run({}, mixed_frontmatter, "de")

        # Should detect English description
        english_issues = [i for i in issues if "description" in i.location]
        assert len(english_issues) >= 1

    def test_short_strings_skipped(self, check):
        """Test that short strings are skipped."""
        translated = {
            "frontmatter": {
                "short": "Hi",  # Too short
            }
        }

        issues = check.run({}, translated, "de")

        assert len(issues) == 0

    def test_configurable_min_length(self):
        """Test that minimum length is configurable."""
        short_check = LanguageDetectionCheck(min_text_length=5)
        long_check = LanguageDetectionCheck(min_text_length=100)

        translated = {
            "frontmatter": {
                "text": "Hello world this is English",  # 27 chars
            }
        }

        # Short threshold should check it
        short_issues = short_check.run({}, translated, "de")
        assert len(short_issues) >= 1

        # Long threshold should skip it
        long_issues = long_check.run({}, translated, "de")
        assert len(long_issues) == 0

    def test_nested_fields_checked(self, check):
        """Test that nested dictionary fields are checked."""
        translated = {
            "frontmatter": {
                "body": {
                    "block": {
                        "title": "This is English text in a nested field",
                    }
                }
            }
        }

        issues = check.run({}, translated, "de")

        assert len(issues) >= 1
        assert "body.block.title" in issues[0].location

    def test_array_fields_checked(self, check):
        """Test that array fields are checked."""
        translated = {
            "frontmatter": {
                "items": [
                    {"content": "Das ist deutsch"},
                    {"content": "This is English that should be detected"},
                ]
            }
        }

        issues = check.run({}, translated, "de")

        # Should find English in second item
        english_issues = [i for i in issues if "[1]" in i.location]
        assert len(english_issues) >= 1

    def test_body_content_checked(self, check, english_text):
        """Test that body content is checked when enabled."""
        translated = {
            "body": english_text,
        }

        issues = check.run({}, translated, "de")

        body_issues = [i for i in issues if i.location == "body"]
        assert len(body_issues) >= 1

    def test_body_check_disabled(self, english_text):
        """Test that body check can be disabled."""
        check = LanguageDetectionCheck(check_body=False)

        translated = {
            "body": english_text,
        }

        issues = check.run({}, translated, "de")

        body_issues = [i for i in issues if i.location == "body"]
        assert len(body_issues) == 0

    def test_frontmatter_check_disabled(self, english_text):
        """Test that frontmatter check can be disabled."""
        check = LanguageDetectionCheck(check_frontmatter=False)

        translated = {
            "frontmatter": {
                "title": english_text,
            }
        }

        issues = check.run({}, translated, "de")

        assert len(issues) == 0

    def test_technical_content_skipped(self, check):
        """Test that technical content is skipped."""
        translated = {
            "frontmatter": {
                "code": "```python\nprint('hello world')\n```",
                "url": "https://example.com/path/to/resource",
                "shortcode": "{{< gist abc123 >}} some content here",
            }
        }

        issues = check.run({}, translated, "de")

        # Technical content should be skipped
        assert len(issues) == 0

    def test_protected_evidence_and_grade_metadata_are_skipped(self, check):
        translated = {
            "frontmatter": {
                "title": "Das ist ein ausreichend langer deutscher Titel",
                "evidence": {
                    "model_sha": "This is immutable English provenance metadata",
                    "sections": [
                        {
                            "heading": "English source section heading",
                            "apis": ["Document save option identifier"],
                        }
                    ],
                },
                "grade_reasons": ["English grading rationale retained for auditability"],
            }
        }

        issues = check.run({}, translated, "de")

        assert issues == []

    def test_translatable_frontmatter_remains_checked_with_evidence(self, check):
        translated = {
            "frontmatter": {
                "description": ("This English description must still fail language detection"),
                "evidence": {
                    "heading": "Protected English evidence metadata",
                },
            }
        }

        issues = check.run({}, translated, "de")

        assert [issue.location for issue in issues] == ["frontmatter.description"]

    def test_issue_metadata(self, check, english_text):
        """Test that issues include useful metadata."""
        translated = {
            "frontmatter": {
                "text": english_text,
            }
        }

        issues = check.run({}, translated, "de")

        assert len(issues) >= 1
        issue = issues[0]
        assert "detected_lang" in issue.metadata
        assert "expected_lang" in issue.metadata
        assert "confidence" in issue.metadata
        assert issue.metadata["expected_lang"] == "de"

    def test_is_enabled_default(self, check):
        """Test that check is enabled by default."""
        assert check.is_enabled() is True
        assert check.is_enabled({}) is True

    def test_is_enabled_with_disable_flag(self, check):
        """Test that check can be disabled via context."""
        assert check.is_enabled({"disable_language_check": True}) is False
        assert check.is_enabled({"disable_language_check": False}) is True

    def test_language_code_variations(self, check):
        """Test that language code variations are handled."""
        # Using mock to simulate detection returning "en" for "en-us" expected
        with patch.object(check, "_detect_language") as mock_detect:
            # Simulate detecting "en" when expecting "en-US"
            mock_detect.return_value = ("en", 0.95)

            translated = {
                "frontmatter": {
                    "text": "This text is detected as 'en'",
                }
            }

            # Should pass because "en" matches "en-US" base
            issues = check.run({}, translated, "en-US")
            assert len(issues) == 0

    def test_confidence_threshold(self):
        """Test that low-confidence detections are ignored."""
        check = LanguageDetectionCheck(confidence_threshold=0.9)

        with patch.object(check, "_detect_language") as mock_detect:
            # Simulate low-confidence detection
            mock_detect.return_value = ("en", 0.5)  # Below threshold

            translated = {
                "frontmatter": {
                    "text": "Some ambiguous text content",
                }
            }

            issues = check.run({}, translated, "de")

            # Low confidence should not trigger issue
            assert len(issues) == 0

    def test_detection_failure_handled_gracefully(self, check):
        """Test that detection failures are handled gracefully."""
        with patch.object(check, "_detect_language") as mock_detect:
            mock_detect.return_value = (None, 0.0)

            translated = {
                "frontmatter": {
                    "text": "Some text that fails detection",
                }
            }

            issues = check.run({}, translated, "de")

            # Should not crash, just skip
            assert len(issues) == 0


class TestLanguageDetectionCheckIntegration:
    """Integration tests with real langdetect (if available)."""

    @pytest.fixture
    def check(self):
        """Language detection check for integration tests."""
        return LanguageDetectionCheck(min_text_length=20)

    def test_german_detection(self, check):
        """Test real German text detection."""
        try:
            translated = {
                "frontmatter": {
                    "title": "Dies ist ein ausführlicher deutscher Text zum Testen",
                }
            }

            issues = check.run({}, translated, "de")
            assert len(issues) == 0  # Should pass
        except ImportError:
            pytest.skip("langdetect not installed")

    def test_english_in_german_context(self, check):
        """Test detecting English in German context."""
        try:
            translated = {
                "frontmatter": {
                    "description": "This is a longer English text that should be detected as wrong language in German output",
                }
            }

            issues = check.run({}, translated, "de")
            assert len(issues) >= 1
            assert issues[0].severity == "error"
        except ImportError:
            pytest.skip("langdetect not installed")

    def test_french_detection(self, check):
        """Test French text detection."""
        try:
            translated = {
                "frontmatter": {
                    "title": "Ceci est un texte français pour tester la détection",
                }
            }

            issues = check.run({}, translated, "fr")
            assert len(issues) == 0  # Should pass
        except ImportError:
            pytest.skip("langdetect not installed")

    def test_spanish_detection(self, check):
        """Test Spanish text detection."""
        try:
            translated = {
                "frontmatter": {
                    "title": "Este es un texto en español para probar la detección",
                }
            }

            issues = check.run({}, translated, "es")
            assert len(issues) == 0  # Should pass
        except ImportError:
            pytest.skip("langdetect not installed")
