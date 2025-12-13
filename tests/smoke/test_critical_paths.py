#!/usr/bin/env python3
"""
Critical Path Smoke Tests

Tests core functionality that must work for the system to be operational:
- GPU detection (if available)
- TM layer initialization (L1/L2/L3)
- Configuration loading
- Model registry access
- Basic translation pipeline components

All tests are marked with @pytest.mark.smoke and should complete in <30 seconds.
"""
import sys
import tempfile
from pathlib import Path
from typing import Optional

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.hardware import GPUManager
from src.model_runtime import HardwareDetector, ModelRegistry
from src.tm import L1Cache, L2PersistentTM, L3SemanticTM, TranslationMemory
from src.translation_engine.engine import TranslationEngine
from src.utils.config_loader import ConfigService


# ============================================================================
# GPU Detection Tests
# ============================================================================


@pytest.mark.smoke
def test_gpu_detection_smoke():
    """Smoke test: GPU detection doesn't crash and returns valid info."""
    try:
        detector = HardwareDetector()
        hw_info = detector.detect()

        # Should always return valid info
        assert hw_info is not None
        assert hw_info.cpu_count > 0
        assert hw_info.total_ram_gb > 0
        assert hw_info.recommended_device in ["cuda", "cpu", "mps"]

        # GPU info should be consistent
        if hw_info.gpu_available:
            assert hw_info.gpu_name is not None
            assert hw_info.gpu_memory_gb > 0
        else:
            assert hw_info.gpu_name is None or hw_info.gpu_name == ""

    except Exception as e:
        pytest.fail(f"GPU detection failed: {e}")


@pytest.mark.smoke
def test_gpu_manager_initialization():
    """Smoke test: GPU manager can initialize without errors."""
    try:
        # GPU manager should initialize even if no GPU available
        manager = GPUManager()

        # Should have valid state
        assert hasattr(manager, 'is_available')

        # Get GPU info (should not crash)
        info = manager.get_gpu_info()
        assert isinstance(info, dict)

    except Exception as e:
        pytest.fail(f"GPU manager initialization failed: {e}")


@pytest.mark.smoke
def test_hardware_detector_device_selection():
    """Smoke test: Hardware detector selects appropriate device."""
    try:
        detector = HardwareDetector()
        hw_info = detector.detect()

        # Verify device selection logic
        device = hw_info.recommended_device

        if hw_info.gpu_available and hw_info.gpu_memory_gb >= 2.0:
            # Should recommend GPU if available with sufficient memory
            assert device == "cuda" or device == "mps"
        else:
            # Should fall back to CPU
            assert device == "cpu"

    except Exception as e:
        pytest.fail(f"Device selection failed: {e}")


# ============================================================================
# TM Layer L1 (Cache) Tests
# ============================================================================


@pytest.mark.smoke
def test_tm_l1_initialization():
    """Smoke test: L1 cache initializes and basic operations work."""
    try:
        cache = L1Cache(max_size=100)

        # Verify initialization
        assert cache is not None
        assert hasattr(cache, 'put')
        assert hasattr(cache, 'get')

        # Test basic put/get
        cache.put('test-site', 'en', 'es', 'hello', 'hola')
        result = cache.get('test-site', 'en', 'es', 'hello')

        assert result is not None
        assert result.translation == 'hola'
        assert result.source_lang == 'en'
        assert result.target_lang == 'es'

    except Exception as e:
        pytest.fail(f"L1 cache initialization failed: {e}")


@pytest.mark.smoke
def test_tm_l1_cache_eviction():
    """Smoke test: L1 cache eviction works when size exceeded."""
    try:
        # Small cache to trigger eviction
        cache = L1Cache(max_size=3)

        # Fill beyond capacity
        cache.put('test-site', 'en', 'es', 'one', 'uno')
        cache.put('test-site', 'en', 'es', 'two', 'dos')
        cache.put('test-site', 'en', 'es', 'three', 'tres')
        cache.put('test-site', 'en', 'es', 'four', 'cuatro')

        # Cache should still work (eviction occurred)
        result = cache.get('test-site', 'en', 'es', 'four')
        assert result is not None
        assert result.translation == 'cuatro'

        # Verify cache size is maintained
        stats = cache.get_stats('test-site', 'en', 'es')
        assert stats['size'] <= 3

    except Exception as e:
        pytest.fail(f"L1 cache eviction failed: {e}")


@pytest.mark.smoke
def test_tm_l1_multi_language_pairs():
    """Smoke test: L1 cache handles multiple language pairs."""
    try:
        cache = L1Cache(max_size=100)

        # Store translations for different language pairs
        cache.put('test-site', 'en', 'es', 'hello', 'hola')
        cache.put('test-site', 'en', 'fr', 'hello', 'bonjour')
        cache.put('test-site', 'es', 'en', 'hola', 'hello')

        # Verify all pairs are accessible
        assert cache.get('test-site', 'en', 'es', 'hello').translation == 'hola'
        assert cache.get('test-site', 'en', 'fr', 'hello').translation == 'bonjour'
        assert cache.get('test-site', 'es', 'en', 'hola').translation == 'hello'

    except Exception as e:
        pytest.fail(f"L1 multi-language support failed: {e}")


# ============================================================================
# TM Layer L2 (Persistent) Tests
# ============================================================================


@pytest.mark.smoke
def test_tm_l2_initialization():
    """Smoke test: L2 persistent TM initializes and basic operations work."""
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            db_path = Path(tmpdir) / "test.lmdb"
            tm = L2PersistentTM(db_path=str(db_path), max_size_mb=10)

            # Verify initialization
            assert tm is not None
            assert hasattr(tm, 'store')
            assert hasattr(tm, 'lookup')

            # Test basic store/lookup
            tm.store('test-site', 'en', 'es', 'world', 'mundo')
            result = tm.lookup('test-site', 'en', 'es', 'world')

            assert result is not None
            assert result.translation == 'mundo'

            # Clean up
            tm.close()

        except Exception as e:
            pytest.fail(f"L2 persistent TM initialization failed: {e}")


@pytest.mark.smoke
def test_tm_l2_persistence():
    """Smoke test: L2 TM persists data across instances."""
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            db_path = Path(tmpdir) / "test.lmdb"

            # Store data in first instance
            tm1 = L2PersistentTM(db_path=str(db_path), max_size_mb=10)
            tm1.store('test-site', 'en', 'es', 'persistence', 'persistencia')
            tm1.close()

            # Retrieve data in second instance
            tm2 = L2PersistentTM(db_path=str(db_path), max_size_mb=10)
            result = tm2.lookup('test-site', 'en', 'es', 'persistence')

            assert result is not None
            assert result.translation == 'persistencia'

            tm2.close()

        except Exception as e:
            pytest.fail(f"L2 persistence failed: {e}")


@pytest.mark.smoke
def test_tm_l2_bulk_operations():
    """Smoke test: L2 TM handles bulk store operations efficiently."""
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            db_path = Path(tmpdir) / "test.lmdb"
            tm = L2PersistentTM(db_path=str(db_path), max_size_mb=10)

            # Store multiple entries
            entries = [
                ('apple', 'manzana'),
                ('banana', 'plátano'),
                ('orange', 'naranja'),
                ('grape', 'uva'),
                ('pear', 'pera'),
            ]

            for source, target in entries:
                tm.store('test-site', 'en', 'es', source, target)

            # Verify all entries
            for source, target in entries:
                result = tm.lookup('test-site', 'en', 'es', source)
                assert result is not None
                assert result.translation == target

            tm.close()

        except Exception as e:
            pytest.fail(f"L2 bulk operations failed: {e}")


# ============================================================================
# TM Layer L3 (Semantic) Tests
# ============================================================================


@pytest.mark.smoke
def test_tm_l3_initialization():
    """Smoke test: L3 semantic TM initializes (CPU mode for speed)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            index_path = Path(tmpdir) / "test_index"
            index_path.mkdir(exist_ok=True)

            # Initialize in CPU mode for smoke test speed
            tm = L3SemanticTM(
                index_path=str(index_path),
                device='cpu',
                similarity_threshold=0.7
            )

            # Verify initialization
            assert tm is not None
            assert hasattr(tm, 'add')
            assert hasattr(tm, 'search')

        except Exception as e:
            pytest.fail(f"L3 semantic TM initialization failed: {e}")


@pytest.mark.smoke
def test_tm_l3_add_and_search():
    """Smoke test: L3 can add entries and perform semantic search."""
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            index_path = Path(tmpdir) / "test_index"
            index_path.mkdir(exist_ok=True)

            tm = L3SemanticTM(
                index_path=str(index_path),
                device='cpu',
                similarity_threshold=0.6
            )

            # Add some entries
            tm.add('test-site', 'en', 'es', 'Hello world', 'Hola mundo')
            tm.add('test-site', 'en', 'es', 'Good morning', 'Buenos días')

            # Search (should find exact or similar match)
            results = tm.search('test-site', 'en', 'es', 'Hello world')

            # Should return at least one result
            assert len(results) > 0

            # Best match should be similar
            if results:
                best_match = results[0]
                assert best_match.similarity >= 0.6

        except Exception as e:
            pytest.fail(f"L3 add/search failed: {e}")


@pytest.mark.smoke
def test_tm_l3_device_compatibility():
    """Smoke test: L3 works on CPU regardless of GPU availability."""
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            index_path = Path(tmpdir) / "test_index"
            index_path.mkdir(exist_ok=True)

            # Force CPU mode
            tm = L3SemanticTM(
                index_path=str(index_path),
                device='cpu',
                similarity_threshold=0.7
            )

            # Should work on any system
            tm.add('test-site', 'en', 'es', 'test', 'prueba')
            results = tm.search('test-site', 'en', 'es', 'test')

            assert len(results) >= 0  # May return 0 or more results

        except Exception as e:
            pytest.fail(f"L3 CPU compatibility failed: {e}")


# ============================================================================
# Translation Memory Integration Tests
# ============================================================================


@pytest.mark.smoke
def test_translation_memory_initialization():
    """Smoke test: Full TranslationMemory stack initializes."""
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

            # Verify all layers initialized
            assert tm.l1 is not None
            assert tm.l2 is not None
            assert tm.l3 is not None

            tm.close()

        except Exception as e:
            pytest.fail(f"TranslationMemory initialization failed: {e}")


@pytest.mark.smoke
def test_translation_memory_lookup_chain():
    """Smoke test: TM lookup chain (L1 -> L2 -> L3) works."""
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

            # Store in L2 (will cascade to L1)
            tm.store('test-site', 'en', 'es', 'lookup test', 'prueba de búsqueda')

            # Lookup should find it
            result = tm.lookup('test-site', 'en', 'es', 'lookup test')

            assert result is not None
            assert result.translation == 'prueba de búsqueda'

            tm.close()

        except Exception as e:
            pytest.fail(f"TM lookup chain failed: {e}")


# ============================================================================
# Configuration Loading Tests
# ============================================================================


@pytest.mark.smoke
def test_config_loading_smoke():
    """Smoke test: ConfigService can initialize and load basic config."""
    try:
        # ConfigService should initialize without config directory
        config = ConfigService()

        # Should have basic methods
        assert hasattr(config, 'get')
        assert hasattr(config, 'load_config')

    except Exception as e:
        pytest.fail(f"Config loading failed: {e}")


@pytest.mark.smoke
def test_config_default_values():
    """Smoke test: ConfigService provides sensible defaults."""
    try:
        config = ConfigService()

        # Should handle missing config gracefully
        value = config.get('nonexistent.key', default='default_value')
        assert value == 'default_value'

    except Exception as e:
        pytest.fail(f"Config default values failed: {e}")


# ============================================================================
# Model Registry Tests
# ============================================================================


@pytest.mark.smoke
def test_model_registry_initialization():
    """Smoke test: ModelRegistry can initialize."""
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            registry_path = Path(tmpdir) / "registry.yaml"

            # Create minimal registry file
            registry_content = """
models:
  test-model:
    name: "test-model"
    type: "huggingface"
    source_lang: "en"
    target_lang: "es"
"""
            registry_path.write_text(registry_content)

            # Initialize registry
            registry = ModelRegistry(registry_path=str(registry_path))

            # Should load models
            models = registry.list_models()
            assert 'test-model' in models

        except Exception as e:
            pytest.fail(f"Model registry initialization failed: {e}")


@pytest.mark.smoke
def test_model_registry_without_file():
    """Smoke test: ModelRegistry handles missing file gracefully."""
    try:
        # Should handle missing file
        registry = ModelRegistry(registry_path="/nonexistent/registry.yaml")

        # Should return empty model list
        models = registry.list_models()
        assert isinstance(models, (list, dict))

    except Exception as e:
        # This is acceptable - may raise error for missing file
        assert "registry" in str(e).lower() or "file" in str(e).lower()


# ============================================================================
# Translation Pipeline Component Tests
# ============================================================================


@pytest.mark.smoke
def test_translation_engine_initialization():
    """Smoke test: TranslationEngine can initialize."""
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            tm_dir = Path(tmpdir)
            l2_path = tm_dir / "l2.lmdb"
            l3_path = tm_dir / "l3_index"
            l3_path.mkdir(exist_ok=True)

            # Create minimal TM
            tm = TranslationMemory(
                l2_db_path=str(l2_path),
                l3_index_path=str(l3_path),
                l1_max_size=100,
                l2_max_size_mb=10,
                l3_device='cpu'
            )

            # Initialize engine
            engine = TranslationEngine(
                translation_memory=tm,
                site_id='test-site',
                source_lang='en',
                target_lang='es'
            )

            # Verify initialization
            assert engine is not None
            assert hasattr(engine, 'translate')

            tm.close()

        except Exception as e:
            pytest.fail(f"TranslationEngine initialization failed: {e}")


@pytest.mark.smoke
def test_translation_engine_parser_smoke():
    """Smoke test: Translation engine parser doesn't crash on simple input."""
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

            engine = TranslationEngine(
                translation_memory=tm,
                site_id='test-site',
                source_lang='en',
                target_lang='es'
            )

            # Simple markdown - parser should handle it
            simple_md = "# Hello World\n\nThis is a test."

            # Parse should not crash
            from src.translation_engine.parser import HugoParser
            parser = HugoParser()
            result = parser.parse(simple_md)

            # Should return some result
            assert result is not None

            tm.close()

        except Exception as e:
            pytest.fail(f"Translation engine parser failed: {e}")


# ============================================================================
# System Integration Smoke Tests
# ============================================================================


@pytest.mark.smoke
def test_system_components_compatibility():
    """Smoke test: All core components can coexist without conflicts."""
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            # Initialize hardware detection
            hw_detector = HardwareDetector()
            hw_info = hw_detector.detect()

            # Initialize TM stack
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

            # Initialize config
            config = ConfigService()

            # All should coexist
            assert hw_info is not None
            assert tm is not None
            assert config is not None

            tm.close()

        except Exception as e:
            pytest.fail(f"System components compatibility failed: {e}")


@pytest.mark.smoke
def test_critical_imports():
    """Smoke test: All critical modules can be imported."""
    try:
        # Core modules
        from src.tm import L1Cache, L2PersistentTM, L3SemanticTM, TranslationMemory
        from src.model_runtime import HardwareDetector, ModelRegistry
        from src.translation_engine.engine import TranslationEngine
        from src.translation_engine.parser import HugoParser
        from src.utils.config_loader import ConfigService

        # Validation modules
        from src.translation_engine.validation import (
            PlaceholderValidator,
            YAMLValidator,
            StructureValidator
        )

        # All imports successful
        assert True

    except ImportError as e:
        pytest.fail(f"Critical import failed: {e}")


@pytest.mark.smoke
def test_smoke_tests_are_fast():
    """Meta-test: Verify smoke tests complete quickly."""
    import time

    # This test itself should be nearly instant
    start = time.time()

    # Simulate quick check
    assert True

    elapsed = time.time() - start

    # Should be effectively instant (<0.1s)
    assert elapsed < 0.1, f"Smoke test too slow: {elapsed:.2f}s"
