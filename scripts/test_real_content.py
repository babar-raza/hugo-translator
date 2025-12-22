#!/usr/bin/env python3
"""
Test HP fixes on real production content.
"""
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import after path is set
from src.translation_engine.parser.hugo_parser import HugoParser
from src.translation_engine.extractor.segment_extractor import SegmentExtractor
from src.translation_engine.reconstructor.markdown_reconstructor import MarkdownReconstructor
from src.utils.config_loader import ConfigService

def translate_file(input_file: Path, output_file: Path, site_id: str, target_lang: str):
    """
    Translate a single file using the translation pipeline.

    This is a simplified version that tests HP fixes without needing full TM/model setup.
    """
    # Load configuration
    config_service = ConfigService(Path("config"))
    site_profile = config_service.get_site_profile(site_id)

    # Read input
    with open(input_file, "r", encoding="utf-8") as f:
        content = f.read()

    # Parse
    parser = HugoParser(site_profile)
    parsed = parser.parse(content)

    # Extract segments
    extractor = SegmentExtractor(site_profile)
    segments = extractor.extract(parsed.body_ast)

    # For testing, just use English text as "translation"
    # This lets us verify HP fixes work without needing actual MT
    translations = {}
    for segment in segments:
        # Use the original text as "translation" for structure validation
        translations[segment.id] = segment.text

    # Reconstruct
    reconstructor = MarkdownReconstructor(site_profile)
    translated_body = reconstructor.reconstruct(
        parsed.body_ast,
        translations,
        target_lang,
        segments
    )

    # Handle frontmatter (keep original for this test)
    translated_frontmatter = parsed.frontmatter

    # Build final content
    frontmatter_str = "---\n"
    for key, value in translated_frontmatter.items():
        if isinstance(value, list):
            frontmatter_str += f"{key}:\n"
            for item in value:
                frontmatter_str += f"  - {item}\n"
        else:
            frontmatter_str += f"{key}: {value}\n"
    frontmatter_str += "---\n\n"

    final_content = frontmatter_str + translated_body

    # Write output
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(final_content)

    print(f"✓ Translated: {input_file.name}")
    print(f"  Segments: {len(segments)}")
    print(f"  Output: {output_file}")

def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Test HP fixes on real content")
    parser.add_argument("--input", type=Path, required=True, help="Input file or directory")
    parser.add_argument("--output", type=Path, required=True, help="Output file or directory")
    parser.add_argument("--site-id", default="kb.aspose.net", help="Site ID")
    parser.add_argument("--target", default="de", help="Target language")

    args = parser.parse_args()

    # Handle single file or directory
    if args.input.is_file():
        translate_file(args.input, args.output, args.site_id, args.target)
    else:
        # Process all markdown files in directory
        input_files = list(args.input.rglob("*.md"))
        print(f"Found {len(input_files)} files to process\n")

        for input_file in input_files:
            # Calculate relative path and create output path
            rel_path = input_file.relative_to(args.input)
            output_file = args.output / rel_path

            try:
                translate_file(input_file, output_file, args.site_id, args.target)
            except Exception as e:
                print(f"✗ Failed: {input_file.name}")
                print(f"  Error: {e}")

        print(f"\n{'='*60}")
        print(f"Processing complete: {len(input_files)} files")
        print(f"{'='*60}")

if __name__ == "__main__":
    main()
