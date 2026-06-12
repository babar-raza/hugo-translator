#!/usr/bin/env python3
"""
Migration script to convert legacy filter.json to new site profile YAML format.
"""

import json
import sys
from pathlib import Path
from typing import Any

import yaml

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from utils.config_loader import ConfigLoadError, ConfigService
from utils.models import (
    BodyRules,
    FrontmatterMode,
    FrontmatterRule,
    OutputLayout,
    SiteProfile,
    TMPreferences,
)

DEFAULT_TARGET_LANGS = ["de", "es", "fr", "ja", "ko", "ru", "zh", "ar", "it", "pt"]

CONTENT_ROOTS_MAP = {
    "products.aspose.net": ["/content/products.aspose.net"],
    "docs.aspose.net": ["/content/docs.aspose.net"],
    "blog.aspose.net": ["/content/blog.aspose.net"],
    "kb.aspose.net": ["/content/kb.aspose.net"],
    "reference.aspose.net": ["/content/reference.aspose.net"],
    "websites.aspose.net": ["/content/websites.aspose.net"],
    "www.aspose.net": ["/content/www.aspose.net"],
    "about.aspose.net": ["/content/about.aspose.net"],
}


def convert_metadata_to_frontmatter(metadata_fields: list[str]) -> dict[str, FrontmatterRule]:
    """Convert legacy metadata field list to frontmatter rules."""
    frontmatter = {}

    for field in metadata_fields:
        if ".list." in field or field.endswith("s.items") or field.endswith("s.points"):
            mode = FrontmatterMode.TRANSLATE_LIST
        else:
            mode = FrontmatterMode.TRANSLATE
        frontmatter[field] = FrontmatterRule(mode=mode)

    # Add common passthrough fields
    for pf in ["draft", "date", "type", "layout", "url", "slug"]:
        if pf not in frontmatter:
            frontmatter[pf] = FrontmatterRule(mode=FrontmatterMode.PASSTHROUGH)

    return frontmatter


def convert_ast_to_body_rules(ast_config: dict[str, Any]) -> BodyRules:
    """Convert legacy AST configuration to new BodyRules."""
    preserve_blocks = ast_config.get("excludeAncestors", [])
    preserve_patterns = ast_config.get("excludePatterns", [])
    placeholder_syntax = [
        r"\{\{<.*?>\}\}",
        r"\{\{%.*?%\}\}",
    ]

    return BodyRules(
        translate_markdown=True,
        preserve_blocks=preserve_blocks,
        preserve_patterns=preserve_patterns,
        placeholder_syntax=placeholder_syntax,
    )


def migrate_site(site_id: str, legacy_config: dict[str, Any], output_dir: Path) -> bool:
    """Migrate a single site configuration."""
    try:
        metadata_fields = legacy_config.get("metadata", [])
        frontmatter = convert_metadata_to_frontmatter(metadata_fields)

        ast_config = legacy_config.get("ast", {})
        body_rules = convert_ast_to_body_rules(ast_config)

        content_roots = CONTENT_ROOTS_MAP.get(site_id, [f"/content/{site_id}"])

        profile = SiteProfile(
            site_id=site_id,
            content_roots=content_roots,
            default_source_lang="en",
            target_langs=DEFAULT_TARGET_LANGS,
            frontmatter=frontmatter,
            body=body_rules,
            output_layout=OutputLayout(per_language_folders=True, pattern="{lang}/{path}"),
            tm_prefs=TMPreferences(use_semantic_tm=True, min_similarity_score=0.8),
        )

        profile_dict = profile.model_dump()

        output_file = output_dir / f"{site_id}.yaml"
        with open(output_file, "w", encoding="utf-8") as f:
            yaml.dump(
                profile_dict, f, default_flow_style=False, sort_keys=False, allow_unicode=True
            )

        print(f"[OK] Migrated {site_id} -> {output_file.name}")
        print(f"  - {len(frontmatter)} frontmatter rules")
        print(f"  - {len(body_rules.preserve_blocks)} preserve blocks")

        return True
    except Exception as e:
        print(f"[FAIL] Failed to migrate {site_id}: {e}", file=sys.stderr)
        return False


def main():
    """Main migration entry point."""
    script_dir = Path(__file__).parent.parent
    legacy_filter_path = script_dir / "legacy" / "filter.json"
    output_dir = script_dir / "config" / "site_profiles"

    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Reading legacy filter from: {legacy_filter_path}")
    try:
        with open(legacy_filter_path, encoding="utf-8") as f:
            legacy_data = json.load(f)
    except Exception as e:
        print(f"Error reading legacy filter.json: {e}", file=sys.stderr)
        sys.exit(1)

    site_configs = {k: v for k, v in legacy_data.items() if not k.startswith("_")}

    print(f"\nFound {len(site_configs)} sites to migrate")
    print(f"Migrating to: {output_dir}\n")

    success_count = 0
    failed_count = 0

    for site_id, config in site_configs.items():
        if migrate_site(site_id, config, output_dir):
            success_count += 1
        else:
            failed_count += 1

    print(f"\n{'=' * 60}")
    print(f"Migration complete: Success {success_count} | Failed {failed_count}")
    print(f"{'=' * 60}\n")

    if success_count > 0:
        print("Validating generated profiles...\n")
        try:
            service = ConfigService(script_dir / "config")
            errors = service.validate_all_profiles()

            if not errors:
                print("[OK] All generated profiles are valid!\n")
            else:
                print(f"[FAIL] Validation errors in {len(errors)} profile(s)\n")
                for site_id, error_list in errors.items():
                    print(f"  {site_id}: {error_list}")
        except ConfigLoadError as e:
            print(f"Warning: Could not validate: {e}\n")

    sys.exit(0 if failed_count == 0 else 1)


if __name__ == "__main__":
    main()
