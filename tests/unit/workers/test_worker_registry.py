"""Tests for worker registry loading and validation."""

import textwrap
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def tmp_registry(tmp_path):
    """Return a helper that writes a workers.yaml and returns its path."""

    def _write(content: str) -> Path:
        p = tmp_path / "workers.yaml"
        p.write_text(textwrap.dedent(content), encoding="utf-8")
        return p

    return _write


MINIMAL_WORKER = """\
workers:
  test_worker:
    enabled: true
    mode: oneshot
    module: src.workers.test
    cli_args: ["--mode", "oneshot"]
    trigger:
      type: queue_non_empty
      queue_path: "data/q.jsonl"
    cooldown_seconds: 60
    max_concurrent: 1
    safe_command: "python -m src.workers.test"
    useful_work_criteria: "items > 0"
"""


class TestLoadWorkerRegistry:
    def test_loads_valid_registry(self, tmp_registry):
        from src.utils.config_loader import load_worker_registry

        p = tmp_registry(MINIMAL_WORKER)
        data = load_worker_registry(p)
        assert "workers" in data
        assert "test_worker" in data["workers"]
        assert data["workers"]["test_worker"]["enabled"] is True

    def test_missing_file_raises(self, tmp_path):
        from src.utils.config_loader import load_worker_registry

        with pytest.raises(FileNotFoundError):
            load_worker_registry(tmp_path / "nope.yaml")

    def test_missing_required_field_raises(self, tmp_registry):
        from src.utils.config_loader import load_worker_registry

        content = MINIMAL_WORKER.replace("    safe_command", "    # safe_command")
        # Remove safe_command line entirely
        lines = [l for l in MINIMAL_WORKER.splitlines(True) if "safe_command" not in l]
        p = tmp_registry("".join(lines))
        with pytest.raises(ValueError, match="missing required fields"):
            load_worker_registry(p)

    def test_unknown_trigger_type_raises(self, tmp_registry):
        from src.utils.config_loader import load_worker_registry

        bad = MINIMAL_WORKER.replace("type: queue_non_empty", "type: magic_trigger")
        p = tmp_registry(bad)
        with pytest.raises(ValueError, match="unknown trigger type"):
            load_worker_registry(p)

    def test_empty_workers_raises(self, tmp_registry):
        from src.utils.config_loader import load_worker_registry

        p = tmp_registry("workers: {}")
        with pytest.raises(ValueError, match="non-empty"):
            load_worker_registry(p)

    def test_multi_trigger_validates_conditions(self, tmp_registry):
        from src.utils.config_loader import load_worker_registry

        content = """\
        workers:
          w:
            enabled: true
            mode: oneshot
            module: m
            cli_args: []
            trigger:
              type: multi
              conditions:
                - type: queue_non_empty
                  queue_path: "q.jsonl"
                - type: file_change
                  paths: ["config/"]
                  pattern: "*.yaml"
            cooldown_seconds: 60
            max_concurrent: 1
            safe_command: "cmd"
            useful_work_criteria: "x"
        """
        p = tmp_registry(content)
        data = load_worker_registry(p)
        assert len(data["workers"]["w"]["trigger"]["conditions"]) == 2

    def test_multi_trigger_empty_conditions_raises(self, tmp_registry):
        from src.utils.config_loader import load_worker_registry

        content = """\
        workers:
          w:
            enabled: true
            mode: oneshot
            module: m
            cli_args: []
            trigger:
              type: multi
              conditions: []
            cooldown_seconds: 60
            max_concurrent: 1
            safe_command: "cmd"
            useful_work_criteria: "x"
        """
        p = tmp_registry(content)
        with pytest.raises(ValueError, match="non-empty 'conditions'"):
            load_worker_registry(p)

    def test_disabled_worker_still_loads(self, tmp_registry):
        from src.utils.config_loader import load_worker_registry

        content = MINIMAL_WORKER.replace("enabled: true", "enabled: false")
        p = tmp_registry(content)
        data = load_worker_registry(p)
        assert data["workers"]["test_worker"]["enabled"] is False

    def test_production_registry_is_valid(self):
        """Validate the actual config/workers.yaml in the repo."""
        from src.utils.config_loader import load_worker_registry

        repo_root = Path(__file__).parent.parent.parent.parent
        registry_path = repo_root / "config" / "workers.yaml"
        if not registry_path.exists():
            pytest.skip("config/workers.yaml not found")
        data = load_worker_registry(registry_path)
        assert len(data["workers"]) >= 3
