"""TC-APT-076: a paragraph containing a link translates as one sentence.

TC-APT-036 removed LINK from _has_inline_formatting's leaf-forcing set so
link-bearing paragraphs would translate whole. A SECOND, independent gate --
_has_technical_content -- also returned True for any LINK child, and the
adaptive strategy is the AND of both, so paragraphs kept splitting and that half
of TC-APT-036 never took effect. Measured on words-document-net: 15 paragraphs,
12 whole, 3 split, all 3 by technical-content alone and 0 by formatting.

The cost was sentence integrity. The paragraph became three units: one ending on
a dangling subordinator, the anchor alone with no sentence context, and one
starting with a subjectless verb phrase. The orphaned subordinator had nothing
to attach to and survived untranslated into 4 of 11 locales at the same line,
and reviewers found all 3 in-prose links defective in fa.

SEQUENCING MATTERS HERE. Removing the trigger was falsified on 2026-09-05: an
identity round-trip over 14 real pages went 14/14 -> 0/14 byte-identical,
because re-parsing a whole translated paragraph dropped every link's URL,
rendering "[text]()". That was a latent markdown-it-py 4.x bug in the renderer
(Token.attrs is a dict; the re-parse iterated it as (key, value) tuples, so the
href lookup never matched), fixed separately in e065151. Only with that landed
is this change output-neutral.

test_a_link_bearing_paragraph_round_trips_byte_identical is therefore the
load-bearing test: it fails if either half regresses.
"""

from pathlib import Path

import pytest

from src.translation_engine.extractor.text_unit_extractor import TextUnitExtractor
from src.translation_engine.parser.ast_nodes import NodeType
from src.translation_engine.parser.hugo_parser import HugoParser
from src.translation_engine.reconstructor.ast_renderer import ASTRenderer
from src.utils.config_loader import ConfigService

MARKDOWN = """## Introduction

This guide looks at how the library represents a document in memory. Where
[the announcement post](/words/net/introducing-words-foss-net/) introduces the
library as a whole, this one stays focused on the object model and how its
pieces fit together.
"""


@pytest.fixture(scope="module")
def patterns():
    return list(ConfigService(Path("config")).get_site_profile("blog.aspose.org").body.preserve_patterns)


def _walk(nodes):
    for node in nodes:
        yield node
        if getattr(node, "children", None):
            yield from _walk(node.children)


def _extract(markdown, patterns):
    doc = HugoParser().parse_string(f"---\ntitle: t\n---\n\n{markdown}")
    extractor = TextUnitExtractor(segmentation_strategy="adaptive", preserve_patterns=patterns)
    return doc, extractor, extractor.extract_from_ast(doc.ast, doc.frontmatter).units


def test_the_paragraph_is_one_unit_not_three(patterns):
    """The whole point: the model must see the sentence, not fragments."""
    _doc, _ex, units = _extract(MARKDOWN, patterns)

    paragraph_units = [u for u in units if str(u.node_addr).startswith("body.paragraph")]
    addrs = {u.node_addr for u in paragraph_units}

    assert len(addrs) == 1, f"paragraph was split into {len(addrs)} units: {sorted(addrs)}"
    assert not any(".link" in str(u.node_addr) for u in units), "anchor extracted as its own unit"


def test_the_dangling_subordinator_is_inside_a_complete_unit(patterns):
    """It used to be the LAST word of its unit, with its clause in another."""
    _doc, _ex, units = _extract(MARKDOWN, patterns)

    holder = next(u for u in units if "Where" in (u.source_text or ""))

    assert not (holder.source_text or "").rstrip().endswith("Where")
    assert "introduces the" in (holder.source_text or ""), "the clause is in a different unit"


def test_link_is_no_longer_a_leaf_forcing_trigger(patterns):
    """Pins the gate itself, so a revert is caught even if extraction shifts."""
    doc, extractor, _units = _extract(MARKDOWN, patterns)
    paragraph = next(
        n for n in _walk(doc.ast)
        if n.type == NodeType.PARAGRAPH and any(c.type == NodeType.LINK for c in _walk([n]))
    )

    assert extractor._has_inline_formatting(paragraph) is False
    assert extractor._has_technical_content(paragraph) is False


def test_a_link_bearing_paragraph_round_trips_byte_identical(patterns):
    """Load-bearing: fails if the extractor OR the renderer half regresses.

    Identity translation -- every unit returns its own source text -- must
    reproduce the markdown exactly, URL included. This is the property whose
    failure (14/14 -> 0/14 on real pages) correctly blocked this change before
    the renderer fix landed.
    """
    doc, _ex, units = _extract(MARKDOWN, patterns)
    before = ASTRenderer().render_to_markdown(doc.ast)

    for unit in units:
        unit.translated_text = unit.source_text
    renderer = ASTRenderer()
    renderer.apply_translations(doc.ast, units, doc.frontmatter)
    after = renderer.render_to_markdown(doc.ast)

    assert after == before
    assert "/words/net/introducing-words-foss-net/" in after, "the URL was dropped"
    assert "]()" not in after, "empty link target -- the markdown-it attrs regression"
    assert renderer.placeholder_leak_count == 0


def test_a_code_block_still_forces_leaf_extraction(patterns):
    """Only the LINK trigger was removed; CODE_BLOCK must still trigger.

    A fenced block is not reconstructable as inline text, which is why that
    branch exists and why it was left alone.
    """
    doc, extractor, _units = _extract(
        "Text before.\n\n```bash\ndotnet build\n```\n\nText after.\n", patterns
    )

    blocks = [n for n in _walk(doc.ast) if n.type == NodeType.CODE_BLOCK]

    assert blocks, "fixture did not produce a CODE_BLOCK"
    for node in _walk(doc.ast):
        if getattr(node, "children", None) and any(
            c.type is NodeType.CODE_BLOCK for c in node.children
        ):
            assert extractor._has_technical_content(node) is True
