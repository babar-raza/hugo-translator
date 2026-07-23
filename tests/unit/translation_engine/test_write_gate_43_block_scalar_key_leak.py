"""
Integration tests for write gate 43 (HT-QUALITY-GATES-001 Phase 8, Tier A
#5): block-scalar key-line leak -- a translated multi-line/folded YAML
scalar whose parsed value contains an embedded pattern resembling a YAML
key line, absent from source. Complementary to Gate 27 (which catches a
scalar losing content); this catches a scalar absorbing content it
shouldn't have, the "silently swallows description" shape not covered by
Gate 27's length-ratio floor or by YAMLValidator/FrontmatterIntegrityValidator's
hard-parse-error and key-set-drift checks (the document still parses
cleanly with the same key set -- it just has wrong content in one field).

Ships "warn" per this registry's established rollout convention.
"""
from pathlib import Path
from unittest.mock import MagicMock

from src.translation_engine.write_gate import WriteGateEvaluator, WriteGateResult


def _make_gate() -> WriteGateEvaluator:
    config = MagicMock()
    config.get_config.return_value = {"translation_engine": {}}
    return WriteGateEvaluator(
        detector=None, similarity_tracker=None, config=config, force_accept=True,
    )


_EN = (
    "---\n"
    "title: Sample\n"
    "description: >\n"
    "  A folded description that\n"
    "  spans multiple lines here.\n"
    "summary: A short summary field.\n"
    "---\n"
    "Body.\n"
)


class TestGateBlockScalarKeyLeak:
    def test_leaked_key_line_fragment_is_flagged(self):
        tr = (
            '---\n'
            'title: Sample\n'
            'description: "A folded description translated.\\nsummary: leaked content here"\n'
            'summary: A short summary field translated.\n'
            '---\n'
            'Cuerpo.\n'
        )
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_block_scalar_key_leak(_EN, tr, Path("test.md"), result)

        assert result.passed is False
        assert "description" in result.error
        assert "summary:" in result.error

    def test_clean_translation_is_silent(self):
        tr = (
            "---\n"
            "title: Sample\n"
            "description: >\n"
            "  Una descripcion plegada que\n"
            "  abarca varias lineas aqui.\n"
            "summary: Un resumen corto traducido.\n"
            "---\n"
            "Cuerpo.\n"
        )
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_block_scalar_key_leak(_EN, tr, Path("test.md"), result)

        assert result.passed is True

    def test_single_line_field_is_not_checked(self):
        """Only fields that were multi-line in the SOURCE are in scope --
        matches Gate 27's own scoping via _is_multiline_source_field."""
        en = "---\ntitle: Sample\ndescription: A single line description.\n---\nBody.\n"
        tr = '---\ntitle: Sample\ndescription: "Translated.\\nsummary: fake"\n---\nCuerpo.\n'
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_block_scalar_key_leak(en, tr, Path("test.md"), result)

        assert result.passed is True

    def test_source_itself_containing_the_shape_is_not_flagged(self):
        """If the source field legitimately contains colon-terminated text
        that happens to match the key-line pattern (e.g. documenting YAML
        syntax), only a NEW occurrence introduced by translation should
        block."""
        en = (
            "---\ntitle: Sample\ndescription: >\n"
            "  Example: use the\n"
            "  key: value syntax here.\n"
            "---\nBody.\n"
        )
        tr = (
            "---\ntitle: Sample\ndescription: >\n"
            "  Ejemplo: usa la\n"
            "  sintaxis key: value aqui.\n"
            "---\nCuerpo.\n"
        )
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_block_scalar_key_leak(en, tr, Path("test.md"), result)

        assert result.passed is True

    def test_missing_frontmatter_is_a_graceful_no_op(self):
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_block_scalar_key_leak("no frontmatter here", "tampoco aqui", Path("test.md"), result)

        assert result.passed is True
