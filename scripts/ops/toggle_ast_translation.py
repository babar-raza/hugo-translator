#!/usr/bin/env python3
"""
Toggle AST-based translation feature for site profiles.

This script enables or disables the AST-based translation feature
for one or more site profiles by modifying their YAML configuration files.

Usage:
    # Enable for specific site
    python toggle_ast_translation.py --site products.aspose.net --enable

    # Disable for specific site
    python toggle_ast_translation.py --site products.aspose.net --disable

    # Enable for all sites
    python toggle_ast_translation.py --all-sites --enable

    # Check status of all sites
    python toggle_ast_translation.py --status
"""

import argparse
import sys
from pathlib import Path

import yaml


def find_site_profiles(config_dir: Path) -> list[Path]:
    """Find all site profile YAML files."""
    return list(config_dir.glob("*.yaml"))


def load_site_profile(profile_path: Path) -> dict:
    """Load a site profile YAML file."""
    with open(profile_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_site_profile(profile_path: Path, config: dict) -> None:
    """Save a site profile YAML file."""
    with open(profile_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, default_flow_style=False, sort_keys=False, allow_unicode=True)


def toggle_ast_translation(profile_path: Path, enable: bool, dry_run: bool = False) -> bool:
    """
    Toggle AST translation feature for a site profile.

    Args:
        profile_path: Path to site profile YAML file
        enable: True to enable, False to disable
        dry_run: If True, don't actually modify the file

    Returns:
        True if changes were made, False if already in desired state
    """
    config = load_site_profile(profile_path)

    # Ensure body section exists
    if "body" not in config:
        config["body"] = {}

    body = config["body"]
    current_value = body.get("use_ast_body_reconstruction", False)

    # Check if already in desired state
    if current_value == enable:
        return False

    # Update the flag
    body["use_ast_body_reconstruction"] = enable

    # Ensure other AST settings exist with defaults (only if enabling)
    if enable:
        if "ast_segmentation_strategy" not in body:
            body["ast_segmentation_strategy"] = "adaptive"
        if "ast_batch_size" not in body:
            body["ast_batch_size"] = 50

    # Save changes
    if not dry_run:
        save_site_profile(profile_path, config)

    return True


def get_ast_status(profile_path: Path) -> dict[str, any]:
    """
    Get AST translation status for a site profile.

    Returns:
        Dict with status information
    """
    config = load_site_profile(profile_path)
    body = config.get("body", {})

    return {
        "site_id": config.get("site_id", profile_path.stem),
        "enabled": body.get("use_ast_body_reconstruction", False),
        "strategy": body.get("ast_segmentation_strategy", "N/A"),
        "batch_size": body.get("ast_batch_size", "N/A"),
    }


def print_status(status_list: list[dict]) -> None:
    """Print status of multiple sites in a formatted table."""
    print(
        "\n{:<30} {:<12} {:<15} {:<12}".format("Site ID", "AST Enabled", "Strategy", "Batch Size")
    )
    print("-" * 70)

    enabled_count = 0
    for status in sorted(status_list, key=lambda x: x["site_id"]):
        enabled = status["enabled"]
        enabled_count += 1 if enabled else 0
        enabled_str = "ENABLED" if enabled else "disabled"

        print(
            "{:<30} {:<12} {:<15} {:<12}".format(
                status["site_id"],
                enabled_str,
                status["strategy"] if enabled else "N/A",
                str(status["batch_size"]) if enabled else "N/A",
            )
        )

    print("-" * 70)
    print(
        f"Total: {len(status_list)} sites, {enabled_count} enabled, {len(status_list) - enabled_count} disabled\n"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Toggle AST-based translation feature for site profiles",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument("--site", type=str, help="Site ID to modify (e.g., products.aspose.net)")

    parser.add_argument("--all-sites", action="store_true", help="Apply to all site profiles")

    parser.add_argument("--enable", action="store_true", help="Enable AST translation")

    parser.add_argument("--disable", action="store_true", help="Disable AST translation")

    parser.add_argument(
        "--status", action="store_true", help="Show status of all sites (no modifications)"
    )

    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be changed without making changes"
    )

    parser.add_argument(
        "--config-dir",
        type=Path,
        default=Path("config/site_profiles"),
        help="Path to site profiles directory (default: config/site_profiles)",
    )

    args = parser.parse_args()

    # Validate arguments
    if not args.status:
        if args.enable and args.disable:
            print("ERROR: Cannot specify both --enable and --disable")
            sys.exit(1)

        if not args.enable and not args.disable:
            print("ERROR: Must specify either --enable or --disable (or --status to view)")
            sys.exit(1)

        if not args.site and not args.all_sites:
            print("ERROR: Must specify either --site or --all-sites")
            sys.exit(1)

    # Ensure config directory exists
    if not args.config_dir.exists():
        print(f"ERROR: Config directory not found: {args.config_dir}")
        sys.exit(1)

    # Find all site profiles
    all_profiles = find_site_profiles(args.config_dir)

    if not all_profiles:
        print(f"ERROR: No site profiles found in {args.config_dir}")
        sys.exit(1)

    # Status mode: Show status and exit
    if args.status:
        status_list = [get_ast_status(profile) for profile in all_profiles]
        print_status(status_list)
        sys.exit(0)

    # Determine which profiles to modify
    if args.all_sites:
        target_profiles = all_profiles
    else:
        # Find specific site
        target_profile = args.config_dir / f"{args.site}.yaml"
        if not target_profile.exists():
            print(f"ERROR: Site profile not found: {target_profile}")
            print("\nAvailable sites:")
            for profile in sorted(all_profiles):
                print(f"  - {profile.stem}")
            sys.exit(1)
        target_profiles = [target_profile]

    # Apply changes
    enable = args.enable
    action_word = "Enabling" if enable else "Disabling"
    dry_run_suffix = " (DRY RUN)" if args.dry_run else ""

    print(f"\n{action_word} AST translation{dry_run_suffix}...")
    print("-" * 70)

    modified_count = 0
    unchanged_count = 0

    for profile in target_profiles:
        site_id = profile.stem
        changed = toggle_ast_translation(profile, enable, dry_run=args.dry_run)

        if changed:
            status = "OK" if not args.dry_run else "DRY"
            print(
                f"{status} {site_id:<40} {'WOULD BE ' if args.dry_run else ''}{'ENABLED' if enable else 'DISABLED'}"
            )
            modified_count += 1
        else:
            already_status = "already enabled" if enable else "already disabled"
            print(f"  {site_id:<40} (unchanged - {already_status})")
            unchanged_count += 1

    print("-" * 70)
    print(f"\nSummary: {modified_count} modified, {unchanged_count} unchanged")

    if args.dry_run and modified_count > 0:
        print("\nWARNING: This was a DRY RUN. No files were actually modified.")
        print("Run without --dry-run to apply changes.")
    elif modified_count > 0:
        print(
            f"\nChanges saved. AST translation {'enabled' if enable else 'disabled'} for {modified_count} site(s)."
        )

        if enable:
            print("\nNext steps:")
            print("  1. Test translations on enabled site(s)")
            print("  2. Monitor telemetry (ast_translation_* metrics)")
            print("  3. Check logs for errors or warnings")
            print("  4. Verify translation quality with spot checks")
            print("\nSee docs/ast_translation_rollout.md for detailed rollout procedures.")
        else:
            print("\nAST translation disabled. Sites will use legacy reconstruction.")

    sys.exit(0)


if __name__ == "__main__":
    main()
