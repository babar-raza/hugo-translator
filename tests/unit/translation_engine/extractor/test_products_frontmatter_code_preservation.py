from pathlib import Path

from src.translation_engine.extractor.segment_extractor import SegmentExtractor
from src.utils.config_loader import ConfigService


def test_products_frontmatter_preserves_fenced_code_before_mt():
    profile = ConfigService(config_root=Path("config")).get_site_profile("products.aspose.org")
    extractor = SegmentExtractor(profile)
    frontmatter = {
        "single": {
            "block": [
                {
                    "content": (
                        "Install the package, then run:\n\n"
                        "```java\n"
                        "import com.aspose.threed.*;\n"
                        "Scene scene = Scene.fromFile(\"model.obj\");\n"
                        "scene.save(\"model.gltf\");\n"
                        "```\n"
                    )
                }
            ]
        }
    }

    segments = extractor.extract_from_frontmatter(frontmatter, "en")

    assert len(segments) == 1
    assert "{PLACEHOLDER_0}" in segments[0].source_text
    assert "import com.aspose.threed" not in segments[0].source_text
    assert segments[0].placeholder_map["{PLACEHOLDER_0}"].startswith("```java")


def test_products_frontmatter_preserves_inline_code_before_mt():
    profile = ConfigService(config_root=Path("config")).get_site_profile("products.aspose.org")
    extractor = SegmentExtractor(profile)
    frontmatter = {
        "overview": {
            "content": "Use `Scene.fromFile(\"model.obj\")` and save the result."
        }
    }

    segments = extractor.extract_from_frontmatter(frontmatter, "en")

    assert len(segments) == 1
    assert "{PLACEHOLDER_0}" in segments[0].source_text
    assert "Scene.fromFile" not in segments[0].source_text
    assert segments[0].placeholder_map["{PLACEHOLDER_0}"] == '`Scene.fromFile("model.obj")`'
