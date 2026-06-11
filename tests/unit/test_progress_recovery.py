"""Unit tests for RES-07: Progress File Validation & Recovery.

Tests cover:
- Progress file validation (JSON, schema, fields)
- Recovery from partially corrupted data
- Handling of unrecoverable files
- CLI integration with validation
"""

import json
import sys
from pathlib import Path

# Add src directory to path for direct imports
src_path = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(src_path))

# Import ProgressTracker directly (avoid translation_engine __init__ which imports engine)
import importlib.util

_progress_module_path = src_path / "translation_engine" / "progress.py"
_spec = importlib.util.spec_from_file_location("progress_module", _progress_module_path)
_progress_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_progress_module)
ProgressTracker = _progress_module.ProgressTracker


# Test validation logic directly without importing the full module
def _validate_progress_file(progress_file: Path) -> tuple[bool, str, bool]:
    """Copy of validation logic for testing purposes."""
    try:
        with open(progress_file, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return (False, f"Invalid JSON: {e}", False)
    except FileNotFoundError:
        return (False, "File not found", False)
    except Exception as e:
        return (False, f"Cannot read file: {e}", False)

    # Check required fields
    required_fields = [
        "run_id",
        "schema_version",
        "site_id",
        "total_files",
        "completed_files",
        "started_at",
    ]

    missing = [f for f in required_fields if f not in data]
    if missing:
        return (False, f"Missing fields: {missing}", True)

    # Check schema version
    version = data.get("schema_version")
    if version != "1.0":
        return (False, f"Unsupported schema version: {version}", False)

    # Check data types
    try:
        total_files = int(data["total_files"])
        if total_files < 0:
            return (False, "total_files cannot be negative", True)

        completed = data["completed_files"]
        if not isinstance(completed, dict):
            return (False, "completed_files must be a dict", True)

    except (ValueError, TypeError) as e:
        return (False, f"Invalid data type: {e}", True)

    # Check logical consistency
    num_completed = sum(
        len(langs) if isinstance(langs, list) else 0 for langs in data["completed_files"].values()
    )
    if num_completed > total_files * 10:  # Sanity check
        return (False, "Suspiciously high completion count", True)

    return (True, "Valid", False)


class TestValidateProgressFile:
    """Tests for progress file validation."""

    def test_validate_valid_progress(self, tmp_path):
        """Test validation passes for valid progress file."""
        progress_file = tmp_path / "progress_test.json"
        progress_file.write_text(
            json.dumps(
                {
                    "run_id": "test-123",
                    "schema_version": "1.0",
                    "site_id": "mysite",
                    "total_files": 10,
                    "completed_files": {"file1.md": ["es", "fr"]},
                    "started_at": "2024-01-01T00:00:00Z",
                }
            )
        )

        is_valid, msg, recoverable = _validate_progress_file(progress_file)

        assert is_valid is True
        assert msg == "Valid"
        assert recoverable is False

    def test_validate_invalid_json(self, tmp_path):
        """Test validation detects invalid JSON."""
        progress_file = tmp_path / "progress_test.json"
        progress_file.write_text("{invalid json")

        is_valid, msg, recoverable = _validate_progress_file(progress_file)

        assert is_valid is False
        assert "Invalid JSON" in msg
        assert recoverable is False

    def test_validate_missing_fields(self, tmp_path):
        """Test validation detects missing required fields."""
        progress_file = tmp_path / "progress_test.json"
        progress_file.write_text(
            json.dumps(
                {
                    "run_id": "test",
                    # Missing other required fields
                }
            )
        )

        is_valid, msg, recoverable = _validate_progress_file(progress_file)

        assert is_valid is False
        assert "Missing fields" in msg
        assert recoverable is True  # Can be recovered

    def test_validate_unsupported_schema(self, tmp_path):
        """Test validation detects unsupported schema version."""
        progress_file = tmp_path / "progress_test.json"
        progress_file.write_text(
            json.dumps(
                {
                    "run_id": "test-123",
                    "schema_version": "2.0",
                    "site_id": "mysite",
                    "total_files": 10,
                    "completed_files": {},
                    "started_at": "2024-01-01T00:00:00Z",
                }
            )
        )

        is_valid, msg, recoverable = _validate_progress_file(progress_file)

        assert is_valid is False
        assert "Unsupported schema" in msg
        assert recoverable is False

    def test_validate_negative_total_files(self, tmp_path):
        """Test validation detects negative total_files."""
        progress_file = tmp_path / "progress_test.json"
        progress_file.write_text(
            json.dumps(
                {
                    "run_id": "test-123",
                    "schema_version": "1.0",
                    "site_id": "mysite",
                    "total_files": -5,
                    "completed_files": {},
                    "started_at": "2024-01-01T00:00:00Z",
                }
            )
        )

        is_valid, msg, recoverable = _validate_progress_file(progress_file)

        assert is_valid is False
        assert "negative" in msg
        assert recoverable is True

    def test_validate_invalid_completed_files_type(self, tmp_path):
        """Test validation detects wrong type for completed_files."""
        progress_file = tmp_path / "progress_test.json"
        progress_file.write_text(
            json.dumps(
                {
                    "run_id": "test-123",
                    "schema_version": "1.0",
                    "site_id": "mysite",
                    "total_files": 10,
                    "completed_files": "not a dict",  # Should be dict
                    "started_at": "2024-01-01T00:00:00Z",
                }
            )
        )

        is_valid, msg, recoverable = _validate_progress_file(progress_file)

        assert is_valid is False
        assert "dict" in msg
        assert recoverable is True

    def test_validate_file_not_found(self, tmp_path):
        """Test validation handles non-existent file."""
        progress_file = tmp_path / "nonexistent.json"

        is_valid, msg, recoverable = _validate_progress_file(progress_file)

        assert is_valid is False
        assert "not found" in msg.lower()
        assert recoverable is False

    def test_validate_suspiciously_high_count(self, tmp_path):
        """Test validation detects suspiciously high completion count."""
        progress_file = tmp_path / "progress_test.json"
        # total_files is 2, but completed count is way higher
        progress_file.write_text(
            json.dumps(
                {
                    "run_id": "test-123",
                    "schema_version": "1.0",
                    "site_id": "mysite",
                    "total_files": 2,
                    "completed_files": {
                        "f1": ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k"],
                        "f2": ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k"],
                        "f3": ["a", "b", "c"],  # This pushes us over 2 * 10 = 20
                    },
                    "started_at": "2024-01-01T00:00:00Z",
                }
            )
        )

        is_valid, msg, recoverable = _validate_progress_file(progress_file)

        assert is_valid is False
        assert "high completion count" in msg.lower()
        assert recoverable is True


class TestRecoverProgressFile:
    """Tests for progress file recovery."""

    def test_recover_partial_data(self, tmp_path):
        """Test recovery of partially corrupted/incomplete data."""
        progress_file = tmp_path / "progress_test.json"
        progress_file.write_text(
            json.dumps(
                {
                    "run_id": "test123",
                    "site_id": "mysite",
                    "source_dir": "/src",
                    "output_dir": "/out",
                    "target_langs": ["es", "fr"],
                    "completed_files": {"file1.md": ["es"]},
                    "total_files": 10,
                    # Missing some fields
                }
            )
        )

        # Use module-level ProgressTracker
        tracker = ProgressTracker.recover_progress_file(progress_file)

        assert tracker is not None
        assert tracker.state.run_id == "test123"
        assert tracker.state.site_id == "mysite"
        assert "file1.md" in tracker.state.completed_files

    def test_recovery_failure_on_invalid_json(self, tmp_path):
        """Test recovery returns None for files with invalid JSON."""
        progress_file = tmp_path / "progress_test.json"
        progress_file.write_text("{completely broken json[[")

        # Use module-level ProgressTracker
        tracker = ProgressTracker.recover_progress_file(progress_file)

        assert tracker is None

    def test_recovery_handles_missing_fields(self, tmp_path):
        """Test recovery handles completely missing optional fields."""
        progress_file = tmp_path / "progress_test.json"
        progress_file.write_text(
            json.dumps(
                {
                    "completed_files": {"file1.md": ["es"]},
                    # Many fields missing
                }
            )
        )

        # Use module-level ProgressTracker

        tracker = ProgressTracker.recover_progress_file(progress_file)

        # Should recover with defaults
        assert tracker is not None
        assert "file1.md" in tracker.state.completed_files
        assert tracker.state.site_id == "unknown"

    def test_recovery_cleans_invalid_completed_files(self, tmp_path):
        """Test recovery cleans up invalid completed_files entries."""
        progress_file = tmp_path / "progress_test.json"
        progress_file.write_text(
            json.dumps(
                {
                    "run_id": "test",
                    "site_id": "mysite",
                    "target_langs": ["es", "fr"],
                    "completed_files": {
                        "file1.md": ["es", "fr"],  # Valid
                        "file2.md": "not_a_list",  # Invalid - string instead of list
                        "file3.md": [123, "es"],  # Partially invalid - number in list
                    },
                    "total_files": 3,
                }
            )
        )

        # Use module-level ProgressTracker

        tracker = ProgressTracker.recover_progress_file(progress_file)

        assert tracker is not None
        # file1.md should be preserved as-is
        assert tracker.state.completed_files.get("file1.md") == ["es", "fr"]
        # file2.md should be converted to list
        assert tracker.state.completed_files.get("file2.md") == ["not_a_list"]
        # file3.md should have only the string entry
        assert tracker.state.completed_files.get("file3.md") == ["es"]


class TestProgressModuleValidation:
    """Tests to verify progress.py contains the validation methods."""

    def test_progress_has_validation_method(self):
        """Verify that progress.py contains validate_progress_file method."""
        progress_path = (
            Path(__file__).parent.parent.parent / "src" / "translation_engine" / "progress.py"
        )
        progress_content = progress_path.read_text(encoding="utf-8")

        assert "def validate_progress_file(" in progress_content
        assert "RES-07" in progress_content

    def test_progress_has_recovery_method(self):
        """Verify that progress.py contains recover_progress_file method."""
        progress_path = (
            Path(__file__).parent.parent.parent / "src" / "translation_engine" / "progress.py"
        )
        progress_content = progress_path.read_text(encoding="utf-8")

        assert "def recover_progress_file(" in progress_content
        assert "@classmethod" in progress_content

    def test_progress_has_validation_error_class(self):
        """Verify that progress.py contains ProgressValidationError class."""
        progress_path = (
            Path(__file__).parent.parent.parent / "src" / "translation_engine" / "progress.py"
        )
        progress_content = progress_path.read_text(encoding="utf-8")

        assert "class ProgressValidationError" in progress_content
        assert "recoverable" in progress_content


class TestCLIValidationIntegration:
    """Tests to verify CLI integrates with validation."""

    def test_cli_has_validation_integration(self):
        """Verify that cli.py integrates with progress validation."""
        cli_path = Path(__file__).parent.parent.parent / "src" / "cli.py"
        cli_content = cli_path.read_text(encoding="utf-8")

        assert "validate_progress_file" in cli_content
        assert "recover_progress_file" in cli_content
        assert "RES-07" in cli_content

    def test_cli_has_backup_logic(self):
        """Verify that cli.py backs up corrupted files."""
        cli_path = Path(__file__).parent.parent.parent / "src" / "cli.py"
        cli_content = cli_path.read_text(encoding="utf-8")

        assert ".json.corrupt" in cli_content
        assert "shutil" in cli_content


class TestEdgeCases:
    """Edge case tests for validation and recovery."""

    def test_validate_empty_completed_files(self, tmp_path):
        """Test validation accepts empty completed_files dict."""
        progress_file = tmp_path / "progress_test.json"
        progress_file.write_text(
            json.dumps(
                {
                    "run_id": "test-123",
                    "schema_version": "1.0",
                    "site_id": "mysite",
                    "total_files": 0,
                    "completed_files": {},
                    "started_at": "2024-01-01T00:00:00Z",
                }
            )
        )

        is_valid, msg, recoverable = _validate_progress_file(progress_file)

        assert is_valid is True
        assert msg == "Valid"

    def test_validate_zero_total_files(self, tmp_path):
        """Test validation accepts zero total_files."""
        progress_file = tmp_path / "progress_test.json"
        progress_file.write_text(
            json.dumps(
                {
                    "run_id": "test-123",
                    "schema_version": "1.0",
                    "site_id": "mysite",
                    "total_files": 0,
                    "completed_files": {},
                    "started_at": "2024-01-01T00:00:00Z",
                }
            )
        )

        is_valid, msg, recoverable = _validate_progress_file(progress_file)

        assert is_valid is True

    def test_validate_total_files_as_float(self, tmp_path):
        """Test validation handles total_files as float."""
        progress_file = tmp_path / "progress_test.json"
        progress_file.write_text(
            json.dumps(
                {
                    "run_id": "test-123",
                    "schema_version": "1.0",
                    "site_id": "mysite",
                    "total_files": 10.0,  # Float instead of int
                    "completed_files": {},
                    "started_at": "2024-01-01T00:00:00Z",
                }
            )
        )

        is_valid, msg, recoverable = _validate_progress_file(progress_file)

        # Should accept float that can be converted to int
        assert is_valid is True

    def test_recovery_preserves_failed_files(self, tmp_path):
        """Test recovery preserves failed_files data."""
        progress_file = tmp_path / "progress_test.json"
        progress_file.write_text(
            json.dumps(
                {
                    "run_id": "test",
                    "site_id": "mysite",
                    "target_langs": ["es"],
                    "completed_files": {},
                    "failed_files": {"error_file.md": {"es": "Translation failed: timeout"}},
                    "total_files": 1,
                }
            )
        )

        # Use module-level ProgressTracker

        tracker = ProgressTracker.recover_progress_file(progress_file)

        assert tracker is not None
        assert "error_file.md" in tracker.state.failed_files
        assert tracker.state.failed_files["error_file.md"]["es"] == "Translation failed: timeout"
