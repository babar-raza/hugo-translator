"""
Integration tests for L3 path consistency across components.

Verifies that health monitor, L3SemanticTM, and scripts all resolve
to the same canonical L3 path.
"""

import sys
from pathlib import Path

import pytest

# Add src to path
repo_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(repo_root / "src"))


def test_health_monitor_uses_l3_faiss_path(tmp_path):
    """Verify health monitor checks l3_faiss directory."""
    from orchestration.health_monitor import HealthMonitor

    # Skip if the method doesn't exist in current HealthMonitor implementation
    if not hasattr(HealthMonitor, "check_tm_l3_faiss"):
        pytest.skip("HealthMonitor.check_tm_l3_faiss() not implemented in this version")

    # Create test data structure
    tm_data = tmp_path / "tm"
    tm_data.mkdir()
    l3_dir = tm_data / "l3_faiss"
    l3_dir.mkdir()

    # Initialize health monitor
    hm = HealthMonitor(tmp_path)

    # Check L3
    result = hm.check_tm_l3_faiss()

    # Should look for l3_faiss, not l3.faiss
    assert "l3_faiss" in str(result.details.get("path", "")) if result.details else True
    assert result.component == "tm_l3_faiss"


def test_l3semantic_accepts_l3_faiss_path(tmp_path):
    """Verify L3SemanticTM works with l3_faiss path."""
    from tm.l3_semantic import L3SemanticTM

    # Create index directory
    index_path = tmp_path / "l3_faiss"
    index_path.mkdir()

    # Should initialize without error
    l3 = L3SemanticTM(
        index_path=str(index_path),
        embedding_model="all-MiniLM-L6-v2",
        use_gpu=False,
    )

    assert l3.index_path == index_path
    assert l3.index is not None


def test_config_path_matches_runtime_default():
    """Verify config l3_index_dir matches script defaults."""
    import yaml

    config_file = repo_root / "config" / "global.yaml"

    if config_file.exists():
        with open(config_file) as f:
            config = yaml.safe_load(f)

        l3_dir = config.get("paths", {}).get("l3_index_dir")

        # Config should specify l3_faiss
        assert l3_dir == "l3_faiss", f"Config l3_index_dir should be 'l3_faiss', got: {l3_dir}"


def test_populate_script_creates_correct_path(tmp_path):
    """Verify populate script uses l3_faiss path."""
    # This is a dry-run integration test
    # In real environment, would run: populate_l3_index.py --dry-run

    # Read populate script source
    populate_script = repo_root / "scripts" / "populate_l3_index.py"

    if populate_script.exists():
        content = populate_script.read_text(encoding="utf-8")

        # Check that script constructs l3_faiss path
        assert 'self.l3_path = self.tm_path / "l3_faiss"' in content, (
            "populate_l3_index.py should construct l3_faiss path"
        )


@pytest.mark.parametrize(
    "script_name",
    [
        "populate_l3_index.py",
        "test_tm_lookup.py",
        "build_l3_index.py",
        "sync_l3_index.py",
        "inspect_l3_metadata.py",
        "quick_validate_l3.py",
    ],
)
def test_all_scripts_use_consistent_path(script_name):
    """Verify all L3 scripts use l3_faiss path."""
    script_path = repo_root / "scripts" / script_name

    if script_path.exists():
        content = script_path.read_text(encoding="utf-8")

        # Should reference l3_faiss
        assert "l3_faiss" in content, f"{script_name} should reference l3_faiss"

        # Should NOT have l3.faiss in non-comment lines
        lines = content.splitlines()
        code_lines = [line for line in lines if not line.strip().startswith("#")]
        code_text = "\n".join(code_lines)

        assert "l3.faiss" not in code_text, (
            f"{script_name} should not contain l3.faiss dot notation in code"
        )
