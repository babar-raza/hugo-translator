"""TC-APT-078 / RB-007: a body cross-reference to a section must agree with
that section's own translated heading.

Measured deterministic in 9/9 regenerated locales on words-document-net:
"Install it via NuGet, or build it from source -- see Quick Start below."
kept the English "Quick Start" while the actual heading below it
("## Quick Start") translated correctly to "## Démarrage rapide". The
reference and the heading are separate TextUnits translated in different
contexts, so nothing made them agree -- this is the deterministic real-world
repro (data/summaries/review-words-doc-r3-fr-20260905.json), reduced to a
fixture.
"""

from src.translation_engine.parser.ast_nodes import ASTNode, NodeType
from src.translation_engine.extractor.text_unit import TextUnit, TextUnitKind
from src.translation_engine.reconstructor.ast_renderer import ASTRenderer


def _heading(source, translated, node_addr="body.heading[0]"):
    node = ASTNode(type=NodeType.HEADING, children=[], attrs={"level": 2}, node_addr=node_addr)
    unit = TextUnit(unit_id=node_addr, node_addr=node_addr, source_text=source, kind=TextUnitKind.HEADING_TEXT)
    unit.translated_text = translated
    unit.metadata = {}
    return node, unit


def _paragraph(source, translated, node_addr="body.paragraph[0]"):
    node = ASTNode(type=NodeType.PARAGRAPH, children=[], attrs={}, node_addr=node_addr)
    unit = TextUnit(unit_id=node_addr, node_addr=node_addr, source_text=source, kind=TextUnitKind.TEXT)
    unit.translated_text = translated
    unit.metadata = {}
    return node, unit


def _code_block(source, node_addr="body.code_block[0]"):
    """Mirrors _extract_code_block (text_unit_extractor.py): do_not_translate=True,
    kind=CODE_SPAN, translated_text copied verbatim from source_text (never sent
    through translation)."""
    node = ASTNode(type=NodeType.CODE_BLOCK, children=[], attrs={"lang": "csharp"}, node_addr=node_addr)
    unit = TextUnit(
        unit_id=node_addr,
        node_addr=node_addr,
        source_text=source,
        kind=TextUnitKind.CODE_SPAN,
        do_not_translate=True,
    )
    unit.translated_text = source
    unit.metadata = {}
    return node, unit


def test_the_real_words_document_net_repro():
    heading_node, heading_unit = _heading("Quick Start", "Démarrage rapide")
    para_node, para_unit = _paragraph(
        "Install it via NuGet, or build it from source — see Quick Start below.",
        "Installez-le via NuGet, ou compilez-le à partir du code source — voir Quick Start ci-dessous.",
    )
    renderer = ASTRenderer()
    renderer.apply_translations([heading_node, para_node], [heading_unit, para_unit])

    assert "Démarrage rapide" in renderer._render_node(heading_node)
    rendered_para = renderer._render_node(para_node)
    assert "Quick Start" not in rendered_para
    assert "Démarrage rapide" in rendered_para


def test_a_heading_left_same_as_source_is_not_corrected_toward_itself():
    """Nothing to correct -- correcting "Scene Graph" -> "Scene Graph" would be a no-op
    that risks matching unrelated occurrences for zero benefit."""
    heading_node, heading_unit = _heading("Scene Graph", "Scene Graph")
    para_node, para_unit = _paragraph(
        "See the Scene Graph section for details.",
        "Voir la section Scene Graph pour plus de détails.",
    )
    renderer = ASTRenderer()
    renderer.apply_translations([heading_node, para_node], [heading_unit, para_unit])

    assert renderer._render_node(para_node) == "Voir la section Scene Graph pour plus de détails.\n\n"


def test_a_partial_word_match_is_not_corrected():
    """Word-boundary only: 'Start' inside 'Starting' must not trigger a mid-word swap."""
    heading_node, heading_unit = _heading("Start", "Démarrer")
    para_node, para_unit = _paragraph(
        "Starting the process is easy.",
        "Starting le processus est facile.",
    )
    renderer = ASTRenderer()
    renderer.apply_translations([heading_node, para_node], [heading_unit, para_unit])

    assert "Starting" in renderer._render_node(para_node)
    assert "Démarrer" not in renderer._render_node(para_node)


def test_a_short_heading_below_the_length_floor_is_not_used_for_correction():
    heading_node, heading_unit = _heading("FAQ", "FAQ")
    para_node, para_unit = _paragraph("See the FAQ for more.", "Voir la FAQ pour plus.")
    renderer = ASTRenderer()
    renderer.apply_translations([heading_node, para_node], [heading_unit, para_unit])
    assert renderer._render_node(para_node) == "Voir la FAQ pour plus.\n\n"


def test_multiple_headings_each_correct_independently():
    h1_node, h1_unit = _heading("Quick Start", "Démarrage rapide", "body.heading[0]")
    h2_node, h2_unit = _heading("Related Resources", "Ressources connexes", "body.heading[1]")
    para_node, para_unit = _paragraph(
        "See Quick Start above and Related Resources below.",
        "Voir Quick Start ci-dessus et Related Resources ci-dessous.",
    )
    renderer = ASTRenderer()
    renderer.apply_translations([h1_node, h2_node, para_node], [h1_unit, h2_unit, para_unit])

    rendered = renderer._render_node(para_node)
    assert "Démarrage rapide" in rendered
    assert "Ressources connexes" in rendered
    assert "Quick Start" not in rendered
    assert "Related Resources" not in rendered


def test_a_page_with_no_headings_is_unaffected():
    para_node, para_unit = _paragraph("Just a plain paragraph.", "Juste un paragraphe simple.")
    renderer = ASTRenderer()
    renderer.apply_translations([para_node], [para_unit])
    assert renderer._render_node(para_node) == "Juste un paragraphe simple.\n\n"


def test_a_code_block_is_never_touched_by_cross_reference_correction():
    """TC-APT-109: confirmed live on blog.aspose.org/words/net/introducing-words-foss-net --
    a page with a "### Charts" heading (correctly translated to "### Diagramme") and two
    fenced ```csharp blocks containing `using Aspose.Words.Drawing.Charts;`. Both code
    blocks came back as `using Aspose.Words.Drawing.Diagramme;`: the word-boundary regex
    in _correct_cross_references matched "Charts" inside the namespace path (a dot is a
    non-word character, so \\bCharts\\b matches right after "Drawing.") and replaced it
    with the heading's translation, corrupting code that must stay byte-for-byte
    identical. The heading_text exclusion alone only stops a heading correcting itself;
    it says nothing about do_not_translate content, which has its own, stronger,
    orthogonal protection contract."""
    heading_node, heading_unit = _heading("Charts", "Diagramme")
    code_source = "using Aspose.Words;\nusing Aspose.Words.Drawing.Charts;\n"
    code_node, code_unit = _code_block(code_source)
    renderer = ASTRenderer()
    renderer.apply_translations([heading_node, code_node], [heading_unit, code_unit])

    assert renderer._render_node(code_node) == f"```csharp\n{code_source}```\n\n"


def test_a_code_span_is_never_touched_by_cross_reference_correction():
    """Same protection, inline code span form (single backticks) rather than a fenced
    block -- both extraction paths mark do_not_translate=True and must be excluded."""
    heading_node, heading_unit = _heading("Chart", "Diagramm")
    node_addr = "body.code_span[0]"
    code_node = ASTNode(type=NodeType.CODE_SPAN, children=[], attrs={}, node_addr=node_addr)
    code_unit = TextUnit(
        unit_id=node_addr,
        node_addr=node_addr,
        source_text="Chart",
        kind=TextUnitKind.CODE_SPAN,
        do_not_translate=True,
    )
    code_unit.translated_text = "Chart"
    code_unit.metadata = {}
    renderer = ASTRenderer()
    renderer.apply_translations([heading_node, code_node], [heading_unit, code_unit])

    assert renderer._render_node(code_node) == "`Chart`"
