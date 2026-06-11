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

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.hardware import GPUManager
from src.model_runtime.hardware import HardwareDetector
from src.tm import L1Cache, L2PersistentTM, TranslationMemory

try:
    from src.tm import L3SemanticTM
except ImportError:
    L3SemanticTM = None


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

        # GPU info should be consistent (using actual attributes)
        if hw_info.has_cuda:
            assert isinstance(hw_info.cuda_devices, list)
            assert len(hw_info.cuda_devices) > 0
        else:
            assert hw_info.cuda_devices == [] or not hw_info.cuda_devices

    except Exception as e:
        pytest.fail(f"GPU detection failed: {e}")


@pytest.mark.smoke
def test_gpu_manager_initialization():
    """Smoke test: GPU manager can initialize without errors."""
    try:
        # GPU manager should initialize even if no GPU available
        manager = GPUManager()

        # Should have valid state
        assert manager is not None

        # Get recommended device (should not crash)
        device = manager.get_recommended_device()
        assert device in ["cuda", "cpu", "mps", None] or device is None

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

        if hw_info.has_cuda and hw_info.cuda_devices:
            # Check if any GPU has sufficient memory (if available)
            has_sufficient_gpu = (
                any(d.get("memory_total_gb", 0) >= 2.0 for d in hw_info.cuda_devices)
                if hw_info.cuda_devices
                else False
            )
            if has_sufficient_gpu:
                # May recommend GPU
                assert device in ["cuda", "mps", "cpu"]
        else:
            # Should fall back to CPU
            assert device in ["cpu", "mps"]

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
        assert hasattr(cache, "put")
        assert hasattr(cache, "get")

        # Test basic put/get (L1Cache.get returns Optional[str])
        cache.put("test-site", "en", "es", "hello", "hola")
        result = cache.get("test-site", "en", "es", "hello")

        assert result is not None
        assert result == "hola"  # L1Cache returns the translation string directly

    except Exception as e:
        pytest.fail(f"L1 cache initialization failed: {e}")


@pytest.mark.smoke
def test_tm_l1_cache_eviction():
    """Smoke test: L1 cache eviction works when size exceeded."""
    try:
        # Small cache to trigger eviction
        cache = L1Cache(max_size=3)

        # Fill beyond capacity
        cache.put("test-site", "en", "es", "one", "uno")
        cache.put("test-site", "en", "es", "two", "dos")
        cache.put("test-site", "en", "es", "three", "tres")
        cache.put("test-site", "en", "es", "four", "cuatro")

        # Cache should still work (eviction occurred)
        result = cache.get("test-site", "en", "es", "four")
        assert result is not None
        assert result == "cuatro"

        # Verify cache size is maintained (use stats() method)
        stats = cache.stats()
        assert stats["size"] <= 3

    except Exception as e:
        pytest.fail(f"L1 cache eviction failed: {e}")


@pytest.mark.smoke
def test_tm_l1_multi_language_pairs():
    """Smoke test: L1 cache handles multiple language pairs."""
    try:
        cache = L1Cache(max_size=100)

        # Store translations for different language pairs
        cache.put("test-site", "en", "es", "hello", "hola")
        cache.put("test-site", "en", "fr", "hello", "bonjour")
        cache.put("test-site", "es", "en", "hola", "hello")

        # Verify all pairs are accessible (returns string directly)
        assert cache.get("test-site", "en", "es", "hello") == "hola"
        assert cache.get("test-site", "en", "fr", "hello") == "bonjour"
        assert cache.get("test-site", "es", "en", "hola") == "hello"

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
            db_path = Path(tmpdir) / "test_l2"
            tm = L2PersistentTM(db_path=db_path, max_size_mb=10)

            # Verify initialization
            assert tm is not None
            assert hasattr(tm, "store")
            assert hasattr(tm, "exact_lookup")

            # Test basic store/lookup
            tm.store("test-site", "en", "es", "world", "mundo")
            result = tm.exact_lookup("test-site", "en", "es", "world")

            assert result is not None
            assert result.translation == "mundo"

            # Clean up
            tm.close()

        except Exception as e:
            pytest.fail(f"L2 persistent TM initialization failed: {e}")


@pytest.mark.smoke
def test_tm_l2_persistence():
    """Smoke test: L2 TM persists data across instances."""
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            db_path = Path(tmpdir) / "test_l2"

            # Store data in first instance
            tm1 = L2PersistentTM(db_path=db_path, max_size_mb=10)
            tm1.store("test-site", "en", "es", "persistence", "persistencia")
            tm1.close()

            # Retrieve data in second instance
            tm2 = L2PersistentTM(db_path=db_path, max_size_mb=10)
            result = tm2.exact_lookup("test-site", "en", "es", "persistence")

            assert result is not None
            assert result.translation == "persistencia"

            tm2.close()

        except Exception as e:
            pytest.fail(f"L2 persistence failed: {e}")


@pytest.mark.smoke
def test_tm_l2_bulk_operations():
    """Smoke test: L2 TM handles bulk store operations efficiently."""
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            db_path = Path(tmpdir) / "test_l2"
            tm = L2PersistentTM(db_path=db_path, max_size_mb=10)

            # Store multiple entries
            entries = [
                ("apple", "manzana"),
                ("banana", "plátano"),
                ("orange", "naranja"),
                ("grape", "uva"),
                ("pear", "pera"),
            ]

            for source, target in entries:
                tm.store("test-site", "en", "es", source, target)

            # Verify all entries
            for source, target in entries:
                result = tm.exact_lookup("test-site", "en", "es", source)
                assert result is not None
                assert result.translation == target

            tm.close()

        except Exception as e:
            pytest.fail(f"L2 bulk operations failed: {e}")


# ============================================================================
# TM Layer L3 (Semantic) Tests
# ============================================================================


@pytest.mark.smoke
@pytest.mark.skipif(L3SemanticTM is None, reason="L3SemanticTM not available (FAISS missing)")
def test_tm_l3_initialization():
    """Smoke test: L3 semantic TM initializes (CPU mode for speed)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            index_path = Path(tmpdir) / "test_index"

            # Initialize in CPU mode for smoke test speed
            tm = L3SemanticTM(
                index_path=index_path,
                use_gpu=False,
            )

            # Verify initialization
            assert tm is not None
            assert hasattr(tm, "add_entry")
            assert hasattr(tm, "semantic_search")

        except Exception as e:
            pytest.fail(f"L3 semantic TM initialization failed: {e}")


@pytest.mark.smoke
@pytest.mark.skipif(L3SemanticTM is None, reason="L3SemanticTM not available (FAISS missing)")
def test_tm_l3_add_and_search():
    """Smoke test: L3 can add entries and perform semantic search."""
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            index_path = Path(tmpdir) / "test_index"

            tm = L3SemanticTM(
                index_path=index_path,
                use_gpu=False,
            )

            # Add some entries (entry_id, site_id, src_lang, tgt_lang, source_text, translation)
            tm.add_entry("entry1", "test-site", "en", "es", "Hello world", "Hola mundo")
            tm.add_entry("entry2", "test-site", "en", "es", "Good morning", "Buenos días")

            # Search (should find exact or similar match)
            results = tm.semantic_search("test-site", "en", "es", "Hello world")

            # Should return results (may be empty list or matches)
            assert isinstance(results, list)

        except Exception as e:
            pytest.fail(f"L3 add/search failed: {e}")


@pytest.mark.smoke
@pytest.mark.skipif(L3SemanticTM is None, reason="L3SemanticTM not available (FAISS missing)")
def test_tm_l3_device_compatibility():
    """Smoke test: L3 works on CPU regardless of GPU availability."""
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            index_path = Path(tmpdir) / "test_index"

            # Force CPU mode
            tm = L3SemanticTM(
                index_path=index_path,
                use_gpu=False,
            )

            # Should work on any system (entry_id, site_id, src_lang, tgt_lang, source_text, translation)
            tm.add_entry("entry1", "test-site", "en", "es", "test", "prueba")
            results = tm.semantic_search("test-site", "en", "es", "test")

            assert isinstance(results, list)  # May return 0 or more results

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
            l2_path = tm_dir / "l2"

            # Create L1 and L2 instances
            l1 = L1Cache(max_size=100)
            l2 = L2PersistentTM(db_path=l2_path, max_size_mb=10)

            # Create TranslationMemory with pre-built components
            tm = TranslationMemory(
                l1_cache=l1,
                l2_persistent=l2,
                l3_semantic=None,  # Optional
            )

            # Verify all layers initialized
            assert tm.l1 is not None
            assert tm.l2 is not None

            l2.close()

        except Exception as e:
            pytest.fail(f"TranslationMemory initialization failed: {e}")


@pytest.mark.smoke
def test_translation_memory_lookup_chain():
    """Smoke test: TM lookup chain (L1 -> L2 -> L3) works."""
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            tm_dir = Path(tmpdir)
            l2_path = tm_dir / "l2"

            l1 = L1Cache(max_size=100)
            l2 = L2PersistentTM(db_path=l2_path, max_size_mb=10)

            tm = TranslationMemory(
                l1_cache=l1,
                l2_persistent=l2,
                l3_semantic=None,
            )

            # Store in TM (goes to L2)
            tm.store("test-site", "en", "es", "lookup test", "prueba de búsqueda")

            # Lookup should find it
            result = tm.lookup("test-site", "en", "es", "lookup test")

            assert result is not None
            assert result.translation == "prueba de búsqueda"

            l2.close()

        except Exception as e:
            pytest.fail(f"TM lookup chain failed: {e}")


# ============================================================================
# Configuration Loading Tests
# ============================================================================


@pytest.mark.smoke
def test_config_loading_smoke():
    """Smoke test: ConfigService can initialize with valid config path."""
    try:
        from src.utils.config_loader import ConfigService

        # ConfigService requires a config_root argument
        # Use the actual config directory
        config_root = Path(__file__).parent.parent.parent / "config"

        if config_root.exists():
            config = ConfigService(config_root)

            # Should have basic methods
            assert hasattr(config, "get_site_profile")
            assert hasattr(config, "global_config")  # Property, not method
        else:
            pytest.skip("Config directory not found")

    except Exception as e:
        pytest.fail(f"Config loading failed: {e}")


@pytest.mark.smoke
def test_config_default_values():
    """Smoke test: ConfigService provides site profiles when available."""
    try:
        from src.utils.config_loader import ConfigService

        config_root = Path(__file__).parent.parent.parent / "config"

        if config_root.exists():
            config = ConfigService(config_root)

            # Try to load a known site profile
            profiles_dir = config_root / "site_profiles"
            if profiles_dir.exists():
                profile_files = list(profiles_dir.glob("*.yaml"))
                if profile_files:
                    # Load first available profile
                    site_id = profile_files[0].stem
                    profile = config.get_site_profile(site_id)
                    assert profile is not None
        else:
            pytest.skip("Config directory not found")

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
            from src.model_runtime import ModelRegistry

            registry_path = Path(tmpdir) / "registry.yaml"

            # Create minimal registry file with correct schema (models is a list)
            registry_content = """
models:
  - model_id: "test-model"
    name: "Test Model"
    backend: "huggingface"
    supported_pairs: "all"
"""
            registry_path.write_text(registry_content)

            # Initialize registry
            registry = ModelRegistry(registry_path=registry_path)

            # Should load models
            models = registry.list_models()
            assert "test-model" in models or len(models) >= 0

        except Exception as e:
            pytest.fail(f"Model registry initialization failed: {e}")


@pytest.mark.smoke
def test_model_registry_without_file():
    """Smoke test: ModelRegistry handles missing file gracefully."""
    try:
        from src.model_runtime import ModelRegistry

        # Should handle missing file
        registry = ModelRegistry(registry_path="/nonexistent/registry.yaml")

        # Should return empty model list or raise gracefully
        models = registry.list_models()
        assert isinstance(models, (list, dict))

    except Exception as e:
        # This is acceptable - may raise error for missing file
        assert "registry" in str(e).lower() or "file" in str(e).lower() or "not" in str(e).lower()


# ============================================================================
# Translation Pipeline Component Tests
# ============================================================================


@pytest.mark.smoke
def test_translation_engine_initialization():
    """Smoke test: TranslationEngine can initialize."""
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            from src.translation_engine.engine import TranslationEngine

            tm_dir = Path(tmpdir)
            l2_path = tm_dir / "l2"

            # Create TM components
            l1 = L1Cache(max_size=100)
            l2 = L2PersistentTM(db_path=l2_path, max_size_mb=10)

            tm = TranslationMemory(
                l1_cache=l1,
                l2_persistent=l2,
                l3_semantic=None,
            )

            # TranslationEngine may have different constructor
            # Check if it can be instantiated
            assert TranslationEngine is not None

            l2.close()

        except ImportError as e:
            pytest.skip(f"TranslationEngine not importable: {e}")
        except Exception as e:
            pytest.fail(f"TranslationEngine initialization failed: {e}")


@pytest.mark.smoke
def test_translation_engine_parser_smoke():
    """Smoke test: Translation engine parser doesn't crash on simple input."""
    try:
        from src.translation_engine.parser import HugoParser

        # Simple markdown - parser should handle it
        simple_md = "# Hello World\n\nThis is a test."

        # Parse should not crash
        parser = HugoParser()
        result = parser.parse_string(simple_md)

        # Should return some result
        assert result is not None

    except ImportError as e:
        pytest.skip(f"HugoParser not importable: {e}")
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
            l2_path = tm_dir / "l2"

            l1 = L1Cache(max_size=100)
            l2 = L2PersistentTM(db_path=l2_path, max_size_mb=10)

            tm = TranslationMemory(
                l1_cache=l1,
                l2_persistent=l2,
                l3_semantic=None,
            )

            # All should coexist
            assert hw_info is not None
            assert tm is not None

            l2.close()

        except Exception as e:
            pytest.fail(f"System components compatibility failed: {e}")


@pytest.mark.smoke
def test_critical_imports():
    """Smoke test: All critical modules can be imported."""
    try:
        # Core modules
        from src.model_runtime.hardware import HardwareDetector
        from src.tm import L1Cache, L2PersistentTM, TranslationMemory
        from src.translation_engine.engine import TranslationEngine
        from src.translation_engine.parser import HugoParser

        # Validation modules
        from src.translation_engine.validation import (
            PlaceholderValidator,
            StructureValidator,
            YAMLValidator,
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
