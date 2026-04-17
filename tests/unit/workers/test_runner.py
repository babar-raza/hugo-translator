"""
Unit tests for WorkerRunner dual-run execution layer.

Tests ExecutionMode, WorkerConfig, DevicePolicy, and WorkerRunner base class.
"""

import os
import warnings
from unittest.mock import patch

import pytest

from src.workers.runner import (
    DevicePolicy,
    ExecutionMode,
    WorkerConfig,
    WorkerRunner,
    detect_legacy_mode,
    warn_legacy_mode,
)


class TestExecutionMode:
    """Tests for ExecutionMode enum."""

    def test_execution_mode_values(self):
        """Test ExecutionMode enum has correct values."""
        assert ExecutionMode.WINDOWS_CUDA.value == "windows_cuda"
        assert ExecutionMode.DOCKER_CPU.value == "docker_cpu"
        assert ExecutionMode.DOCKER_GPU.value == "docker_gpu"

    def test_execution_mode_from_string(self):
        """Test creating ExecutionMode from string."""
        assert ExecutionMode("windows_cuda") == ExecutionMode.WINDOWS_CUDA
        assert ExecutionMode("docker_cpu") == ExecutionMode.DOCKER_CPU
        assert ExecutionMode("docker_gpu") == ExecutionMode.DOCKER_GPU

    def test_execution_mode_invalid_string(self):
        """Test invalid ExecutionMode string raises ValueError."""
        with pytest.raises(ValueError):
            ExecutionMode("invalid_mode")


class TestWorkerConfig:
    """Tests for WorkerConfig dataclass."""

    def test_worker_config_defaults(self):
        """Test WorkerConfig has correct defaults."""
        config = WorkerConfig()
        assert config.execution_mode == ExecutionMode.WINDOWS_CUDA
        assert config.worker_id == "worker-default"
        assert config.redis_host == "localhost"
        assert config.redis_port == 6379
        assert config.redis_db == 0
        assert config.redis_password is None
        assert config.poll_interval == 5.0
        assert config.max_retries == 3
        assert config.config_path == "./config"
        assert config.tm_path == "./data/tm"
        assert config.device == "auto"
        assert config.use_shared_engines is True
        assert config.log_level == "INFO"

    def test_worker_config_from_env_empty(self):
        """Test WorkerConfig.from_env() with no environment variables."""
        with patch.dict(os.environ, {}, clear=True):
            config = WorkerConfig.from_env()
            assert config.execution_mode == ExecutionMode.WINDOWS_CUDA
            assert config.worker_id == "worker-default"
            assert config.redis_host == "localhost"
            assert config.device == "auto"

    def test_worker_config_from_env_with_vars(self):
        """Test WorkerConfig.from_env() with environment variables."""
        env_vars = {
            "EXECUTION_MODE": "docker_cpu",
            "WORKER_ID": "cpu-worker-1",
            "REDIS_HOST": "redis-server",
            "REDIS_PORT": "6380",
            "REDIS_DB": "1",
            "REDIS_PASSWORD": "secret",
            "POLL_INTERVAL": "3.0",
            "MAX_RETRIES": "5",
            "CONFIG_PATH": "/app/config",
            "TM_DATA_PATH": "/data/tm",
            "DEVICE": "cpu",
            "USE_SHARED_ENGINES": "true",
            "LOG_LEVEL": "DEBUG"
        }

        with patch.dict(os.environ, env_vars, clear=True):
            config = WorkerConfig.from_env()
            assert config.execution_mode == ExecutionMode.DOCKER_CPU
            assert config.worker_id == "cpu-worker-1"
            assert config.redis_host == "redis-server"
            assert config.redis_port == 6380
            assert config.redis_db == 1
            assert config.redis_password == "secret"
            assert config.poll_interval == 3.0
            assert config.max_retries == 5
            assert config.config_path == "/app/config"
            assert config.tm_path == "/data/tm"
            assert config.device == "cpu"
            assert config.use_shared_engines is True
            assert config.log_level == "DEBUG"

    def test_worker_config_from_env_with_mode_defaults(self):
        """Test WorkerConfig.from_env() with mode defaults from global.yaml."""
        mode_defaults = {
            "device": "cpu",
            "max_retries": 5,
            "poll_interval": 3.0,
            "worker_id": "docker-cpu-worker"
        }

        with patch.dict(os.environ, {}, clear=True):
            config = WorkerConfig.from_env(mode_defaults)
            assert config.device == "cpu"
            assert config.max_retries == 5
            assert config.poll_interval == 3.0
            assert config.worker_id == "docker-cpu-worker"

    def test_worker_config_from_env_precedence(self):
        """Test 3-tier precedence: ENV > mode defaults > dataclass defaults."""
        mode_defaults = {
            "device": "cpu",  # From mode config
            "max_retries": 5,  # From mode config
        }

        env_vars = {
            "DEVICE": "cuda",  # ENV overrides mode config
        }

        with patch.dict(os.environ, env_vars, clear=True):
            config = WorkerConfig.from_env(mode_defaults)
            assert config.device == "cuda"  # ENV wins
            assert config.max_retries == 5  # Mode default wins
            assert config.poll_interval == 5.0  # Dataclass default wins

    def test_worker_config_invalid_execution_mode(self):
        """Test invalid EXECUTION_MODE falls back to windows_cuda with warning."""
        with patch.dict(os.environ, {"EXECUTION_MODE": "invalid_mode"}, clear=True):
            config = WorkerConfig.from_env()
            assert config.execution_mode == ExecutionMode.WINDOWS_CUDA

    def test_worker_config_to_dict(self):
        """Test WorkerConfig.to_dict() serialization."""
        config = WorkerConfig(
            execution_mode=ExecutionMode.DOCKER_CPU,
            worker_id="test-worker",
            device="cpu"
        )
        config_dict = config.to_dict()
        assert config_dict["execution_mode"] == "docker_cpu"
        assert config_dict["worker_id"] == "test-worker"
        assert config_dict["device"] == "cpu"


class TestDevicePolicy:
    """Tests for DevicePolicy enforcement."""

    def test_device_policy_docker_cpu_mode(self):
        """Test DevicePolicy enforces CPU-only in docker_cpu mode."""
        policy = DevicePolicy(ExecutionMode.DOCKER_CPU)
        policy.enforce()

        # Check environment variable set
        assert os.environ.get("CUDA_VISIBLE_DEVICES") == ""

        # Check device override
        assert policy.get_device("cuda") == "cpu"
        assert policy.get_device("cuda:0") == "cpu"
        assert policy.get_device("auto") == "cpu"
        assert policy.get_device("cpu") == "cpu"

    def test_device_policy_docker_gpu_mode(self):
        """Test DevicePolicy allows GPU in docker_gpu mode."""
        policy = DevicePolicy(ExecutionMode.DOCKER_GPU)
        policy.enforce()

        # Check no device override
        assert policy.get_device("cuda") == "cuda"
        assert policy.get_device("cuda:0") == "cuda:0"
        assert policy.get_device("cpu") == "cpu"

    def test_device_policy_windows_cuda_mode(self):
        """Test DevicePolicy allows GPU in windows_cuda mode."""
        policy = DevicePolicy(ExecutionMode.WINDOWS_CUDA)
        policy.enforce()

        # Check no device override
        assert policy.get_device("cuda") == "cuda"
        assert policy.get_device("cuda:0") == "cuda:0"
        assert policy.get_device("cpu") == "cpu"

    def test_device_policy_is_gpu_allowed(self):
        """Test is_gpu_allowed() returns correct values."""
        policy_cpu = DevicePolicy(ExecutionMode.DOCKER_CPU)
        assert policy_cpu.is_gpu_allowed() is False

        policy_gpu = DevicePolicy(ExecutionMode.DOCKER_GPU)
        assert policy_gpu.is_gpu_allowed() is True

        policy_windows = DevicePolicy(ExecutionMode.WINDOWS_CUDA)
        assert policy_windows.is_gpu_allowed() is True

    def test_device_policy_double_enforce(self):
        """Test calling enforce() multiple times is safe."""
        policy = DevicePolicy(ExecutionMode.DOCKER_CPU)
        policy.enforce()
        policy.enforce()  # Should not raise error

        assert policy.get_device("cuda") == "cpu"

    def test_device_policy_get_device_without_enforce(self):
        """Test get_device() calls enforce() automatically if not enforced."""
        policy = DevicePolicy(ExecutionMode.DOCKER_CPU)
        # Don't call enforce() manually
        device = policy.get_device("cuda")
        assert device == "cpu"
        # Verify enforcement happened
        assert os.environ.get("CUDA_VISIBLE_DEVICES") == ""


class TestWorkerRunner:
    """Tests for WorkerRunner base class."""

    def test_worker_runner_abstract(self):
        """Test WorkerRunner is abstract and cannot be instantiated."""
        config = WorkerConfig()
        with pytest.raises(TypeError):
            WorkerRunner(config)  # Should fail because ABC

    def test_worker_runner_concrete_implementation(self):
        """Test concrete WorkerRunner implementation."""

        class ConcreteWorker(WorkerRunner):
            def setup(self):
                self.setup_called = True

            def run(self):
                self.run_called = True

            def shutdown(self):
                self.shutdown_called = True

        config = WorkerConfig(
            execution_mode=ExecutionMode.DOCKER_CPU,
            worker_id="test-worker"
        )

        worker = ConcreteWorker(config)
        assert worker.config.execution_mode == ExecutionMode.DOCKER_CPU
        assert worker.config.worker_id == "test-worker"
        assert worker.device_policy is not None

        # Test methods
        worker.setup()
        worker.run()
        worker.shutdown()

        assert worker.setup_called
        assert worker.run_called
        assert worker.shutdown_called

    def test_worker_runner_device_policy_enforcement(self):
        """Test WorkerRunner enforces device policy on initialization."""

        class ConcreteWorker(WorkerRunner):
            def setup(self):
                pass

            def run(self):
                pass

            def shutdown(self):
                pass

        # Docker CPU mode - should force CPU
        config_cpu = WorkerConfig(
            execution_mode=ExecutionMode.DOCKER_CPU,
            device="cuda"  # Request GPU
        )
        worker_cpu = ConcreteWorker(config_cpu)
        assert worker_cpu.config.device == "cpu"  # Overridden to CPU
        assert worker_cpu.get_effective_device() == "cpu"

        # Docker GPU mode - should allow GPU
        config_gpu = WorkerConfig(
            execution_mode=ExecutionMode.DOCKER_GPU,
            device="cuda"
        )
        worker_gpu = ConcreteWorker(config_gpu)
        assert worker_gpu.config.device == "cuda"  # Not overridden
        assert worker_gpu.get_effective_device() == "cuda"

    def test_worker_runner_log_startup_info(self):
        """Test log_startup_info() logs configuration."""

        class ConcreteWorker(WorkerRunner):
            def setup(self):
                pass

            def run(self):
                pass

            def shutdown(self):
                pass

        config = WorkerConfig(
            execution_mode=ExecutionMode.DOCKER_CPU,
            worker_id="test-worker"
        )
        worker = ConcreteWorker(config)

        # Should not raise error
        worker.log_startup_info()


class TestLegacyMode:
    """Tests for legacy mode detection and warnings."""

    def test_detect_legacy_mode_true(self):
        """Test detect_legacy_mode() returns True when EXECUTION_MODE not set."""
        with patch.dict(os.environ, {}, clear=True):
            assert detect_legacy_mode() is True

    def test_detect_legacy_mode_false(self):
        """Test detect_legacy_mode() returns False when EXECUTION_MODE set."""
        with patch.dict(os.environ, {"EXECUTION_MODE": "docker_cpu"}, clear=True):
            assert detect_legacy_mode() is False

    def test_warn_legacy_mode(self):
        """Test warn_legacy_mode() emits deprecation warning."""
        with patch.dict(os.environ, {}, clear=True):
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                warn_legacy_mode()

                assert len(w) == 1
                assert issubclass(w[0].category, DeprecationWarning)
                assert "EXECUTION_MODE" in str(w[0].message)

    def test_warn_legacy_mode_no_warning_when_set(self):
        """Test warn_legacy_mode() does not warn when EXECUTION_MODE set."""
        with patch.dict(os.environ, {"EXECUTION_MODE": "docker_cpu"}, clear=True):
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                warn_legacy_mode()

                # Should not emit warning
                assert len(w) == 0


class TestIntegration:
    """Integration tests for WorkerRunner components."""

    def test_end_to_end_docker_cpu_mode(self):
        """Test complete workflow in docker_cpu mode."""

        class TestWorker(WorkerRunner):
            def setup(self):
                self.initialized = True

            def run(self):
                self.executed = True

            def shutdown(self):
                self.cleaned_up = True

        # Simulate docker_cpu environment
        env_vars = {
            "EXECUTION_MODE": "docker_cpu",
            "WORKER_ID": "cpu-worker-1",
            "DEVICE": "cuda"  # Request GPU (will be overridden)
        }

        with patch.dict(os.environ, env_vars, clear=True):
            # Load config from environment
            config = WorkerConfig.from_env()

            # Create worker
            worker = TestWorker(config)

            # Verify configuration
            assert worker.config.execution_mode == ExecutionMode.DOCKER_CPU
            assert worker.config.device == "cpu"  # Overridden from "cuda"
            assert worker.device_policy.is_gpu_allowed() is False
            assert os.environ.get("CUDA_VISIBLE_DEVICES") == ""

            # Run worker lifecycle
            worker.setup()
            worker.run()
            worker.shutdown()

            assert worker.initialized
            assert worker.executed
            assert worker.cleaned_up

    def test_end_to_end_windows_cuda_mode(self):
        """Test complete workflow in windows_cuda mode."""

        class TestWorker(WorkerRunner):
            def setup(self):
                pass

            def run(self):
                pass

            def shutdown(self):
                pass

        # Simulate windows_cuda environment
        env_vars = {
            "EXECUTION_MODE": "windows_cuda",
            "WORKER_ID": "gpu-worker-1",
            "DEVICE": "cuda"
        }

        with patch.dict(os.environ, env_vars, clear=True):
            config = WorkerConfig.from_env()
            worker = TestWorker(config)

            # Verify GPU allowed
            assert worker.config.execution_mode == ExecutionMode.WINDOWS_CUDA
            assert worker.config.device == "cuda"  # Not overridden
            assert worker.device_policy.is_gpu_allowed() is True

    def test_end_to_end_mode_defaults(self):
        """Test configuration with mode defaults from global.yaml."""

        class TestWorker(WorkerRunner):
            def setup(self):
                pass

            def run(self):
                pass

            def shutdown(self):
                pass

        mode_defaults = {
            "device": "cpu",
            "max_retries": 5,
            "poll_interval": 3.0
        }

        env_vars = {
            "EXECUTION_MODE": "docker_cpu",
            "MAX_RETRIES": "7"  # Override mode default
        }

        with patch.dict(os.environ, env_vars, clear=True):
            config = WorkerConfig.from_env(mode_defaults)
            worker = TestWorker(config)

            # Verify precedence
            assert worker.config.device == "cpu"  # From mode defaults
            assert worker.config.max_retries == 7  # From ENV (overrides mode)
            assert worker.config.poll_interval == 3.0  # From mode defaults
