"""TC-APT-042: a soft-wrapped sentence must reach the model whole.

A source paragraph wrapped mid-sentence used to produce one TEXT node per source
line with a SOFT_BREAK between them. When the paragraph also contained a link or
bold span, `_should_extract_full_sentence()` sent it down the leaf-level path,
which makes each TEXT sibling its own translation unit -- so the fragments were
translated with no knowledge of each other.

Measured consequence on cells/go/introducing-cells-foss-go: 16 of 16 reviewed
locales failed in the same paragraph, with split noun phrases ("No hay uso
restricciones"), duplicated tokens, spurious copulas, and outright meaning
inversion in Thai and Vietnamese.
See data/summaries/fp-softwrap-sentence-splitting-20260905.json.

Two properties are pinned here:
  1. The wrapped-with-link paragraph extracts as ONE prose unit.
  2. The fix is output-neutral -- rendering is byte-identical with and without it,
     because ASTRenderer already emits SOFT_BREAK as a single space.
"""

import pytest

from src.translation_engine.extractor.text_unit_extractor import TextUnitExtractor
from src.translation_engine.parser.hugo_parser import HugoParser
from src.translation_engine.reconstructor.ast_renderer import ASTRenderer

# The exact paragraph, wrapped exactly as the real source wraps it.
REAL_PARAGRAPH = (
    "---\ntitle: t\n---\n\n"
    "## Open Source & Licensing\n\n"
    "Aspose.Cells FOSS for Go is released under the MIT license. There are no usage\n"
    "restrictions, no runtime fees, and no registration requirements. The source code is\n"
    "available at [github.com/x](https://github.com/x).\n"
)


def _prose_units(markdown: str) -> list[str]:
    parsed = HugoParser().parse_string(markdown)
    plan = TextUnitExtractor().extract_from_ast(parsed.ast, parsed.frontmatter or {})
    texts = []
    for unit in getattr(plan, "units", plan):
        text = getattr(unit, "source_text", None) or getattr(unit, "text", "")
        if text and text.strip():
            texts.append(text)
    return texts


def _render_body(markdown: str, *, merge_enabled: bool) -> str:
    original = HugoParser._merge_soft_breaks
    if not merge_enabled:
        HugoParser._merge_soft_breaks = lambda self, nodes: nodes
    try:
        parsed = HugoParser().parse_string(markdown)
        return ASTRenderer().render_to_markdown(parsed.ast)
    finally:
        HugoParser._merge_soft_breaks = original


def test_wrapped_sentence_with_a_link_stays_one_unit():
    units = _prose_units(REAL_PARAGRAPH)

    prose = [u for u in units if "no usage" in u or "restrictions" in u]
    assert len(prose) == 1, f"sentence was split into fragments: {prose}"
    whole = prose[0]
    assert "no usage restrictions" in whole, "the noun phrase must not be split across units"
    assert "The source code is available at" in whole, "the copula must stay with its complement"


def test_no_unit_is_a_bare_sentence_fragment():
    """The specific shapes that caused the defect must not appear as standalone units."""
    units = _prose_units(REAL_PARAGRAPH)

    for fragment in ("There are no usage", "The source code is"):
        assert not any(u.strip().endswith(fragment) for u in units), (
            f"{fragment!r} is a dangling fragment -- a model cannot translate it correctly"
        )


def test_the_fix_is_output_neutral():
    """Rendering must be byte-identical with and without the merge."""
    assert _render_body(REAL_PARAGRAPH, merge_enabled=True) == _render_body(
        REAL_PARAGRAPH, merge_enabled=False
    )


def test_soft_break_before_a_link_keeps_its_space():
    """A break that is not between two TEXT nodes must still render as a space."""
    markdown = "---\ntitle: t\n---\n\nSee the docs\n[here](https://x).\n"

    assert _render_body(markdown, merge_enabled=True) == _render_body(
        markdown, merge_enabled=False
    )
    assert "docs here" in "".join(_prose_units(markdown)) or any(
        u.strip().endswith("docs") for u in _prose_units(markdown)
    )


def test_unwrapped_paragraph_is_unaffected():
    markdown = (
        "---\ntitle: t\n---\n\n"
        "There are no usage restrictions and the source is at [x](https://x).\n"
    )
    units = _prose_units(markdown)

    assert any("no usage restrictions" in u for u in units)
    assert _render_body(markdown, merge_enabled=True) == _render_body(
        markdown, merge_enabled=False
    )


def test_soft_break_inside_bold_is_also_merged():
    units = _prose_units("---\ntitle: t\n---\n\nSome **bold\ntext** here.\n")

    assert "bold text" in units, f"bold span was split: {units}"


@pytest.mark.parametrize(
    "body",
    [
        "One line only.\n",
        "Two sentences. On one line.\n",
        "A\nB\nC wrapped three ways with a [link](https://x).\n",
        "- list item wrapped\n  across lines with [link](https://x)\n",
    ],
)
def test_output_neutrality_holds_across_shapes(body):
    markdown = "---\ntitle: t\n---\n\n" + body

    assert _render_body(markdown, merge_enabled=True) == _render_body(
        markdown, merge_enabled=False
    )
