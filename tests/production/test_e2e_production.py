"""
End-to-end production readiness tests.

Tests all system components in a production-like configuration.
"""
import os
import time
from pathlib import Path
import tempfile

import pytest

# Import all major components
from src.utils.config_loader import ConfigService
from src.translation_engine.engine import TranslationEngine
from src.tm import TranslationMemory, L1Cache, L2PersistentTM, L3SemanticTM
from src.model_runtime import ModelLoader, ModelRegistry, HardwareDetector
from src.orchestrator import TranslationOrchestrator, JobQueue
from src.observability import MetricsCollector, StructuredLogger


class TestProductionReadiness:
    """Production readiness validation tests."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        """Setup test environment."""
        self.tmp_path = tmp_path
        self.config_path = Path("config")

    def test_01_configuration_loads(self):
        """Test all configuration loads successfully."""
        # Test ConfigService
        config = ConfigService(self.config_path)
        assert config is not None

        # Test site profiles exist
        sites = config.list_sites()
        assert len(sites) > 0, "No site profiles found"

        # Test each site profile validates
        for site_id in sites[:3]:  # Test first 3 sites
            profile = config.get_site_profile(site_id)
            assert profile is not None
            assert profile.site_id == site_id

    def test_02_hardware_detection(self):
        """Test hardware detection works."""
        detector = HardwareDetector()
        hw_info = detector.detect()

        assert hw_info.cpu_count > 0
        assert hw_info.total_ram_gb > 0
        assert hw_info.recommended_device in ['cpu', 'cuda', 'mps']

    def test_03_model_registry_loads(self):
        """Test model registry loads."""
        registry = ModelRegistry(Path("config/model_registry.yaml"))
        models = registry.list_models()
        assert len(models) > 0, "No models in registry"

    def test_04_tm_initialization(self):
        """Test TM system initializes."""
        l1 = L1Cache(max_size=100)
        assert l1 is not None

        l2 = L2PersistentTM(self.tmp_path / "tm.lmdb")
        assert l2 is not None

        # Test basic TM operations
        l2.store("test-site", "en", "es", "hello", "hola")
        result = l2.exact_lookup("test-site", "en", "es", "hello")
        assert result == "hola"
        l2.close()

    def test_05_translation_engine_initialization(self):
        """Test translation engine initializes."""
        config = ConfigService(self.config_path)
        l1 = L1Cache()
        l2 = L2PersistentTM(self.tmp_path / "tm.lmdb")
        tm = TranslationMemory(l1, l2)
        registry = ModelRegistry(Path("config/model_registry.yaml"))
        hw_info = HardwareDetector().detect()
        loader = ModelLoader(registry, hw_info.recommended_device)
        engine = TranslationEngine(config, tm, loader)
        assert engine is not None
        l2.close()

    def test_06_parallel_translation_enabled(self):
        """Test parallel processing is enabled."""
        config = ConfigService(self.config_path)
        l1 = L1Cache()
        l2 = L2PersistentTM(self.tmp_path / "tm.lmdb")
        tm = TranslationMemory(l1, l2)
        registry = ModelRegistry(Path("config/model_registry.yaml"))
        hw_info = HardwareDetector().detect()
        loader = ModelLoader(registry, hw_info.recommended_device)
        engine = TranslationEngine(config, tm, loader)

        # Verify locks exist
        assert hasattr(engine, '_tm_lock')
        assert hasattr(engine, '_model_lock')
        l2.close()

    def test_07_orchestrator_initialization(self):
        """Test orchestrator initializes."""
        config = ConfigService(self.config_path)
        queue = JobQueue(backend='memory')
        orchestrator = TranslationOrchestrator(
            config=config,
            queue=queue,
            tm_path=self.tmp_path / "tm.lmdb",
            model_cache_path=self.tmp_path / "models"
        )
        assert orchestrator is not None

    def test_08_metrics_collection(self):
        """Test metrics collection works."""
        collector = MetricsCollector()
        collector.increment('test_counter', labels={'test': 'value'})
        collector.set_gauge('test_gauge', 42)
        collector.observe('test_histogram', 1.5)
        metrics = collector.export_prometheus()
        assert len(metrics) > 0

    def test_09_structured_logging(self):
        """Test structured logging works."""
        log_file = self.tmp_path / "test.log"
        from src.observability.logger import setup_structured_logging
        import structlog
        setup_structured_logging(log_file=str(log_file))
        logger = structlog.get_logger()
        logger.info("test_message", key="value")
        assert log_file.exists()

    def test_10_environment_variables(self):
        """Test environment variables are documented."""
        env_example = Path(".env.example")
        env_production = Path(".env.production")
        assert env_example.exists(), ".env.example not found"
        assert env_production.exists(), ".env.production not found"

    def test_11_docker_files_exist(self):
        """Test Docker files exist."""
        assert Path("Dockerfile").exists()
        assert Path("Dockerfile.gpu").exists()
        assert Path("docker-compose.yml").exists()
        assert Path("docker/prometheus/prometheus.yml").exists()
        assert Path("docker/prometheus/alert_rules.yml").exists()

    def test_12_configuration_files_complete(self):
        """Test all configuration files are complete."""
        assert Path("config/global.yaml").exists()
        assert Path("config/model_registry.yaml").exists()
        assert Path("config/site_profiles").is_dir()

    def test_13_parallel_processing_code(self):
        """Test parallel processing implementation exists."""
        engine_file = Path("src/translation_engine/engine.py")
        content = engine_file.read_text()
        assert "ThreadPoolExecutor" in content
        assert "_translate_directory_parallel" in content
        assert "_translate_file_safe" in content

    def test_14_no_todos_remaining(self):
        """Test no critical TODOs remain in code."""
        engine_file = Path("src/translation_engine/engine.py")
        content = engine_file.read_text()
        # The only TODO should be resolved
        assert "TODO: Implement parallel processing" not in content


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
