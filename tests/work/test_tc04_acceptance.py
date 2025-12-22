"""
Standalone acceptance test for TC-04 (Apply Translations to AST + Render).
Run this script to verify TC-04 implementation.
"""
import sys
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

# Direct import to avoid dependency issues
import importlib.util

# Load modules
def load_module(name, file_path, package=None):
    spec = importlib.util.spec_from_file_location(name, file_path)
    module = importlib.util.module_from_spec(spec)
    if package:
        module.__package__ = package
    spec.loader.exec_module(module)
    return module

# Load required modules
ast_nodes = load_module(
    "ast_nodes",
    src_path / "translation_engine" / "parser" / "ast_nodes.py"
)
text_unit = load_module(
    "text_unit",
    src_path / "translation_engine" / "extractor" / "text_unit.py"
)

# Create fake package structure for relative imports
class FakeModule:
    pass

# Set up module hierarchy
extractor_package = FakeModule()
extractor_package.text_unit = text_unit
parser_package = FakeModule()
parser_package.ast_nodes = ast_nodes

# Register in sys.modules
sys.modules['src'] = FakeModule()
sys.modules['src.translation_engine'] = FakeModule()
sys.modules['src.translation_engine.extractor'] = extractor_package
sys.modules['src.translation_engine.extractor.text_unit'] = text_unit
sys.modules['src.translation_engine.parser'] = parser_package
sys.modules['src.translation_engine.parser.ast_nodes'] = ast_nodes

ast_renderer = load_module(
    "ast_renderer",
    src_path / "translation_engine" / "reconstructor" / "ast_renderer.py",
    package="src.translation_engine.reconstructor"
)

# Extract classes
ASTNode = ast_nodes.ASTNode
NodeType = ast_nodes.NodeType
text_node = ast_nodes.text_node
paragraph_node = ast_nodes.paragraph_node
heading_node = ast_nodes.heading_node

TextUnit = text_unit.TextUnit
TextUnitKind = text_unit.TextUnitKind
ASTRenderer = ast_renderer.ASTRenderer


def test_apply_translation():
    """Test applying translation to AST."""
    renderer = ASTRenderer()

    # Create simple paragraph
    para = paragraph_node([text_node("Hello")])
    para.assign_addresses("body.paragraph[0]")

    # Create translated unit
    unit = TextUnit(
        unit_id="u1",
        node_addr="body.paragraph[0].text[0]",
        kind=TextUnitKind.TEXT,
        source_text="Hello",
        translated_text="Hola"
    )

    # Apply
    renderer.apply_translations([para], [unit])

    # Verify
    assert para.children[0].raw == "Hola"
    print("OK Test 1: Translation applied to AST")


def test_apply_with_whitespace():
    """Test whitespace reattachment."""
    renderer = ASTRenderer()

    para = paragraph_node([text_node("  Hello  ")])
    para.assign_addresses("body.paragraph[0]")

    unit = TextUnit(
        unit_id="u1",
        node_addr="body.paragraph[0].text[0]",
        kind=TextUnitKind.TEXT,
        source_text="Hello",
        prefix_ws="  ",
        suffix_ws="  ",
        translated_text="Hola"
    )

    renderer.apply_translations([para], [unit])

    # Whitespace should be reattached
    assert para.children[0].raw == "  Hola  "
    print("OK Test 2: Whitespace reattached correctly")


def test_render_paragraph():
    """Test rendering paragraph."""
    renderer = ASTRenderer()

    para = paragraph_node([text_node("Hello world")])

    markdown = renderer.render_to_markdown([para])

    assert "Hello world" in markdown
    assert markdown.endswith("\n\n")
    print("OK Test 3: Paragraph rendered correctly")


def test_render_heading():
    """Test rendering heading."""
    renderer = ASTRenderer()

    heading = heading_node(level=2, children=[text_node("My Heading")])

    markdown = renderer.render_to_markdown([heading])

    assert markdown == "## My Heading\n\n"
    print("OK Test 4: Heading rendered correctly")


def test_render_strong():
    """Test rendering bold text."""
    renderer = ASTRenderer()

    strong = ASTNode(type=NodeType.STRONG, children=[text_node("bold")])
    para = paragraph_node([text_node("This is "), strong])

    markdown = renderer.render_to_markdown([para])

    assert "**bold**" in markdown
    print("OK Test 5: Bold text rendered correctly")


def test_render_emphasis():
    """Test rendering italic text."""
    renderer = ASTRenderer()

    em = ASTNode(type=NodeType.EMPHASIS, children=[text_node("italic")])
    para = paragraph_node([em])

    markdown = renderer.render_to_markdown([para])

    assert "*italic*" in markdown
    print("OK Test 6: Italic text rendered correctly")


def test_render_code_span():
    """Test rendering inline code."""
    renderer = ASTRenderer()

    code = ASTNode(type=NodeType.CODE_SPAN, raw="myFunction()")
    para = paragraph_node([text_node("Call "), code])

    markdown = renderer.render_to_markdown([para])

    assert "`myFunction()`" in markdown
    print("OK Test 7: Inline code rendered correctly")


def test_render_link():
    """Test rendering link."""
    renderer = ASTRenderer()

    link = ASTNode(
        type=NodeType.LINK,
        attrs={"url": "https://example.com"},
        children=[text_node("Click here")]
    )
    para = paragraph_node([link])

    markdown = renderer.render_to_markdown([para])

    assert "[Click here](https://example.com)" in markdown
    print("OK Test 8: Link rendered correctly")


def test_link_url_preservation():
    """Test URL is preserved when translating link text."""
    renderer = ASTRenderer()

    link = ASTNode(
        type=NodeType.LINK,
        attrs={"url": "https://example.com"},
        children=[text_node("link")]
    )
    link.assign_addresses("body.link[0]")
    link.children[0].assign_addresses("body.link[0].text[0]")

    # Translate link text
    unit = TextUnit(
        unit_id="u1",
        node_addr="body.link[0].text[0]",
        kind=TextUnitKind.LINK_TEXT,
        source_text="link",
        translated_text="enlace"
    )

    renderer.apply_translations([link], [unit])
    markdown = renderer.render_to_markdown([link])

    # URL preserved, text translated
    assert "https://example.com" in markdown
    assert "enlace" in markdown
    print("OK Test 9: URL preserved, link text translated")


def test_render_image():
    """Test rendering image."""
    renderer = ASTRenderer()

    image = ASTNode(
        type=NodeType.IMAGE,
        attrs={"src": "/images/photo.jpg", "alt": "Photo"}
    )

    markdown = renderer.render_to_markdown([image])

    assert "![Photo](/images/photo.jpg)" in markdown
    print("OK Test 10: Image rendered correctly")


def test_image_src_preservation():
    """Test image src is preserved when translating alt text."""
    renderer = ASTRenderer()

    image = ASTNode(
        type=NodeType.IMAGE,
        attrs={"src": "/images/photo.jpg", "alt": "Photo"}
    )
    image.assign_addresses("body.image[0]")

    # Translate alt text
    unit = TextUnit(
        unit_id="u1",
        node_addr="body.image[0]",
        kind=TextUnitKind.IMAGE_ALT,
        source_text="Photo",
        translated_text="Foto"
    )

    renderer.apply_translations([image], [unit])
    markdown = renderer.render_to_markdown([image])

    # src preserved, alt translated
    assert "/images/photo.jpg" in markdown
    assert "![Foto]" in markdown
    print("OK Test 11: Image src preserved, alt text translated")


def test_nested_formatting():
    """Test nested formatting (bold in link)."""
    renderer = ASTRenderer()

    # [**bold**](url)
    strong = ASTNode(type=NodeType.STRONG, children=[text_node("bold")])
    link = ASTNode(
        type=NodeType.LINK,
        attrs={"url": "https://example.com"},
        children=[strong]
    )
    para = paragraph_node([link])

    markdown = renderer.render_to_markdown([para])

    assert "[**bold**](https://example.com)" in markdown
    print("OK Test 12: Nested formatting rendered correctly")


def test_deterministic_rendering():
    """Test same AST produces identical Markdown."""
    renderer1 = ASTRenderer()
    renderer2 = ASTRenderer()

    para1 = paragraph_node([text_node("Same text")])
    para2 = paragraph_node([text_node("Same text")])

    markdown1 = renderer1.render_to_markdown([para1])
    markdown2 = renderer2.render_to_markdown([para2])

    assert markdown1 == markdown2
    print("OK Test 13: Rendering is deterministic")


def test_end_to_end():
    """Test complete translate and render workflow."""
    renderer = ASTRenderer()

    # Create document structure
    heading = heading_node(level=1, children=[text_node("Title")])
    strong = ASTNode(type=NodeType.STRONG, children=[text_node("bold")])
    link = ASTNode(
        type=NodeType.LINK,
        attrs={"url": "https://example.com"},
        children=[text_node("link")]
    )
    code = ASTNode(type=NodeType.CODE_SPAN, raw="code()")
    para = paragraph_node([
        text_node("Visit "),
        strong,
        text_node(" or "),
        link,
        text_node(" and see "),
        code
    ])

    # Assign addresses
    heading.assign_addresses("body.heading[0]")
    para.assign_addresses("body.paragraph[0]")

    # Create translation units
    units = [
        TextUnit(
            unit_id="u1",
            node_addr="body.heading[0].text[0]",
            kind=TextUnitKind.TEXT,
            source_text="Title",
            translated_text="Título"
        ),
        TextUnit(
            unit_id="u2",
            node_addr="body.paragraph[0].text[0]",
            kind=TextUnitKind.TEXT,
            source_text="Visit",
            translated_text="Visitar",
            suffix_ws=" "
        ),
        TextUnit(
            unit_id="u3",
            node_addr="body.paragraph[0].strong[0].text[0]",
            kind=TextUnitKind.TEXT,
            source_text="bold",
            translated_text="audaz"
        ),
        TextUnit(
            unit_id="u4",
            node_addr="body.paragraph[0].text[1]",
            kind=TextUnitKind.TEXT,
            source_text="or",
            prefix_ws=" ",
            suffix_ws=" ",
            translated_text="o"
        ),
        TextUnit(
            unit_id="u5",
            node_addr="body.paragraph[0].link[0].text[0]",
            kind=TextUnitKind.LINK_TEXT,
            source_text="link",
            translated_text="enlace"
        ),
        TextUnit(
            unit_id="u6",
            node_addr="body.paragraph[0].text[2]",
            kind=TextUnitKind.TEXT,
            source_text="and see",
            prefix_ws=" ",
            suffix_ws=" ",
            translated_text="y ver"
        ),
        TextUnit(
            unit_id="u7",
            node_addr="body.paragraph[0].codespan[0]",
            kind=TextUnitKind.CODE_SPAN,
            source_text="code()",
            do_not_translate=True,
            translated_text="code()"
        ),
    ]

    # Apply translations
    renderer.apply_translations([heading, para], units)

    # Render to markdown
    markdown = renderer.render_to_markdown([heading, para])

    # Verify translations applied
    assert "Título" in markdown
    assert "Visitar" in markdown
    assert "audaz" in markdown
    assert "enlace" in markdown
    assert "y ver" in markdown

    # Verify preservation
    assert "https://example.com" in markdown  # URL preserved
    assert "`code()`" in markdown  # Code preserved

    print("OK Test 14: End-to-end workflow works")
    print("\nRendered Markdown:")
    print(markdown)


def run_all_tests():
    """Run all TC-04 acceptance tests."""
    print("=== TC-04 Acceptance Tests ===")
    print("")

    test_apply_translation()
    test_apply_with_whitespace()
    test_render_paragraph()
    test_render_heading()
    test_render_strong()
    test_render_emphasis()
    test_render_code_span()
    test_render_link()
    test_link_url_preservation()
    test_render_image()
    test_image_src_preservation()
    test_nested_formatting()
    test_deterministic_rendering()
    test_end_to_end()

    print("")
    print("=== ALL TC-04 ACCEPTANCE TESTS PASSED ===")
    print("")
    print("TC-04 Deliverables Complete:")
    print("OK ASTRenderer class implemented")
    print("OK apply_translations() method works")
    print("OK Whitespace reattachment working")
    print("OK render_to_markdown() handles all node types")
    print("OK Headings, paragraphs, bold, italic rendered")
    print("OK Code, links, images rendered")
    print("OK URL preservation verified")
    print("OK Image src preservation verified")
    print("OK Code preservation verified")
    print("OK Nested formatting supported")
    print("OK Deterministic rendering verified")
    print("OK End-to-end workflow tested")
    print("")
    print("Ready to proceed to TC-05: Engine Wiring Behind Feature Flag")


if __name__ == '__main__':
    run_all_tests()
