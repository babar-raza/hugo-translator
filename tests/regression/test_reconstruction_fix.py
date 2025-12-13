"""Test the nested array reconstruction fix."""
import yaml
from src.translation_engine.reconstructor.markdown_reconstructor import MarkdownReconstructor
from src.translation_engine.extractor import Segment, SegmentContext, SegmentContextType
from src.utils.models import SiteProfile, FrontmatterRule, FrontmatterMode

# Create a minimal site profile matching products.aspose.net
profile_data = {
    "site_id": "test.site",
    "frontmatter": {
        "title": {"mode": "translate"},
        "description": {"mode": "translate"},
        "body.block.title_left": {"mode": "translate"},
        "body.block.title_right": {"mode": "translate"},
        "body.block.content_left": {"mode": "translate"},
        "faq.list.question": {"mode": "translate"},
        "faq.list.answer": {"mode": "translate"},
    },
    "body": {"translate_markdown": True}
}

# Convert to SiteProfile object
from src.utils.models import BodyRules

site_profile = SiteProfile(
    site_id="test.site",
    content_roots=["/test"],
    default_source_lang="en",
    target_langs=["es"],
    body=BodyRules(translate_markdown=True),
    frontmatter={
        "title": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
        "description": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
        "body.block.title_left": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
        "body.block.title_right": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
        "body.block.content_left": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
        "faq.list.question": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
        "faq.list.answer": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
    }
)

# Original frontmatter (simulating the source document)
original_fm = {
    "title": "Original Title",
    "description": "Original Description",
    "body": {
        "enable": True,
        "block": [
            {
                "title_left": "First Left Title",
                "title_right": "First Right Title",
                "content_left": "First left content"
            },
            {
                "title_left": "Second Left Title",
                "title_right": "Second Right Title",
                "content_left": "Second left content"
            }
        ]
    },
    "faq": {
        "enable": True,
        "list": [
            {"question": "Question 1?", "answer": "Answer 1"},
            {"question": "Question 2?", "answer": "Answer 2"}
        ]
    }
}

# Create segment IDs and translations (simulating translated segments)
def create_segment_id(text: str, key: str, site_id: str) -> str:
    """Simplified segment ID creation."""
    context = SegmentContext(
        context_type=SegmentContextType.FRONTMATTER,
        frontmatter_key=key,
    )
    return Segment.create_id(text, context, site_id)

translations = {
    create_segment_id("Original Title", "title", "test.site"): "Título Original",
    create_segment_id("Original Description", "description", "test.site"): "Descripción Original",
    create_segment_id("First Left Title", "body.block[0].title_left", "test.site"): "Primer Título Izquierdo",
    create_segment_id("First Right Title", "body.block[0].title_right", "test.site"): "Primer Título Derecho",
    create_segment_id("First left content", "body.block[0].content_left", "test.site"): "Primer contenido izquierdo",
    create_segment_id("Second Left Title", "body.block[1].title_left", "test.site"): "Segundo Título Izquierdo",
    create_segment_id("Second Right Title", "body.block[1].title_right", "test.site"): "Segundo Título Derecho",
    create_segment_id("Second left content", "body.block[1].content_left", "test.site"): "Segundo contenido izquierdo",
    create_segment_id("Question 1?", "faq.list[0].question", "test.site"): "¿Pregunta 1?",
    create_segment_id("Answer 1", "faq.list[0].answer", "test.site"): "Respuesta 1",
    create_segment_id("Question 2?", "faq.list[1].question", "test.site"): "¿Pregunta 2?",
    create_segment_id("Answer 2", "faq.list[1].answer", "test.site"): "Respuesta 2",
}

# Test reconstruction
print("Testing nested array reconstruction...")
print("=" * 60)

reconstructor = MarkdownReconstructor(site_profile)
result = reconstructor.reconstruct_frontmatter(original_fm, translations, "es")

print("\nOriginal frontmatter:")
print(yaml.dump(original_fm, allow_unicode=True, default_flow_style=False))

print("\nReconstructed frontmatter:")
print(yaml.dump(result, allow_unicode=True, default_flow_style=False))

# Verify translations were applied
print("\n" + "=" * 60)
print("Verification:")
print("=" * 60)

assert result["title"] == "Título Original", "Title not translated"
print("[PASS] Title translated correctly")

assert result["description"] == "Descripción Original", "Description not translated"
print("[PASS] Description translated correctly")

assert result["body"]["block"][0]["title_left"] == "Primer Título Izquierdo", "First block title_left not translated"
print("[PASS] First block title_left translated correctly")

assert result["body"]["block"][0]["title_right"] == "Primer Título Derecho", "First block title_right not translated"
print("[PASS] First block title_right translated correctly")

assert result["body"]["block"][1]["title_left"] == "Segundo Título Izquierdo", "Second block title_left not translated"
print("[PASS] Second block title_left translated correctly")

assert result["faq"]["list"][0]["question"] == "¿Pregunta 1?", "First FAQ question not translated"
print("[PASS] First FAQ question translated correctly")

assert result["faq"]["list"][1]["answer"] == "Respuesta 2", "Second FAQ answer not translated"
print("[PASS] Second FAQ answer translated correctly")

print("\n" + "=" * 60)
print("All reconstruction tests passed!")
print("=" * 60)
