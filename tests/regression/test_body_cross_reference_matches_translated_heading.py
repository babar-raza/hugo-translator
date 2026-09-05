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
