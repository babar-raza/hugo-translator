"""
Unit tests for L3 path consistency across the codebase.

Ensures all L3 FAISS index paths use the standardized `l3_faiss` naming
and that no legacy `l3.faiss` (dot notation) references remain.
"""
import subprocess
from pathlib import Path


def test_no_dot_notation_in_runtime_code():
    """Verify no l3.faiss dot notation exists in src/ or scripts/."""
    repo_root = Path(__file__).parent.parent.parent

    # Run grep excluding binary files, __pycache__, and lint script
    result = subprocess.run(
        [
            "grep", "-rn", r"l3\.faiss",
            str(repo_root / "src"),
            str(repo_root / "scripts"),
            "--exclude-dir=__pycache__",
            "--exclude=*.pyc",
            "--exclude=lint_l3_paths.sh",
        ],
        capture_output=True,
        text=True,
    )

    # Filter out binary file matches
    matches = [
        line for line in result.stdout.splitlines()
        if "Binary file" not in line
    ]

    assert len(matches) == 0, (
        f"Found {len(matches)} instance(s) of l3.faiss dot notation:\n"
        + "\n".join(matches[:5])
    )


def test_all_underscore_notation():
    """Verify l3_faiss underscore notation exists in expected places."""
    repo_root = Path(__file__).parent.parent.parent

    # Check health monitor
    health_monitor = repo_root / "src" / "orchestration" / "health_monitor.py"
    if health_monitor.exists():
        content = health_monitor.read_text()
        assert "l3_faiss" in content, (
            "health_monitor.py should reference l3_faiss"
        )


def test_config_defines_l3_path():
    """Verify config/global.yaml defines l3_index_dir."""
    repo_root = Path(__file__).parent.parent.parent
    config_file = repo_root / "config" / "global.yaml"

    if config_file.exists():
        content = config_file.read_text()
        assert "l3_index_dir" in content, (
            "config/global.yaml should define l3_index_dir"
        )


def test_scripts_use_correct_default_path():
    """Verify scripts default to l3_faiss path."""
    repo_root = Path(__file__).parent.parent.parent
    scripts_dir = repo_root / "scripts"

    critical_scripts = [
        "populate_l3_index.py",
        "test_tm_lookup.py",
        "build_l3_index.py",
        "sync_l3_index.py",
    ]

    for script_name in critical_scripts:
        script_path = scripts_dir / script_name
        if script_path.exists():
            content = script_path.read_text()
            # Should contain l3_faiss
            assert "l3_faiss" in content, (
                f"{script_name} should use l3_faiss path"
            )
            # Should NOT contain l3.faiss (dot notation)
            # Allow in comments but not in actual path strings
            lines_with_dot = [
                line for line in content.splitlines()
                if 'l3.faiss' in line and not line.strip().startswith('#')
            ]
            assert len(lines_with_dot) == 0, (
                f"{script_name} contains l3.faiss dot notation: "
                + "\n".join(lines_with_dot[:3])
            )


def test_lint_script_passes():
    """Verify the lint script runs and passes."""
    repo_root = Path(__file__).parent.parent.parent
    lint_script = repo_root / "scripts" / "lint_l3_paths.sh"

    if lint_script.exists():
        result = subprocess.run(
            ["bash", str(lint_script)],
            capture_output=True,
            text=True,
            cwd=repo_root,
        )

        assert result.returncode == 0, (
            f"Lint script failed:\n{result.stdout}\n{result.stderr}"
        )
        assert "PASS" in result.stdout
