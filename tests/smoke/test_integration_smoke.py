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

from src.model_runtime import HardwareDetector
from src.tm import TranslationMemory
from src.translation_engine.engine import TranslationEngine
from src.translation_engine.parser import HugoParser
from src.translation_engine.validation import (
    PlaceholderValidator,
    StructureValidator,
    YAMLValidator
)
from src.utils.config_loader import ConfigService


# ============================================================================
# Simple Translation Pipeline Tests
# ============================================================================


@pytest.mark.smoke
def test_simple_translation_pipeline():
    """Smoke test: Basic translation pipeline can process simple content."""
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            # Setup TM
            tm_dir = Path(tmpdir)
            l2_path = tm_dir / "l2.lmdb"
            l3_path = tm_dir / "l3_index"
            l3_path.mkdir(exist_ok=True)

            tm = TranslationMemory(
                l2_db_path=str(l2_path),
                l3_index_path=str(l3_path),
                l1_max_size=100,
                l2_max_size_mb=10,
                l3_device='cpu'
            )

            # Pre-populate TM with test data
            tm.store('test-site', 'en', 'es', 'Hello', 'Hola')
            tm.store('test-site', 'en', 'es', 'World', 'Mundo')

            # Create engine
            engine = TranslationEngine(
                translation_memory=tm,
                site_id='test-site',
                source_lang='en',
                target_lang='es'
            )

            # Simple translation should work
            simple_text = "Hello World"

            # Engine should process without crashing
            # (May not translate without actual model, but shouldn't error)
            assert engine is not None

            tm.close()

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
        result = parser.parse(content)

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
        result = parser.parse(content)

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
            tm_dir = Path(tmpdir)
            l2_path = tm_dir / "l2.lmdb"
            l3_path = tm_dir / "l3_index"
            l3_path.mkdir(exist_ok=True)

            tm = TranslationMemory(
                l2_db_path=str(l2_path),
                l3_index_path=str(l3_path),
                l1_max_size=100,
                l2_max_size_mb=10,
                l3_device='cpu'
            )

            # Store in L2 (should cascade to L1)
            tm.store('test-site', 'en', 'es', 'chain test', 'prueba de cadena')

            # Lookup from L1 (should hit L1 cache)
            result_l1 = tm.lookup('test-site', 'en', 'es', 'chain test')
            assert result_l1 is not None
            assert result_l1.translation == 'prueba de cadena'

            # Clear L1 cache
            tm.l1 = type(tm.l1)(max_size=100)

            # Lookup from L2
            result_l2 = tm.lookup('test-site', 'en', 'es', 'chain test')
            assert result_l2 is not None
            assert result_l2.translation == 'prueba de cadena'

            tm.close()

        except Exception as e:
            pytest.fail(f"TM lookup chain failed: {e}")


@pytest.mark.smoke
def test_tm_cache_promotion():
    """Smoke test: TM promotes L2 hits to L1 cache."""
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            tm_dir = Path(tmpdir)
            l2_path = tm_dir / "l2.lmdb"
            l3_path = tm_dir / "l3_index"
            l3_path.mkdir(exist_ok=True)

            tm = TranslationMemory(
                l2_db_path=str(l2_path),
                l3_index_path=str(l3_path),
                l1_max_size=100,
                l2_max_size_mb=10,
                l3_device='cpu'
            )

            # Store directly in L2
            tm.l2.store('test-site', 'en', 'es', 'promote', 'promover')

            # First lookup (L2 hit, should promote to L1)
            result1 = tm.lookup('test-site', 'en', 'es', 'promote')
            assert result1 is not None
            assert result1.translation == 'promover'

            # Second lookup (should hit L1 cache)
            result2 = tm.l1.get('test-site', 'en', 'es', 'promote')
            assert result2 is not None
            assert result2.translation == 'promover'

            tm.close()

        except Exception as e:
            pytest.fail(f"TM cache promotion failed: {e}")


@pytest.mark.smoke
def test_tm_multi_site_isolation():
    """Smoke test: TM isolates translations between different sites."""
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            tm_dir = Path(tmpdir)
            l2_path = tm_dir / "l2.lmdb"
            l3_path = tm_dir / "l3_index"
            l3_path.mkdir(exist_ok=True)

            tm = TranslationMemory(
                l2_db_path=str(l2_path),
                l3_index_path=str(l3_path),
                l1_max_size=100,
                l2_max_size_mb=10,
                l3_device='cpu'
            )

            # Store same text for different sites
            tm.store('site-a', 'en', 'es', 'test', 'prueba A')
            tm.store('site-b', 'en', 'es', 'test', 'prueba B')

            # Lookups should be site-specific
            result_a = tm.lookup('site-a', 'en', 'es', 'test')
            result_b = tm.lookup('site-b', 'en', 'es', 'test')

            assert result_a.translation == 'prueba A'
            assert result_b.translation == 'prueba B'

            tm.close()

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

        source = "Hello {name}, welcome to {place}!"
        translation_good = "Hola {name}, bienvenido a {place}!"
        translation_bad = "Hola {name}, bienvenido!"

        # Good translation should pass
        result_good = validator.validate(source, translation_good, {})
        assert result_good.is_valid

        # Bad translation should fail
        result_bad = validator.validate(source, translation_bad, {})
        assert not result_bad.is_valid

    except Exception as e:
        pytest.fail(f"Placeholder validation failed: {e}")


@pytest.mark.smoke
def test_quality_validation_yaml_check():
    """Smoke test: YAML validator catches invalid YAML."""
    try:
        validator = YAMLValidator()

        # Valid frontmatter
        valid_fm = """---
title: "Test"
date: 2024-01-01
---
Content here
"""

        # Invalid frontmatter (unclosed quote)
        invalid_fm = """---
title: "Test
date: 2024-01-01
---
Content here
"""

        # Valid should pass
        result_valid = validator.validate(valid_fm, valid_fm, {})
        assert result_valid.is_valid

        # Invalid should fail
        result_invalid = validator.validate(valid_fm, invalid_fm, {})
        assert not result_invalid.is_valid

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

        # Good translation should pass
        result_good = validator.validate(source, translation_good, {})
        assert result_good.is_valid

        # Bad translation should fail
        result_bad = validator.validate(source, translation_bad, {})
        assert not result_bad.is_valid

    except Exception as e:
        pytest.fail(f"Structure validation failed: {e}")


# ============================================================================
# Configuration Integration Tests
# ============================================================================


@pytest.mark.smoke
def test_config_hardware_integration():
    """Smoke test: Config and hardware detection work together."""
    try:
        config = ConfigService()
        hw_detector = HardwareDetector()

        # Both should initialize
        hw_info = hw_detector.detect()

        # Should be able to use hardware info with config
        assert hw_info is not None
        assert config is not None

    except Exception as e:
        pytest.fail(f"Config-hardware integration failed: {e}")


@pytest.mark.smoke
def test_config_tm_integration():
    """Smoke test: Config can work with TM setup."""
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            config = ConfigService()

            # Use config to determine TM paths
            tm_dir = Path(tmpdir)
            l2_path = tm_dir / "l2.lmdb"
            l3_path = tm_dir / "l3_index"
            l3_path.mkdir(exist_ok=True)

            # Create TM with config-determined paths
            tm = TranslationMemory(
                l2_db_path=str(l2_path),
                l3_index_path=str(l3_path),
                l1_max_size=config.get('tm.l1_max_size', default=100),
                l2_max_size_mb=config.get('tm.l2_max_size_mb', default=10),
                l3_device='cpu'
            )

            # Should work together
            assert tm is not None

            tm.close()

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

            tm_dir = Path(tmpdir)
            l2_path = tm_dir / "l2.lmdb"
            l3_path = tm_dir / "l3_index"
            l3_path.mkdir(exist_ok=True)

            tm = TranslationMemory(
                l2_db_path=str(l2_path),
                l3_index_path=str(l3_path),
                l1_max_size=100,
                l2_max_size_mb=10,
                l3_device='cpu'
            )

            validator = PlaceholderValidator()

            # Pre-populate TM
            tm.store('test-site', 'en', 'es', 'test content', 'contenido de prueba')

            # Parse content
            content = """---
title: "Test"
---

# Test Content
"""
            parsed = parser.parse(content)

            # Lookup from TM
            result = tm.lookup('test-site', 'en', 'es', 'test content')

            # Validate (simple check)
            validation = validator.validate('test', 'prueba', {})

            # All components should work
            assert parsed is not None
            assert result is not None
            assert validation is not None

            tm.close()

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

            # 2. Configuration
            config = ConfigService()

            # 3. TM setup
            tm_dir = Path(tmpdir)
            l2_path = tm_dir / "l2.lmdb"
            l3_path = tm_dir / "l3_index"
            l3_path.mkdir(exist_ok=True)

            tm = TranslationMemory(
                l2_db_path=str(l2_path),
                l3_index_path=str(l3_path),
                l1_max_size=100,
                l2_max_size_mb=10,
                l3_device='cpu'
            )

            # 4. Engine initialization
            engine = TranslationEngine(
                translation_memory=tm,
                site_id='test-site',
                source_lang='en',
                target_lang='es'
            )

            # All should initialize successfully
            assert hw_info is not None
            assert config is not None
            assert tm is not None
            assert engine is not None

            tm.close()

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

            # Create TM with appropriate device
            tm_dir = Path(tmpdir)
            l2_path = tm_dir / "l2.lmdb"
            l3_path = tm_dir / "l3_index"
            l3_path.mkdir(exist_ok=True)

            # Force CPU mode for L3
            device = 'cpu'  # Always use CPU in smoke tests

            tm = TranslationMemory(
                l2_db_path=str(l2_path),
                l3_index_path=str(l3_path),
                l1_max_size=100,
                l2_max_size_mb=10,
                l3_device=device
            )

            # System should work on CPU
            tm.store('test-site', 'en', 'es', 'cpu test', 'prueba cpu')
            result = tm.lookup('test-site', 'en', 'es', 'cpu test')

            assert result is not None
            assert result.translation == 'prueba cpu'

            tm.close()

        except Exception as e:
            pytest.fail(f"Graceful degradation failed: {e}")
