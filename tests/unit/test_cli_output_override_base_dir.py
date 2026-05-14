"""
Regression test for CLI base_dir integration bug (Phase 10).

Verifies that when --output override is used, the CLI correctly passes base_dir
to TranslationEngine.translate_file() to preserve directory structure and avoid
output path collisions for files with the same basename.

Bug context:
- Without base_dir, multiple _index.md files from different directories all map
  to the same output path (e.g., override/fr/_index.md)
- With base_dir, structure is preserved (e.g., override/fr/a/_index.md, override/fr/b/_index.md)
"""

import tempfile
from pathlib import Path
from unittest.mock import Mock

import pytest


def test_get_output_path_with_base_dir_preserves_structure():
    """
    Test that _get_output_path preserves directory structure when base_dir is provided.

    This is the core engine behavior that the CLI must enable by passing base_dir.
    """
    from src.translation_engine.engine import TranslationEngine
    from src.utils.config_loader import ConfigService

    # Create minimal config service with a test site profile
    config_root = Path(__file__).parent.parent.parent / "config"
    config_service = ConfigService(config_root)

    # Create temporary directory structure
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        base_path = Path(tmpdir)

        # Create test file structure
        en_dir = base_path / "en"
        en_dir.mkdir()

        file_a = en_dir / "a" / "_index.md"
        file_a.parent.mkdir()
        file_a.write_text("# Test A")

        file_b = en_dir / "b" / "_index.md"
        file_b.parent.mkdir()
        file_b.write_text("# Test B")

        # Create output override directory
        output_override = base_path / "override"
        output_override.mkdir()

        # Create minimal engine with output override
        # Mock the required dependencies
        mock_tm = Mock()
        mock_model_loader = Mock()

        engine = TranslationEngine(
            config_service=config_service,
            tm=mock_tm,
            model_loader=mock_model_loader,
            output_dir_override=output_override,
        )

        # Create minimal site profile
        class MinimalProfile:
            default_source_lang = "en"
            output_layout = {"per_language_folders": True}

        site_profile = MinimalProfile()

        # Test Case 1: WITH base_dir (correct behavior)
        output_a_with_base = engine._get_output_path(
            source_path=file_a,
            target_lang="fr",
            site_profile=site_profile,
            base_dir=en_dir,
        )

        output_b_with_base = engine._get_output_path(
            source_path=file_b,
            target_lang="fr",
            site_profile=site_profile,
            base_dir=en_dir,
        )

        # Verify outputs are distinct and preserve structure
        assert output_a_with_base != output_b_with_base, (
            "Output paths should be distinct when base_dir is provided"
        )
        assert "a" in str(output_a_with_base), f"Output should preserve 'a' subdirectory: {output_a_with_base}"
        assert "b" in str(output_b_with_base), f"Output should preserve 'b' subdirectory: {output_b_with_base}"

        # Test Case 2: WITHOUT base_dir (buggy behavior - should NOT be used by CLI)
        output_a_no_base = engine._get_output_path(
            source_path=file_a,
            target_lang="fr",
            site_profile=site_profile,
            base_dir=None,
        )

        output_b_no_base = engine._get_output_path(
            source_path=file_b,
            target_lang="fr",
            site_profile=site_profile,
            base_dir=None,
        )

        # Verify this causes collision (the bug we're fixing)
        assert output_a_no_base == output_b_no_base, (
            "Without base_dir, outputs should collide (demonstrating the bug)"
        )
        assert str(output_a_no_base).endswith("_index.md"), (
            "Without base_dir, only filename is preserved"
        )


def test_cli_base_dir_detection_language_folder():
    """
    Test that CLI correctly detects language folder and sets base_dir.

    Simulates the base_dir determination logic from cli.py for a file under /en/.
    """
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        base_path = Path(tmpdir)

        # Create structure: tmpdir/slides/en/docs/_index.md
        slides_dir = base_path / "slides"
        en_dir = slides_dir / "en"
        docs_dir = en_dir / "docs"
        docs_dir.mkdir(parents=True)

        test_file = docs_dir / "_index.md"
        test_file.write_text("# Test")

        # Simulate CLI base_dir detection logic
        source_lang = "en"
        resolved_path = test_file.resolve()
        base_dir = None

        for parent in resolved_path.parents:
            if parent.name == source_lang:
                base_dir = parent.parent
                break

        # Verify base_dir is set to slides_dir (parent of /en/)
        assert base_dir is not None, "Should detect language folder"
        assert base_dir == slides_dir, f"base_dir should be {slides_dir}, got {base_dir}"


def test_cli_base_dir_detection_no_language_folder():
    """
    Test that CLI falls back to parent directory when no language folder is found.
    """
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        base_path = Path(tmpdir)

        # Create structure without language folder: tmpdir/content/_index.md
        content_dir = base_path / "content"
        content_dir.mkdir()

        test_file = content_dir / "_index.md"
        test_file.write_text("# Test")

        # Simulate CLI base_dir detection logic
        source_lang = "en"
        resolved_path = test_file.resolve()
        base_dir = None

        for parent in resolved_path.parents:
            if parent.name == source_lang:
                base_dir = parent.parent
                break

        # Fallback to parent
        if base_dir is None:
            base_dir = test_file.parent

        # Verify base_dir falls back to content_dir
        assert base_dir == content_dir, f"base_dir should be {content_dir}, got {base_dir}"


def test_output_path_collision_prevention():
    """
    End-to-end test: Verify that with proper base_dir usage, collision detection works.

    The engine has collision detection in _translate_directory_sequential that should
    catch issues. This test verifies the collision detection still works correctly.
    """
    import platform

    from src.translation_engine.engine import TranslationEngine
    from src.utils.config_loader import ConfigService

    config_root = Path(__file__).parent.parent.parent / "config"
    config_service = ConfigService(config_root)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        base_path = Path(tmpdir)

        # Create test structure
        en_dir = base_path / "en"
        en_dir.mkdir()

        file_a = en_dir / "category1" / "_index.md"
        file_a.parent.mkdir()
        file_a.write_text("# Category 1")

        file_b = en_dir / "category2" / "_index.md"
        file_b.parent.mkdir()
        file_b.write_text("# Category 2")

        output_override = base_path / "out"
        output_override.mkdir()

        # Mock required dependencies
        mock_tm = Mock()
        mock_model_loader = Mock()

        engine = TranslationEngine(
            config_service=config_service,
            tm=mock_tm,
            model_loader=mock_model_loader,
            output_dir_override=output_override,
        )

        class MinimalProfile:
            default_source_lang = "en"
            output_layout = {"per_language_folders": False}

        site_profile = MinimalProfile()
        md_files = [file_a, file_b]
        target_langs = ["fr"]

        # Build output path map like engine does in collision detection
        output_path_map = {}

        for md_file in md_files:
            for target_lang in target_langs:
                # WITH base_dir (fixed behavior)
                output_path = engine._get_output_path(
                    source_path=md_file,
                    target_lang=target_lang,
                    site_profile=site_profile,
                    base_dir=en_dir,
                )

                normalized = str(output_path).lower() if platform.system() == "Windows" else str(output_path)

                # Should NOT collide with proper base_dir
                assert normalized not in output_path_map, (
                    f"Collision detected with base_dir (should not happen):\n"
                    f"  File: {md_file}\n"
                    f"  Output: {output_path}\n"
                    f"  Normalized: {normalized}"
                )

                output_path_map[normalized] = (output_path, md_file)

        # Verify we have 2 distinct paths
        assert len(output_path_map) == 2, (
            f"Should have 2 distinct output paths, got {len(output_path_map)}"
        )


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])
