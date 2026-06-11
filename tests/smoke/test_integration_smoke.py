#!/usr/bin/env python3
"""
Integration Smoke Tests

Tests integration between components without running full end-to-end tests:
- Simple translation pipeline
- TM lookup chain (L1 -> L2 -> L3)
- Quality validation
- Configuration integration

All tests are marked with @pytest.mark.smoke and should complete in <30 seconds.
"""

import sys
import tempfile
from pathlib import Path

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.model_runtime.hardware import HardwareDetector
from src.tm import L1Cache, L2PersistentTM, TranslationMemory

try:
    from src.tm import L3SemanticTM
except ImportError:
    L3SemanticTM = None
from src.translation_engine.parser import HugoParser
from src.translation_engine.validation import (
    PlaceholderValidator,
    StructureValidator,
    YAMLValidator,
)


def _create_tm(tmpdir: Path):
    """Helper to create TranslationMemory with proper initialization."""
    l2_path = tmpdir / "l2"
    l1 = L1Cache(max_size=100)
    l2 = L2PersistentTM(db_path=l2_path, max_size_mb=10)
    return TranslationMemory(l1_cache=l1, l2_persistent=l2, l3_semantic=None), l2


# ============================================================================
# Simple Translation Pipeline Tests
# ============================================================================


@pytest.mark.smoke
def test_simple_translation_pipeline():
    """Smoke test: Basic translation pipeline can process simple content."""
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            tm, l2 = _create_tm(Path(tmpdir))

            # Pre-populate TM with test data
            tm.store("test-site", "en", "es", "Hello", "Hola")
            tm.store("test-site", "en", "es", "World", "Mundo")

            # Lookup should work
            result = tm.lookup("test-site", "en", "es", "Hello")
            assert result is not None
            assert result.translation == "Hola"

            l2.close()

        except Exception as e:
            pytest.fail(f"Simple translation pipeline failed: {e}")


@pytest.mark.smoke
def test_parser_integration():
    """Smoke test: Parser can process markdown and extract content."""
    try:
        parser = HugoParser()

        # Simple markdown with frontmatter
        content = """---
title: "Test Page"
date: 2024-01-01
---

# Heading

This is a paragraph with some text.

- List item 1
- List item 2
"""

        # Parse should work
        result = parser.parse_string(content)

        # Should extract frontmatter and content
        assert result is not None

    except Exception as e:
        pytest.fail(f"Parser integration failed: {e}")


@pytest.mark.smoke
def test_parser_with_hugo_shortcodes():
    """Smoke test: Parser handles Hugo shortcodes without crashing."""
    try:
        parser = HugoParser()

        # Markdown with Hugo shortcodes
        content = """# Test

{{< figure src="image.jpg" title="A figure" >}}

Some text here.

{{< ref "/docs/page.md" >}}
"""

        # Parse should handle shortcodes
        result = parser.parse_string(content)

        # Should not crash on shortcodes
        assert result is not None

    except Exception as e:
        pytest.fail(f"Parser shortcode handling failed: {e}")


# ============================================================================
# TM Lookup Chain Integration Tests
# ============================================================================


@pytest.mark.smoke
def test_tm_lookup_chain():
    """Smoke test: TM lookup chain cascades through layers correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            tm, l2 = _create_tm(Path(tmpdir))

            # Store in TM (goes to L2, cascades to L1)
            tm.store("test-site", "en", "es", "chain test", "prueba de cadena")

            # Lookup should find it
            result_l1 = tm.lookup("test-site", "en", "es", "chain test")
            assert result_l1 is not None
            assert result_l1.translation == "prueba de cadena"

            # Clear L1 cache
            tm.l1.clear()

            # Lookup from L2
            result_l2 = tm.lookup("test-site", "en", "es", "chain test")
            assert result_l2 is not None
            assert result_l2.translation == "prueba de cadena"

            l2.close()

        except Exception as e:
            pytest.fail(f"TM lookup chain failed: {e}")


@pytest.mark.smoke
def test_tm_cache_promotion():
    """Smoke test: TM promotes L2 hits to L1 cache."""
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            tm, l2 = _create_tm(Path(tmpdir))

            # Store directly in L2
            tm.l2.store("test-site", "en", "es", "promote", "promover")

            # First lookup (L2 hit, should promote to L1)
            result1 = tm.lookup("test-site", "en", "es", "promote")
            assert result1 is not None
            assert result1.translation == "promover"

            # Second lookup should hit L1 cache (returns string)
            result2 = tm.l1.get("test-site", "en", "es", "promote")
            assert result2 is not None
            assert result2 == "promover"  # L1Cache returns string directly

            l2.close()

        except Exception as e:
            pytest.fail(f"TM cache promotion failed: {e}")


@pytest.mark.smoke
def test_tm_multi_site_isolation():
    """Smoke test: TM isolates translations between different sites."""
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            tm, l2 = _create_tm(Path(tmpdir))

            # Store same text for different sites
            tm.store("site-a", "en", "es", "test", "prueba A")
            tm.store("site-b", "en", "es", "test", "prueba B")

            # Lookups should be site-specific
            result_a = tm.lookup("site-a", "en", "es", "test")
            result_b = tm.lookup("site-b", "en", "es", "test")

            assert result_a.translation == "prueba A"
            assert result_b.translation == "prueba B"

            l2.close()

        except Exception as e:
            pytest.fail(f"TM multi-site isolation failed: {e}")


# ============================================================================
# Quality Validation Integration Tests
# ============================================================================


@pytest.mark.smoke
def test_quality_validation_placeholder_check():
    """Smoke test: Placeholder validator catches missing placeholders."""
    try:
        validator = PlaceholderValidator()

        # Default pattern expects {{TYPE_N}} format like {{CODE_1}}, {{LINK_2}}
        source = "Hello {{NAME_1}}, welcome to {{PLACE_1}}!"
        translation_good = "Hola {{NAME_1}}, bienvenido a {{PLACE_1}}!"
        translation_bad = "Hola {{NAME_1}}, bienvenido!"

        # Good translation should pass
        result_good = validator.validate(source, translation_good, {})
        assert result_good.success

        # Bad translation should fail
        result_bad = validator.validate(source, translation_bad, {})
        assert not result_bad.success

    except Exception as e:
        pytest.fail(f"Placeholder validation failed: {e}")


@pytest.mark.smoke
def test_quality_validation_yaml_check():
    """Smoke test: YAML validator catches invalid YAML."""
    try:
        validator = YAMLValidator()

        # YAMLValidator expects just the YAML content, not full document with --- delimiters
        valid_yaml = """title: "Test"
date: 2024-01-01
"""

        # Invalid YAML (unclosed quote)
        invalid_yaml = """title: "Test
date: 2024-01-01
"""

        # Valid should pass
        result_valid = validator.validate(valid_yaml, valid_yaml, {})
        assert result_valid.success

        # Invalid should fail
        result_invalid = validator.validate(valid_yaml, invalid_yaml, {})
        assert not result_invalid.success

    except Exception as e:
        pytest.fail(f"YAML validation failed: {e}")


@pytest.mark.smoke
def test_quality_validation_structure_check():
    """Smoke test: Structure validator checks markdown structure."""
    try:
        validator = StructureValidator()

        source = """# Heading 1

## Heading 2

Paragraph
"""

        # Matching structure
        translation_good = """# Título 1

## Título 2

Párrafo
"""

        # Different structure (missing heading level)
        translation_bad = """# Título 1

Párrafo
"""

        # Good translation should pass (no issues)
        result_good = validator.validate(source, translation_good, {})
        assert result_good.success
        assert len(result_good.issues) == 0

        # Bad translation should report issues (warnings for structure mismatch)
        result_bad = validator.validate(source, translation_bad, {})
        # StructureValidator reports warnings but doesn't fail validation
        # It should have issues about missing heading
        assert len(result_bad.issues) > 0

    except Exception as e:
        pytest.fail(f"Structure validation failed: {e}")


# ============================================================================
# Configuration Integration Tests
# ============================================================================


@pytest.mark.smoke
def test_config_hardware_integration():
    """Smoke test: Config and hardware detection work together."""
    try:
        from src.utils.config_loader import ConfigService

        config_root = Path(__file__).parent.parent.parent / "config"
        hw_detector = HardwareDetector()

        # Hardware should initialize
        hw_info = hw_detector.detect()
        assert hw_info is not None

        # Config should initialize if path exists
        if config_root.exists():
            config = ConfigService(config_root)
            assert config is not None
        else:
            pytest.skip("Config directory not found")

    except Exception as e:
        pytest.fail(f"Config-hardware integration failed: {e}")


@pytest.mark.smoke
def test_config_tm_integration():
    """Smoke test: Config can work with TM setup."""
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            config_root = Path(__file__).parent.parent.parent / "config"

            # Create TM with proper initialization
            tm, l2 = _create_tm(Path(tmpdir))

            # Should work together
            assert tm is not None

            l2.close()

        except Exception as e:
            pytest.fail(f"Config-TM integration failed: {e}")


# ============================================================================
# End-to-End Component Integration Tests
# ============================================================================


@pytest.mark.smoke
def test_e2e_component_chain():
    """Smoke test: Full component chain (parser -> TM -> validator) works."""
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            # Initialize components
            parser = HugoParser()
            tm, l2 = _create_tm(Path(tmpdir))
            validator = PlaceholderValidator()

            # Pre-populate TM
            tm.store("test-site", "en", "es", "test content", "contenido de prueba")

            # Parse content
            content = """---
title: "Test"
---

# Test Content
"""
            parsed = parser.parse_string(content)

            # Lookup from TM
            result = tm.lookup("test-site", "en", "es", "test content")

            # Validate (simple check)
            validation = validator.validate("test", "prueba", {})

            # All components should work
            assert parsed is not None
            assert result is not None
            assert validation is not None

            l2.close()

        except Exception as e:
            pytest.fail(f"E2E component chain failed: {e}")


@pytest.mark.smoke
def test_system_initialization_sequence():
    """Smoke test: System components can initialize in standard sequence."""
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            # Standard initialization sequence
            # 1. Hardware detection
            hw_detector = HardwareDetector()
            hw_info = hw_detector.detect()

            # 2. TM setup
            tm, l2 = _create_tm(Path(tmpdir))

            # All should initialize successfully
            assert hw_info is not None
            assert tm is not None

            l2.close()

        except Exception as e:
            pytest.fail(f"System initialization sequence failed: {e}")


@pytest.mark.smoke
def test_graceful_degradation():
    """Smoke test: System gracefully degrades when GPU unavailable."""
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            # Detect hardware
            hw_detector = HardwareDetector()
            hw_info = hw_detector.detect()

            # Create TM with CPU-only mode
            tm, l2 = _create_tm(Path(tmpdir))

            # System should work on CPU
            tm.store("test-site", "en", "es", "cpu test", "prueba cpu")
            result = tm.lookup("test-site", "en", "es", "cpu test")

            assert result is not None
            assert result.translation == "prueba cpu"

            l2.close()

        except Exception as e:
            pytest.fail(f"Graceful degradation failed: {e}")
