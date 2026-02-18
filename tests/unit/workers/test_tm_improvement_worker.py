"""
Unit tests for TM improvement worker.

Tests:
- Worker configuration loading
- Candidate improvement with mocked LLM
- VRAM guard logic with mocked GPU readings
- Validation logic
- Time and call limits
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from pathlib import Path

from src.workers.tm_improvement_worker import (
    TMImprovementWorker,
    TMImprovementWorkerConfig,
)
from src.tm.improvement_queue import ImprovementCandidate


@pytest.fixture
def worker_config(tmp_path):
    """Create worker configuration for testing."""
    return TMImprovementWorkerConfig(
        config_root="config/",
        tm_path=str(tmp_path / "tm"),
        mode="oneshot",
        runs_per_day=5,
        window_start="10:00",
        window_end="22:00",
        timezone="America/Los_Angeles",
        jitter_minutes=10,
        candidates_per_run=10,
        max_llm_calls_per_run=50,
        max_seconds_per_run=60,
        llm_provider="ollama",
        llm_model="llama2",
        llm_base_url="http://localhost:11434",
        llm_timeout_seconds=30,
        llm_temperature=0.3,
        max_gpu_memory_percent=60,
        preflight_check=True,
        abort_on_high_usage=True,
        device="cpu",  # Use CPU for tests
    )


@pytest.fixture
def mock_dependencies(tmp_path):
    """Create mocked dependencies for worker."""
    # Mock ConfigService
    mock_config_service = Mock()
    mock_config_service.config_root = "config/"
    mock_config_service.config = {
        "paths": {"tm_data_dir": str(tmp_path / "tm")},
        "tm_improvement": {
            "schedule": {},
            "batch": {},
            "llm": {},
            "resources": {},
            "queue": {},
        },
    }

    # Mock ImprovementQueue
    mock_queue = Mock()
    mock_queue.stats.return_value = {
        "queue_size": 5,
        "seen_hashes": 10,
    }

    # Mock TranslationMemory
    mock_tm = Mock()
    mock_tm.store.return_value = True

    # Mock LLMClient
    mock_llm = Mock()
    mock_llm.is_available.return_value = True

    return {
        "config_service": mock_config_service,
        "queue": mock_queue,
        "tm": mock_tm,
        "llm": mock_llm,
    }


def test_worker_initialization(worker_config):
    """Test worker initialization."""
    worker = TMImprovementWorker(worker_config)

    assert worker.config == worker_config
    assert worker.config_service is None
    assert worker.tm is None
    assert worker.improvement_queue is None
    assert worker.llm_client is None
    assert worker.scheduler is None


def test_validate_improved_translation_valid(worker_config):
    """Test validation of valid improved translation."""
    worker = TMImprovementWorker(worker_config)

    original = "Hello {name}, welcome to {site}!"
    improved = "Hi {name}, bienvenue to {site}!"

    result = worker._validate_improved_translation(original, improved)
    assert result is True


def test_validate_improved_translation_empty(worker_config):
    """Test validation rejects empty improved translation."""
    worker = TMImprovementWorker(worker_config)

    original = "Hello world"
    improved = ""

    result = worker._validate_improved_translation(original, improved)
    assert result is False


def test_validate_improved_translation_same_as_original(worker_config):
    """Test validation rejects translation same as original."""
    worker = TMImprovementWorker(worker_config)

    original = "Hello world"
    improved = "Hello world"

    result = worker._validate_improved_translation(original, improved)
    assert result is False


def test_validate_improved_translation_placeholder_mismatch(worker_config):
    """Test validation rejects placeholder mismatch."""
    worker = TMImprovementWorker(worker_config)

    original = "Hello {name}, welcome to {site}!"
    improved = "Hi {name}, bienvenue!"  # Missing {site} placeholder

    result = worker._validate_improved_translation(original, improved)
    assert result is False


def test_validate_improved_translation_markdown_loss(worker_config):
    """Test validation detects markdown formatting loss."""
    worker = TMImprovementWorker(worker_config)

    original = "This is **bold** and *italic* text with `code`"
    improved = "This is bold and italic text with code"  # Lost markdown

    result = worker._validate_improved_translation(original, improved)
    assert result is False


def test_validate_improved_translation_markdown_preserved(worker_config):
    """Test validation accepts translation with markdown preserved."""
    worker = TMImprovementWorker(worker_config)

    original = "This is **bold** and *italic* text"
    improved = "Ceci est **gras** et *italique* texte"

    result = worker._validate_improved_translation(original, improved)
    assert result is True


def test_improve_candidate_success(worker_config, mock_dependencies):
    """Test successful candidate improvement."""
    worker = TMImprovementWorker(worker_config)
    worker.config_service = mock_dependencies["config_service"]
    worker.tm = mock_dependencies["tm"]
    worker.llm_client = mock_dependencies["llm"]

    # Mock LLM to return improved translation
    mock_dependencies["llm"].adapt_translation.return_value = "Improved translation"

    candidate = ImprovementCandidate(
        site_id="docs.aspose.net",
        src_lang="en",
        tgt_lang="de",
        text="Original text",
        translation="Original translation",
        context="test",
        metadata={"similarity_score": 0.75},
    )

    result = worker._improve_candidate(candidate)

    assert result == "improved"
    mock_dependencies["llm"].adapt_translation.assert_called_once()
    mock_dependencies["tm"].store.assert_called_once()

    # Check that store was called with force_update=True
    call_kwargs = mock_dependencies["tm"].store.call_args[1]
    assert call_kwargs["force_update"] is True
    assert "improved_by" in call_kwargs["metadata"]
    assert call_kwargs["metadata"]["improved_by"] == "tm_improvement_worker"


def test_improve_candidate_llm_returns_none(worker_config, mock_dependencies):
    """Test candidate improvement when LLM returns None."""
    worker = TMImprovementWorker(worker_config)
    worker.config_service = mock_dependencies["config_service"]
    worker.tm = mock_dependencies["tm"]
    worker.llm_client = mock_dependencies["llm"]

    # Mock LLM to return None
    mock_dependencies["llm"].adapt_translation.return_value = None

    candidate = ImprovementCandidate(
        site_id="docs.aspose.net",
        src_lang="en",
        tgt_lang="de",
        text="Original text",
        translation="Original translation",
    )

    result = worker._improve_candidate(candidate)

    assert result == "skipped"
    mock_dependencies["tm"].store.assert_not_called()


def test_improve_candidate_validation_fails(worker_config, mock_dependencies):
    """Test candidate improvement when validation fails."""
    worker = TMImprovementWorker(worker_config)
    worker.config_service = mock_dependencies["config_service"]
    worker.tm = mock_dependencies["tm"]
    worker.llm_client = mock_dependencies["llm"]

    # Mock LLM to return same text (will fail validation)
    mock_dependencies["llm"].adapt_translation.return_value = "Original translation"

    candidate = ImprovementCandidate(
        site_id="docs.aspose.net",
        src_lang="en",
        tgt_lang="de",
        text="Original text",
        translation="Original translation",
    )

    result = worker._improve_candidate(candidate)

    assert result == "skipped"
    mock_dependencies["tm"].store.assert_not_called()


def test_improve_candidate_store_fails(worker_config, mock_dependencies):
    """Test candidate improvement when store fails."""
    worker = TMImprovementWorker(worker_config)
    worker.config_service = mock_dependencies["config_service"]
    worker.tm = mock_dependencies["tm"]
    worker.llm_client = mock_dependencies["llm"]

    # Mock LLM to return improved translation
    mock_dependencies["llm"].adapt_translation.return_value = "Improved translation"

    # Mock TM store to return False
    mock_dependencies["tm"].store.return_value = False

    candidate = ImprovementCandidate(
        site_id="docs.aspose.net",
        src_lang="en",
        tgt_lang="de",
        text="Original text",
        translation="Original translation",
    )

    result = worker._improve_candidate(candidate)

    assert result == "failed"


def test_check_gpu_usage_no_gpu(worker_config):
    """Test GPU usage check when GPU not available."""
    worker = TMImprovementWorker(worker_config)
    worker.gpu_manager = None

    usage = worker._check_gpu_usage()
    assert usage is None


@patch("src.workers.tm_improvement_worker.torch.cuda.is_available")
def test_check_gpu_usage_with_gpu(mock_cuda_available, worker_config):
    """Test GPU usage check when GPU available."""
    mock_cuda_available.return_value = True

    worker = TMImprovementWorker(worker_config)

    # Mock GPU manager
    mock_gpu_manager = Mock()
    mock_gpu_info = Mock()
    mock_gpu_info.total_mb = 8192
    mock_gpu_info.used_mb = 4096  # 50% usage
    mock_gpu_manager.get_gpu_memory.return_value = mock_gpu_info

    worker.gpu_manager = mock_gpu_manager

    usage = worker._check_gpu_usage()
    assert usage == 50.0


def test_execute_improvement_run_empty_queue(worker_config, mock_dependencies):
    """Test improvement run with empty queue."""
    worker = TMImprovementWorker(worker_config)
    worker.config_service = mock_dependencies["config_service"]
    worker.improvement_queue = mock_dependencies["queue"]
    worker.tm = mock_dependencies["tm"]
    worker.llm_client = mock_dependencies["llm"]

    # Mock empty queue
    mock_dependencies["queue"].pop_candidates.return_value = []

    result = worker._execute_improvement_run()

    assert result["status"] == "success"
    assert result["candidates_pulled"] == 0
    assert result["improved_count"] == 0


def test_execute_improvement_run_processes_candidates(worker_config, mock_dependencies):
    """Test improvement run processes candidates."""
    worker = TMImprovementWorker(worker_config)
    worker.config_service = mock_dependencies["config_service"]
    worker.improvement_queue = mock_dependencies["queue"]
    worker.tm = mock_dependencies["tm"]
    worker.llm_client = mock_dependencies["llm"]

    # Mock queue with 3 candidates
    candidates = [
        ImprovementCandidate(
            site_id="docs.aspose.net",
            src_lang="en",
            tgt_lang="de",
            text=f"Text {i}",
            translation=f"Translation {i}",
        )
        for i in range(3)
    ]
    mock_dependencies["queue"].pop_candidates.return_value = candidates

    # Mock LLM to return improved translations
    mock_dependencies["llm"].adapt_translation.return_value = "Improved translation"

    result = worker._execute_improvement_run()

    assert result["status"] == "success"
    assert result["candidates_pulled"] == 3
    assert result["improved_count"] == 3
    assert result["llm_calls"] == 3


def test_execute_improvement_run_respects_call_limit(worker_config, mock_dependencies):
    """Test improvement run respects LLM call limit."""
    # Set low call limit
    worker_config.max_llm_calls_per_run = 2

    worker = TMImprovementWorker(worker_config)
    worker.config_service = mock_dependencies["config_service"]
    worker.improvement_queue = mock_dependencies["queue"]
    worker.tm = mock_dependencies["tm"]
    worker.llm_client = mock_dependencies["llm"]

    # Mock queue with 5 candidates (more than limit)
    candidates = [
        ImprovementCandidate(
            site_id="docs.aspose.net",
            src_lang="en",
            tgt_lang="de",
            text=f"Text {i}",
            translation=f"Translation {i}",
        )
        for i in range(5)
    ]
    mock_dependencies["queue"].pop_candidates.return_value = candidates

    # Mock LLM to return improved translations
    mock_dependencies["llm"].adapt_translation.return_value = "Improved translation"

    result = worker._execute_improvement_run()

    # Should only process 2 candidates (call limit)
    assert result["llm_calls"] <= 2


def test_execute_improvement_run_preflight_check_aborts_high_usage(
    worker_config, mock_dependencies
):
    """Test preflight check aborts when GPU usage high."""
    worker = TMImprovementWorker(worker_config)
    worker.config_service = mock_dependencies["config_service"]
    worker.improvement_queue = mock_dependencies["queue"]
    worker.llm_client = mock_dependencies["llm"]
    worker._llm_unavailable = False

    # Mock high GPU usage
    mock_gpu_manager = Mock()
    mock_gpu_info = Mock()
    mock_gpu_info.total_mb = 8192
    mock_gpu_info.used_mb = 5120  # 62.5% usage (above 60% threshold)
    mock_gpu_manager.get_gpu_memory.return_value = mock_gpu_info

    worker.gpu_manager = mock_gpu_manager

    result = worker._execute_improvement_run()

    assert result["status"] == "aborted"
    assert result["reason"] == "gpu_usage_high"
    assert result["gpu_usage_percent"] == 62.5


def test_execute_improvement_run_no_preflight_check(worker_config, mock_dependencies):
    """Test improvement run without preflight check."""
    # Disable preflight check
    worker_config.preflight_check = False

    worker = TMImprovementWorker(worker_config)
    worker.config_service = mock_dependencies["config_service"]
    worker.improvement_queue = mock_dependencies["queue"]
    worker.tm = mock_dependencies["tm"]
    worker.llm_client = mock_dependencies["llm"]

    # Mock queue with candidates
    candidates = [
        ImprovementCandidate(
            site_id="docs.aspose.net",
            src_lang="en",
            tgt_lang="de",
            text="Text",
            translation="Translation",
        )
    ]
    mock_dependencies["queue"].pop_candidates.return_value = candidates

    # Mock LLM
    mock_dependencies["llm"].adapt_translation.return_value = "Improved translation"

    # Mock high GPU usage (should not abort because preflight disabled)
    mock_gpu_manager = Mock()
    mock_gpu_info = Mock()
    mock_gpu_info.total_mb = 8192
    mock_gpu_info.used_mb = 5120  # 62.5% usage
    mock_gpu_manager.get_gpu_memory.return_value = mock_gpu_info
    worker.gpu_manager = mock_gpu_manager

    result = worker._execute_improvement_run()

    # Should not abort (preflight disabled)
    assert result["status"] == "success"
    assert result["improved_count"] == 1


def test_config_from_config_service():
    """Test creating worker config from ConfigService."""
    mock_config_service = Mock()
    mock_config_service.config_root = "config/"
    mock_config_service.config = {
        "paths": {"tm_data_dir": "data/tm"},
        "tm_improvement": {
            "schedule": {
                "runs_per_day": 4,
                "window_start": "09:00",
                "window_end": "21:00",
                "timezone": "America/New_York",
                "jitter_minutes": 15,
            },
            "batch": {
                "candidates_per_run": 100,
                "max_llm_calls_per_run": 300,
                "max_seconds_per_run": 1800,
            },
            "llm": {
                "provider": "openai",
                "model": "gpt-3.5-turbo",
                "base_url": None,
                "api_key": "test-key",
                "timeout_seconds": 60,
                "temperature": 0.5,
            },
            "resources": {
                "max_gpu_memory_percent": 70,
                "preflight_check": False,
                "abort_on_high_usage": False,
            },
            "queue": {
                "enabled": True,
            },
        },
    }

    config = TMImprovementWorkerConfig.from_config_service(
        mock_config_service, mode="daemon"
    )

    assert config.mode == "daemon"
    assert config.runs_per_day == 4
    assert config.window_start == "09:00"
    assert config.window_end == "21:00"
    assert config.timezone == "America/New_York"
    assert config.candidates_per_run == 100
    assert config.llm_provider == "openai"
    assert config.llm_model == "gpt-3.5-turbo"
    assert config.max_gpu_memory_percent == 70
    assert config.preflight_check is False
    assert config.abort_on_high_usage is False
