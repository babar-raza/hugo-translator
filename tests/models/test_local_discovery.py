"""
Tests for local model discovery engine.

Uses temporary mock model folders -- no real large models required.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from src.model_runtime.local_discovery import (
    DEFAULT_SKIP_PATTERNS,
    DiscoveredLocalModel,
    LocalModelDiscovery,
    ScanRoot,
    _generate_model_id,
    _parse_hf_id,
    _parse_opus_language_pair,
    detect_ctranslate2_model,
    detect_gguf_model,
    detect_hf_cache_models,
    detect_ollama_models,
    detect_sentencepiece_model,
    detect_transformers_model,
)
from src.model_runtime.discovery_report import DiscoveryReportManager
from src.model_runtime.registry import ModelInfo, ModelRegistry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_hf_cache(tmp_path: Path) -> Path:
    """Create a fake HuggingFace cache with M2M100 and Opus models."""
    cache_dir = tmp_path / "hf_cache" / "hub"
    cache_dir.mkdir(parents=True)

    # M2M100 model
    m2m_dir = cache_dir / "models--facebook--m2m100_418M" / "snapshots" / "abc123"
    m2m_dir.mkdir(parents=True)
    (m2m_dir / "config.json").write_text(json.dumps({
        "model_type": "m2m_100",
        "_name_or_path": "facebook/m2m100_418M",
        "vocab_size": 128112,
    }))
    (m2m_dir / "pytorch_model.bin").write_bytes(b"\x00" * 1024)
    (m2m_dir / "sentencepiece.bpe.model").write_bytes(b"\x00" * 100)
    (m2m_dir / "tokenizer_config.json").write_text("{}")

    # Opus EN-FR model
    opus_dir = cache_dir / "models--Helsinki-NLP--opus-mt-en-fr" / "snapshots" / "def456"
    opus_dir.mkdir(parents=True)
    (opus_dir / "config.json").write_text(json.dumps({
        "model_type": "marian",
        "_name_or_path": "Helsinki-NLP/opus-mt-en-fr",
    }))
    (opus_dir / "pytorch_model.bin").write_bytes(b"\x00" * 512)

    return cache_dir


@pytest.fixture
def mock_nllb_cache(tmp_path: Path) -> Path:
    """Create a fake HF cache with NLLB model."""
    cache_dir = tmp_path / "nllb_cache" / "hub"
    nllb_dir = cache_dir / "models--facebook--nllb-200-distilled-600M" / "snapshots" / "snap1"
    nllb_dir.mkdir(parents=True)
    (nllb_dir / "config.json").write_text(json.dumps({
        "model_type": "m2m_100",  # NLLB uses m2m_100 architecture
        "_name_or_path": "facebook/nllb-200-distilled-600M",
    }))
    (nllb_dir / "model.safetensors").write_bytes(b"\x00" * 2048)
    return cache_dir


@pytest.fixture
def mock_marian_cache(tmp_path: Path) -> Path:
    """Create a fake HF cache with Marian model."""
    cache_dir = tmp_path / "marian_cache" / "hub"
    marian_dir = cache_dir / "models--Helsinki-NLP--opus-mt-de-en" / "snapshots" / "snap1"
    marian_dir.mkdir(parents=True)
    (marian_dir / "config.json").write_text(json.dumps({
        "model_type": "marian",
        "_name_or_path": "Helsinki-NLP/opus-mt-de-en",
    }))
    (marian_dir / "pytorch_model.bin").write_bytes(b"\x00" * 512)
    return cache_dir


@pytest.fixture
def mock_ollama_dir(tmp_path: Path) -> Path:
    """Create a fake Ollama models directory."""
    ollama = tmp_path / "ollama_models"
    manifests = ollama / "manifests" / "registry.ollama.ai" / "library" / "qwen3" / "14b"
    manifests.mkdir(parents=True)
    manifest_file = manifests / "latest"

    # Simplified Ollama manifest
    manifest_file.write_text(json.dumps({
        "schemaVersion": 2,
        "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
        "layers": [
            {"mediaType": "application/vnd.ollama.image.model", "size": 8_000_000_000},
            {"mediaType": "application/vnd.ollama.image.template", "size": 1024},
        ],
    }))

    blobs = ollama / "blobs"
    blobs.mkdir(parents=True)
    return ollama


@pytest.fixture
def mock_ct2_dir(tmp_path: Path) -> Path:
    """Create a fake CTranslate2 model directory."""
    ct2 = tmp_path / "ct2_model"
    ct2.mkdir()
    (ct2 / "model.bin").write_bytes(b"\x00" * 4096)
    (ct2 / "model_spec.json").write_text(json.dumps({
        "quantization": "int8",
        "with_source_bpe": True,
    }))
    (ct2 / "shared_vocabulary.json").write_text("{}")
    return ct2


@pytest.fixture
def mock_gguf_file(tmp_path: Path) -> Path:
    """Create a fake GGUF file with correct magic bytes."""
    gguf = tmp_path / "llama-2-7b-chat.Q4_K_M.gguf"
    # GGUF magic: "GGUF" in bytes
    content = b"GGUF" + b"\x00" * 1020
    gguf.write_bytes(content)
    return gguf


# ---------------------------------------------------------------------------
# Test: HF Cache Detection
# ---------------------------------------------------------------------------


class TestDetectHfCacheModels:
    def test_detect_m2m100(self, mock_hf_cache: Path):
        models = detect_hf_cache_models(mock_hf_cache)
        m2m = [m for m in models if "m2m100" in m.model_family]
        assert len(m2m) >= 1
        m = m2m[0]
        assert m.multilingual is True
        assert m.supported_language_pairs == "all"
        assert m.model_format == "transformers"
        assert m.backend_type == "huggingface"
        assert m.hf_model_id == "facebook/m2m100_418M"
        assert m.confidence >= 0.8

    def test_detect_opus(self, mock_hf_cache: Path):
        models = detect_hf_cache_models(mock_hf_cache)
        opus = [m for m in models if m.source_language == "en" and m.target_language == "fr"]
        assert len(opus) >= 1
        m = opus[0]
        assert m.multilingual is False
        assert ("en", "fr") in m.supported_language_pairs
        assert ("fr", "en") in m.supported_language_pairs

    def test_detect_nllb(self, mock_nllb_cache: Path):
        models = detect_hf_cache_models(mock_nllb_cache)
        assert len(models) >= 1
        m = models[0]
        assert m.hf_model_id == "facebook/nllb-200-distilled-600M"
        assert m.multilingual is True

    def test_detect_marian(self, mock_marian_cache: Path):
        models = detect_hf_cache_models(mock_marian_cache)
        assert len(models) >= 1
        m = models[0]
        assert m.source_language == "de"
        assert m.target_language == "en"
        assert m.multilingual is False


# ---------------------------------------------------------------------------
# Test: Ollama Detection
# ---------------------------------------------------------------------------


class TestDetectOllamaModels:
    def test_detect_ollama(self, mock_ollama_dir: Path):
        models = detect_ollama_models(mock_ollama_dir)
        assert len(models) >= 1
        m = models[0]
        assert m.backend_type == "local_llm"
        assert m.model_format == "ollama"
        assert m.size_bytes > 0


# ---------------------------------------------------------------------------
# Test: CTranslate2 Detection
# ---------------------------------------------------------------------------


class TestDetectCTranslate2:
    def test_detect_ct2(self, mock_ct2_dir: Path):
        model = detect_ctranslate2_model(mock_ct2_dir)
        assert model is not None
        assert model.backend_type == "ctranslate2"
        assert model.model_format == "ctranslate2"
        assert model.quantization == "int8"
        assert model.confidence >= 0.8


# ---------------------------------------------------------------------------
# Test: GGUF Detection
# ---------------------------------------------------------------------------


class TestDetectGguf:
    def test_detect_gguf(self, mock_gguf_file: Path):
        model = detect_gguf_model(mock_gguf_file)
        assert model is not None
        assert model.backend_type == "local_llm"
        assert model.model_format == "gguf"
        assert model.quantization == "Q4_K_M"
        assert model.confidence >= 0.8

    def test_reject_non_gguf(self, tmp_path: Path):
        fake = tmp_path / "fake.gguf"
        fake.write_bytes(b"NOT_GGUF_MAGIC_BYTES_HERE")
        model = detect_gguf_model(fake)
        assert model is None


# ---------------------------------------------------------------------------
# Test: Invalid Folder Ignored
# ---------------------------------------------------------------------------


class TestInvalidFolder:
    def test_random_folder_not_detected(self, tmp_path: Path):
        """Folder with random files should not be detected as a model."""
        random_dir = tmp_path / "random_stuff"
        random_dir.mkdir()
        (random_dir / "readme.txt").write_text("hello")
        (random_dir / "data.csv").write_text("a,b,c")

        assert detect_transformers_model(random_dir) is None
        assert detect_ctranslate2_model(random_dir) is None


# ---------------------------------------------------------------------------
# Test: Skip Patterns
# ---------------------------------------------------------------------------


class TestSkipPatterns:
    def test_skip_patterns_enforced(self, tmp_path: Path):
        """Directories matching skip patterns should not be scanned."""
        # Create a model inside a $RECYCLE.BIN directory
        recycle = tmp_path / "$RECYCLE.BIN" / "model"
        recycle.mkdir(parents=True)
        (recycle / "config.json").write_text(json.dumps({"model_type": "m2m_100"}))
        (recycle / "pytorch_model.bin").write_bytes(b"\x00" * 100)

        # Create a valid model outside skip
        good = tmp_path / "good_model"
        good.mkdir()
        (good / "config.json").write_text(json.dumps({"model_type": "m2m_100"}))
        (good / "pytorch_model.bin").write_bytes(b"\x00" * 100)

        root = ScanRoot(path=tmp_path, label="test", max_depth=4, scan_type="directory")
        discovery = LocalModelDiscovery(scan_roots=[root])
        models = discovery.discover_all()

        model_paths = [str(m.absolute_path) for m in models]
        assert any("good_model" in p for p in model_paths)
        assert not any("RECYCLE" in p for p in model_paths)


# ---------------------------------------------------------------------------
# Test: Max Depth
# ---------------------------------------------------------------------------


class TestMaxDepth:
    def test_max_depth_enforcement(self, tmp_path: Path):
        """Models deeper than max_depth should not be found."""
        # Create deeply nested model (depth=5)
        deep = tmp_path / "a" / "b" / "c" / "d" / "e" / "deep_model"
        deep.mkdir(parents=True)
        (deep / "config.json").write_text(json.dumps({"model_type": "marian"}))

        # Shallow model (depth=1)
        shallow = tmp_path / "shallow_model"
        shallow.mkdir()
        (shallow / "config.json").write_text(json.dumps({"model_type": "marian"}))
        (shallow / "pytorch_model.bin").write_bytes(b"\x00" * 100)

        root = ScanRoot(path=tmp_path, label="test", max_depth=2, scan_type="directory")
        discovery = LocalModelDiscovery(scan_roots=[root])
        models = discovery.discover_all()

        ids = [m.model_id for m in models]
        assert any("shallow" in mid for mid in ids)
        # Deep model should not be found at depth=2
        assert not any("deep" in mid for mid in ids)


# ---------------------------------------------------------------------------
# Test: Permission Error Handling
# ---------------------------------------------------------------------------


class TestPermissionErrorHandling:
    def test_permission_error_continues(self, tmp_path: Path):
        """Discovery should continue when one root has permission errors."""
        # Create a valid model
        good = tmp_path / "good"
        good.mkdir()
        (good / "config.json").write_text(json.dumps({"model_type": "m2m_100"}))
        (good / "pytorch_model.bin").write_bytes(b"\x00" * 100)

        roots = [
            ScanRoot(path=Path("/nonexistent/forbidden"), label="bad", max_depth=2),
            ScanRoot(path=tmp_path, label="good", max_depth=4, scan_type="directory"),
        ]
        discovery = LocalModelDiscovery(scan_roots=roots)
        models = discovery.discover_all()

        # Should still find the good model despite the bad root
        assert len(models) >= 1
        assert any("good" in m.model_id for m in models)
        # Bad root should be in skipped_roots
        assert any("nonexistent" in s["path"] for s in discovery.skipped_roots)

    def test_permission_error_during_scan(self, tmp_path: Path):
        """Scanner should handle PermissionError raised by iterdir()."""
        from unittest.mock import patch, PropertyMock

        # Create a valid model in a good directory
        good_dir = tmp_path / "accessible"
        good_dir.mkdir()
        (good_dir / "config.json").write_text(json.dumps({"model_type": "m2m_100"}))
        (good_dir / "pytorch_model.bin").write_bytes(b"\x00" * 100)

        # Create a directory that will raise PermissionError when iterated
        forbidden_dir = tmp_path / "forbidden"
        forbidden_dir.mkdir()

        real_iterdir = Path.iterdir

        def patched_iterdir(self):
            if self.name == "forbidden":
                raise PermissionError(f"Access denied: {self}")
            return real_iterdir(self)

        roots = [
            ScanRoot(path=tmp_path, label="mixed", max_depth=4, scan_type="directory"),
        ]
        discovery = LocalModelDiscovery(scan_roots=roots)

        with patch.object(Path, "iterdir", patched_iterdir):
            models = discovery.discover_all()

        # Should still find the good model
        assert len(models) >= 1
        # PermissionError should be recorded
        assert len(discovery.errors) >= 1
        assert any("forbidden" in e.get("path", "") for e in discovery.errors)


# ---------------------------------------------------------------------------
# Test: Deduplication
# ---------------------------------------------------------------------------


class TestDeduplication:
    def test_same_model_two_roots(self, tmp_path: Path):
        """Same model found via two roots should appear once."""
        model_dir = tmp_path / "shared_model"
        model_dir.mkdir()
        (model_dir / "config.json").write_text(json.dumps({"model_type": "m2m_100"}))
        (model_dir / "pytorch_model.bin").write_bytes(b"\x00" * 100)

        roots = [
            ScanRoot(path=tmp_path, label="root1", max_depth=4, scan_type="directory"),
            ScanRoot(path=tmp_path, label="root2", max_depth=4, scan_type="directory"),
        ]
        discovery = LocalModelDiscovery(scan_roots=roots)
        models = discovery.discover_all()

        # Should be deduplicated to 1
        assert len(models) == 1


# ---------------------------------------------------------------------------
# Test: Registry Dict Roundtrip
# ---------------------------------------------------------------------------


class TestRegistryDictRoundtrip:
    def test_roundtrip(self, mock_hf_cache: Path):
        """DiscoveredLocalModel.to_registry_dict() -> ModelInfo.from_dict() roundtrip."""
        models = detect_hf_cache_models(mock_hf_cache)
        assert len(models) >= 1

        for m in models:
            registry_dict = m.to_registry_dict()

            # Should have required fields
            assert "model_id" in registry_dict
            assert "name" in registry_dict
            assert "backend" in registry_dict
            assert "supported_pairs" in registry_dict

            # Should be loadable by ModelInfo
            info = ModelInfo.from_dict(registry_dict)
            assert info.model_id == m.model_id
            assert info.local_path is not None


# ---------------------------------------------------------------------------
# Test: Discovery Report Save/Load
# ---------------------------------------------------------------------------


class TestDiscoveryReport:
    def test_report_save_load(self, tmp_path: Path, mock_hf_cache: Path):
        """Reports should save and load correctly."""
        report_mgr = DiscoveryReportManager(reports_dir=tmp_path / "reports")
        root = ScanRoot(path=mock_hf_cache, label="test", scan_type="hf_cache")

        run_id = report_mgr.start_run([root])

        models = detect_hf_cache_models(mock_hf_cache)
        for m in models:
            report_mgr.record_model(run_id, m.to_dict())

        report = report_mgr.finish_run(run_id)
        report_path = report_mgr.save_report(report)

        assert report_path.exists()

        # Load it back
        loaded = report_mgr.load_report(run_id)
        assert loaded is not None
        assert loaded.run_id == run_id
        assert loaded.models_found == len(models)


# ---------------------------------------------------------------------------
# Test: Export Registry YAML
# ---------------------------------------------------------------------------


class TestExportRegistryYaml:
    def test_exported_yaml_loadable(self, tmp_path: Path, mock_hf_cache: Path):
        """Exported YAML should be loadable by ModelRegistry."""
        report_mgr = DiscoveryReportManager(reports_dir=tmp_path / "reports")
        root = ScanRoot(path=mock_hf_cache, label="test", scan_type="hf_cache")

        run_id = report_mgr.start_run([root])
        models = detect_hf_cache_models(mock_hf_cache)
        for m in models:
            report_mgr.record_model(run_id, m.to_dict())
        report = report_mgr.finish_run(run_id)

        yaml_path = tmp_path / "discovered.yaml"
        count = report_mgr.export_as_registry_yaml(report, yaml_path)
        assert count > 0
        assert yaml_path.exists()

        # Should load via ModelRegistry
        registry = ModelRegistry(yaml_path)
        assert len(registry) > 0


# ---------------------------------------------------------------------------
# Test: Registry Merge Preserves Existing
# ---------------------------------------------------------------------------


class TestRegistryMerge:
    def test_curated_not_overridden(self, tmp_path: Path):
        """Curated entries should not be overridden by discovered models."""
        # Create a curated registry
        curated_path = tmp_path / "curated.yaml"
        curated_path.write_text(yaml.dump({"models": [{
            "model_id": "test_model",
            "name": "Curated Test Model",
            "backend": "huggingface",
            "supported_pairs": "all",
            "model_size_mb": 100,
            "min_ram_gb": 2,
            "optimal_device": "cpu",
        }]}))

        registry = ModelRegistry(curated_path)
        assert registry.get_model("test_model").name == "Curated Test Model"

        # Create a discovered model with same ID
        discovered = ModelInfo.from_dict({
            "model_id": "test_model",
            "name": "Discovered Override Attempt",
            "backend": "huggingface",
            "supported_pairs": "all",
        })

        count = registry.merge_discovered([discovered], allow_override=False)
        assert count == 0
        assert registry.get_model("test_model").name == "Curated Test Model"


# ---------------------------------------------------------------------------
# Test: Empty/Nonexistent Roots
# ---------------------------------------------------------------------------


class TestEmptyRoots:
    def test_nonexistent_root_graceful(self, tmp_path: Path):
        """Nonexistent roots should be handled gracefully."""
        roots = [
            ScanRoot(path=tmp_path / "does_not_exist", label="missing"),
        ]
        discovery = LocalModelDiscovery(scan_roots=roots)
        models = discovery.discover_all()
        assert len(models) == 0
        assert len(discovery.skipped_roots) >= 1

    def test_empty_directory(self, tmp_path: Path):
        """Empty directory should return no models."""
        empty = tmp_path / "empty"
        empty.mkdir()
        root = ScanRoot(path=empty, label="empty", scan_type="directory")
        discovery = LocalModelDiscovery(scan_roots=[root])
        models = discovery.discover_all()
        assert len(models) == 0


# ---------------------------------------------------------------------------
# Test: Missing Path Marked Unavailable
# ---------------------------------------------------------------------------


class TestMissingPath:
    def test_missing_path_status(self):
        """Model with nonexistent path should have appropriate health_status."""
        model = DiscoveredLocalModel(
            model_id="test_missing",
            display_name="Missing Model",
            model_family="test",
            model_type="test",
            backend_type="huggingface",
            model_format="transformers",
            absolute_path=Path("/nonexistent/model/path"),
            path_exists=False,
            health_status="unavailable",
        )
        assert model.health_status == "unavailable"
        assert model.path_exists is False

        # to_registry_dict should still work
        d = model.to_registry_dict()
        assert d["model_id"] == "test_missing"
        assert d["local_path"] == str(Path("/nonexistent/model/path"))


# ---------------------------------------------------------------------------
# Test: Windows-Style Paths
# ---------------------------------------------------------------------------


class TestWindowsPaths:
    def test_pathlib_handles_windows(self, tmp_path: Path):
        """Paths with various separators should be handled by pathlib."""
        model_dir = tmp_path / "win_model"
        model_dir.mkdir()
        (model_dir / "config.json").write_text(json.dumps({"model_type": "m2m_100"}))
        # Weight file required — tokenizer-only dirs are now rejected by the detector
        (model_dir / "model.safetensors").write_bytes(b"\x00" * 8)

        model = detect_transformers_model(model_dir)
        assert model is not None
        # Path should be a proper pathlib Path
        assert isinstance(model.absolute_path, Path)
        # to_registry_dict should produce a string path
        d = model.to_registry_dict()
        assert isinstance(d["local_path"], str)


# ---------------------------------------------------------------------------
# Test: Utility Functions
# ---------------------------------------------------------------------------


class TestUtilities:
    def test_parse_hf_id(self):
        assert _parse_hf_id("models--facebook--m2m100_418M") == "facebook/m2m100_418M"
        assert _parse_hf_id("models--Helsinki-NLP--opus-mt-en-fr") == "Helsinki-NLP/opus-mt-en-fr"
        assert _parse_hf_id("not-a-model") is None
        assert _parse_hf_id("models--") is None

    def test_parse_opus_language_pair(self):
        assert _parse_opus_language_pair("Helsinki-NLP/opus-mt-en-fr") == ("en", "fr")
        assert _parse_opus_language_pair("Helsinki-NLP/opus-mt-de-en") == ("de", "en")
        assert _parse_opus_language_pair("facebook/m2m100_418M") is None

    def test_generate_model_id(self, tmp_path: Path):
        mid = _generate_model_id(tmp_path / "test_model", "transformers")
        assert isinstance(mid, str)
        assert len(mid) > 0
        assert "__" not in mid
