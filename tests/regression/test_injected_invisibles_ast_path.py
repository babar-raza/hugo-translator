"""TC-APT-073 must be wired into the path the in-scope sites actually run.

The first cut of this fix lived only in
`segment_translator._restore_placeholders`. Every in-scope profile sets
`use_ast_body_reconstruction: true`, and `_translate_body_ast` never calls that
method -- so the fix was inert for body AND frontmatter on every site that
motivated it, while its unit tests passed. RECURRENCE step 2 (reverify against
the exact failing files) is what surfaced it.

These tests pin the coverage property rather than the function's behaviour,
which `test_injected_invisible_characters.py` already covers:

  * the AST renderer normalizes FRONTMATTER units -- nl and he carried 67 and 37
    injected characters, dominated by `description`/`summary`;
  * it normalizes BODY units;
  * it does so even when the unit has NO placeholder_map. The renderer calls
    `_restore_placeholders` only `if placeholder_map:`, so normalization nested
    inside that branch would skip exactly the plain prose where most of the 147
    occurrences live. This is the trap the placement had to avoid.
"""

from src.translation_engine.extractor.text_unit import TextUnit, TextUnitKind
from src.translation_engine.reconstructor.ast_renderer import ASTRenderer

NBH = "‑"  # NON-BREAKING HYPHEN
SHY = "­"  # SOFT HYPHEN


def _frontmatter_unit(source: str, translated: str, field: str = "summary", **metadata) -> TextUnit:
    unit = TextUnit(
        unit_id=f"u-{field}",
        node_addr=f"frontmatter.{field}",
        kind=TextUnitKind.TEXT,
        source_text=source,
        prefix_ws="",
        suffix_ws="",
        do_not_translate=False,
    )
    unit.translated_text = translated
    unit.metadata = {"field_name": field, "field_type": "string", **metadata}
    return unit


def _apply(units: list[TextUnit]) -> dict:
    frontmatter: dict = {unit.metadata["field_name"]: "" for unit in units}
    ASTRenderer()._apply_frontmatter_translations(frontmatter, units)
    return frontmatter


def test_frontmatter_units_are_normalized():
    """nl carried 67 injected characters, mostly in description/summary."""
    result = _apply([_frontmatter_unit("node-tree APIs", f"node{NBH}tree APIs")])

    assert NBH not in result["summary"]
    assert result["summary"] == "node-tree APIs"


def test_frontmatter_normalization_does_not_require_a_placeholder_map():
    """The placement trap: _restore_placeholders runs only `if placeholder_map:`."""
    unit = _frontmatter_unit("plain source", f"plain{NBH}target")

    assert not unit.metadata.get("placeholder_map")
    assert NBH not in _apply([unit])["summary"]


def test_frontmatter_soft_hyphen_is_removed():
    result = _apply([_frontmatter_unit("dependent", f"depen{SHY}dent", field="title")])

    assert result["title"] == "dependent"


def test_a_character_the_source_uses_survives_in_frontmatter():
    """Fidelity rule, not a character ban."""
    result = _apply([_frontmatter_unit(f"node{NBH}tree", f"node{NBH}tree")])

    assert result["summary"] == f"node{NBH}tree"


def test_frontmatter_placeholders_still_restore():
    """Neutrality: normalization must not disturb the existing restore path."""
    unit = _frontmatter_unit(
        "See {PLACEHOLDER_0} now",
        f"Zie {{PLACEHOLDER_0}} nu{NBH}x",
        placeholder_map={"{PLACEHOLDER_0}": "[docs](https://example.com)"},
    )

    result = _apply([unit])["summary"]

    assert "[docs](https://example.com)" in result
    assert NBH not in result


def test_the_body_path_normalizes_before_restoring():
    """Ordering, asserted on the source: protected spans must still be masked.

    If normalization ran after restoration it could rewrite characters inside a
    restored URL or code span.
    """
    from pathlib import Path

    source = Path("src/translation_engine/reconstructor/ast_renderer.py").read_text(encoding="utf-8")
    body = source.split("# Restore placeholders (if any were applied during extraction)")[0]
    tail = body.rsplit("final_text = normalize_injected_invisibles", 1)

    assert len(tail) == 2, "body path does not normalize before the restore block"


def test_both_call_sites_are_outside_the_placeholder_conditional():
    """Regression guard for the exact mistake this file documents."""
    from pathlib import Path

    source = Path("src/translation_engine/reconstructor/ast_renderer.py").read_text(encoding="utf-8")

    for line in source.splitlines():
        if "normalize_injected_invisibles(" in line and "import" not in line:
            assert not line.startswith(" " * 20), (
                "normalization looks nested inside the `if placeholder_map:` branch: " + line
            )
