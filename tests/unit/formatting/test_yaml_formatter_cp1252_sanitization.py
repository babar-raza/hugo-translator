"""
HT-QUALITY-GATES-001 Part 25: YAMLFormatter must sanitize CP1252-remnant C1
control characters before serialization, rather than crashing.

Real confirmed repro: retranslating a real products.aspose.org file to `uk`
produced literal U+0092 in the MT output, which previously crashed YAML
serialization with "unacceptable character #x0092: special characters are
not allowed" -- blocking the entire file write and leaving stale,
pre-mission content (including a wrong title) in place indefinitely.

Uses explicit \\xNN escape sequences throughout (never a literal raw control
byte in source) so the exact character under test is unambiguous.
"""
from src.translation_engine.reconstructor.yaml_formatter import YAMLFormatter


class TestCP1252C1Sanitization:
    def test_real_confirmed_u0092_is_fixed_not_crashed(self):
        """The exact real repro: a right single quote mis-encoded as the raw
        C1 control byte U+0092 inside a description field."""
        data = {"title": "Test", "description": "d\x92image processing"}

        yaml_content = YAMLFormatter.format_frontmatter(data)

        assert "\x92" not in yaml_content
        assert "d’image processing" in yaml_content

    def test_multiple_cp1252_artifacts_all_fixed(self):
        # Ellipsis placed mid-string, not trailing: "description" is also
        # RCD-checked (_strip_rcd_contamination), whose unrelated .rstrip()
        # would otherwise consume a trailing \x85 (Unicode NEL/whitespace)
        # before this sanitizer even runs -- not what this test is about.
        data = {
            "title": "Test",
            "description": "\x93Quoted\x94 text \x96 with a dash\x85 continued",
        }

        yaml_content = YAMLFormatter.format_frontmatter(data)

        assert not any(chr(c) in yaml_content for c in [0x93, 0x94, 0x96, 0x85])
        assert "“Quoted” text – with a dash… continued" in yaml_content

    def test_nested_fields_are_sanitized(self):
        data = {
            "title": "Test",
            "content": {"block": [{"content_left": "item\x92s here"}]},
        }

        yaml_content = YAMLFormatter.format_frontmatter(data)

        assert "\x92" not in yaml_content
        assert "item’s here" in yaml_content

    def test_clean_content_unaffected(self):
        data = {"title": "Test", "description": "Nothing unusual here."}

        yaml_content = YAMLFormatter.format_frontmatter(data)

        assert "Nothing unusual here." in yaml_content

    def test_literal_scalar_style_preserved_after_sanitization(self):
        from ruamel.yaml.scalarstring import LiteralScalarString

        data = {
            "title": "Test",
            "description": LiteralScalarString("Line one\x92s content\nLine two."),
        }

        yaml_content = YAMLFormatter.format_frontmatter(data)

        assert "\x92" not in yaml_content
        # Literal block style (|) must survive -- confirms the sanitizer
        # rewraps in LiteralScalarString rather than degrading to plain scalar.
        assert "description: |" in yaml_content
