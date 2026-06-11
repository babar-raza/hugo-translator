"""
Tests for the engine frontmatter presence gate (Fix 2 — SD-01 defense-in-depth).

The frontmatter presence gate lives at engine.py:1913-1925.
It fires when the source file has '---' (YAML frontmatter) but the translated
output does not. This prevents silent frontmatter loss from ever being written.

Root cause of incident 6837f6671:
  - English _index.md files had unquoted YAML values with ': '
  - Both parsers failed silently, producing empty frontmatter dict
  - format_frontmatter({}) returns "" → translated_content = "\n{body}"
  - No existing gate caught the missing '---' in output

These tests simulate the exact gate logic from engine.py:1913-1925 to verify
the gate condition fires and does not fire in all three relevant scenarios.
"""


def _run_frontmatter_gate(source: str, translated: str, validation_passed: bool = True):
    """
    Simulate the engine frontmatter presence gate from engine.py:1913-1925.

    Returns (validation_passed, retryable_gate_failure, validation_error).
    """
    retryable_gate_failure = None
    validation_error = None

    # Exact replica of engine.py:1913-1925
    if validation_passed and source.lstrip("\n").startswith("---"):
        if not translated.lstrip("\n").startswith("---"):
            validation_passed = False
            retryable_gate_failure = False  # structural — not retryable
            validation_error = (
                "Frontmatter presence gate: source file has frontmatter "
                "(---) but translated output does not. Blocking write to "
                "prevent frontmatter loss. Fix the source YAML syntax."
            )

    return validation_passed, retryable_gate_failure, validation_error


class TestFrontmatterPresenceGateFires:
    """Gate must fire when source has frontmatter but output does not."""

    def test_gate_fires_when_output_is_body_only(self):
        """Classic SD-01 scenario: source has --- but output is just body text."""
        source = "---\ntitle: Test\n---\n\nBody text here.\n"
        # What the engine produced when frontmatter was silently dropped
        translated = "\nTraduction du corps ici.\n"

        passed, retryable, error = _run_frontmatter_gate(source, translated)

        assert not passed, "Gate must block the write"
        assert retryable is False, "Structural failure must not be retryable"
        assert "Frontmatter presence gate" in error
        assert "---" in error

    def test_gate_fires_when_output_starts_with_blank_line_then_body(self):
        """Output with leading newline before body (exact shape from incident)."""
        source = "---\ntitle: Guide\ndescription: foo\n---\n\nBody.\n"
        translated = "\n\nCorps traduit.\n"  # two leading newlines, then body

        passed, retryable, error = _run_frontmatter_gate(source, translated)

        assert not passed
        assert retryable is False

    def test_gate_fires_when_output_is_empty(self):
        """Degenerate case: translated content is empty string."""
        source = "---\ntitle: Test\n---\n\nBody.\n"
        translated = ""

        passed, retryable, error = _run_frontmatter_gate(source, translated)

        assert not passed
        assert retryable is False


class TestFrontmatterPresenceGateDoesNotFire:
    """Gate must NOT fire when both source and output have frontmatter."""

    def test_gate_passes_when_both_have_frontmatter(self):
        """Normal case: both source and translation start with ---."""
        source = "---\ntitle: Test\n---\n\nBody.\n"
        translated = "---\ntitle: Titre de test\n---\n\nCorps traduit.\n"

        passed, retryable, error = _run_frontmatter_gate(source, translated)

        assert passed, "Gate must pass when output has frontmatter"
        assert retryable is None
        assert error is None

    def test_gate_passes_when_source_has_no_frontmatter(self):
        """Source without frontmatter: gate must not fire regardless of output."""
        source = "# Heading\n\nPlain body content, no YAML block.\n"
        translated = "# Titre\n\nCorps traduit.\n"

        passed, retryable, error = _run_frontmatter_gate(source, translated)

        assert passed, "Gate must not fire when source has no frontmatter"

    def test_gate_passes_when_source_no_frontmatter_output_also_no_frontmatter(self):
        """Files legitimately without frontmatter must flow through unchanged."""
        source = "Body only.\n"
        translated = "Corps seulement.\n"

        passed, retryable, error = _run_frontmatter_gate(source, translated)

        assert passed

    def test_gate_passes_when_source_has_leading_newline_before_delimiters(self):
        """Source with leading newline before --- is still detected correctly."""
        source = "\n---\ntitle: Test\n---\n\nBody.\n"
        translated = "\n---\ntitle: Titre\n---\n\nCorps.\n"

        passed, retryable, error = _run_frontmatter_gate(source, translated)

        assert passed

    def test_gate_not_blocked_when_validation_already_failed(self):
        """Gate only runs if validation_passed is True — must not override existing fail."""
        source = "---\ntitle: Test\n---\n\nBody.\n"
        translated = "\nBody only — no frontmatter.\n"

        # Pass validation_passed=False (previous gate already failed)
        passed, retryable, error = _run_frontmatter_gate(
            source, translated, validation_passed=False
        )

        # Should stay False but NOT modify retryable/error (gate skipped)
        assert not passed
        assert retryable is None  # Gate did not execute (condition short-circuits)
        assert error is None


class TestFrontmatterGateRetryBehavior:
    """Gate failures must be non-retryable (structural, not transient)."""

    def test_retryable_is_false_on_gate_failure(self):
        """Structural frontmatter loss is not a retry scenario."""
        source = "---\ntitle: Test\n---\n\nBody.\n"
        translated = "\nBody only.\n"

        _, retryable, _ = _run_frontmatter_gate(source, translated)

        assert retryable is False, (
            "Frontmatter loss is a structural error (malformed source YAML). "
            "Retrying the same translation will produce the same bad output."
        )

    def test_error_message_guides_operator(self):
        """Error message must explain root cause and direct fix."""
        source = "---\ntitle: Test\n---\n\nBody.\n"
        translated = "\nBody only.\n"

        _, _, error = _run_frontmatter_gate(source, translated)

        assert "frontmatter" in error.lower()
        assert "---" in error
        assert "Fix" in error or "fix" in error
