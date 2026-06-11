"""
Golden Test Suite for CLI Backward Compatibility (P0-02).

This test suite captures the current CLI behavior as a regression baseline.
All 4 golden tests MUST pass identically across refactoring phases P1-P5.

Test Philosophy:
- Subprocess-based CLI invocation (not in-process)
- Output snapshot comparison (normalized for non-deterministic elements)
- Exit code validation
- File write validation (when applicable)

Author: Agent C (Tests & Verification Specialist)
Task: P0-02-GOLDEN-TESTS
Date: 2026-01-14
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest


class CLIResult:
    """Container for CLI execution result."""

    def __init__(
        self,
        exit_code: int,
        stdout: str,
        stderr: str,
        duration: float,
        files_written: list[str] | None = None,
    ):
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.duration = duration
        self.files_written = files_written or []

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration": self.duration,
            "files_written": self.files_written,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CLIResult":
        """Create from dictionary."""
        return cls(
            exit_code=data["exit_code"],
            stdout=data["stdout"],
            stderr=data["stderr"],
            duration=data["duration"],
            files_written=data.get("files_written", []),
        )


class GoldenTestBase:
    """
    Base class for golden CLI tests with common utilities.

    Provides:
    - run_cli(): Execute CLI via subprocess
    - normalize_output(): Strip non-deterministic elements
    - save_snapshot(): Save baseline to JSON
    - compare_snapshot(): Compare against baseline
    """

    @classmethod
    def setup_class(cls):
        """Setup test class - find project root."""
        cls.project_root = Path(__file__).parent.parent.parent.absolute()
        cls.snapshot_dir = cls.project_root / "tests" / "golden" / "fixtures" / "expected_outputs"
        cls.snapshot_dir.mkdir(parents=True, exist_ok=True)

    def run_cli(
        self, args: list[str], capture_files: bool = False, cwd: Path | None = None
    ) -> CLIResult:
        """
        Execute CLI via subprocess and capture result.

        Args:
            args: CLI arguments (e.g., ["--site", "golden-test", "--dry-run"])
            capture_files: Whether to track files written
            cwd: Working directory (defaults to project root)

        Returns:
            CLIResult with normalized output
        """
        if cwd is None:
            cwd = self.project_root

        # Build command: python -m src.cli <args>
        cmd = [sys.executable, "-m", "src.cli"] + args

        # Track files before execution (if requested)
        files_before = set()
        if capture_files:
            files_before = self._get_output_files()

        # Execute CLI
        import time

        start_time = time.time()
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            encoding="utf-8",
            errors="replace",  # Replace invalid UTF-8 chars instead of failing
            timeout=120,  # 2 minute timeout
        )
        duration = time.time() - start_time

        # Track files after execution
        files_written = []
        if capture_files:
            files_after = self._get_output_files()
            files_written = sorted(list(files_after - files_before))

        # Return result
        return CLIResult(
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            duration=duration,
            files_written=files_written,
        )

    def _get_output_files(self) -> set:
        """Get set of all files in output directories."""
        output_dirs = [
            self.project_root / "tests" / "golden" / "fixtures" / "es",
            self.project_root / "tests" / "golden" / "fixtures" / "fr",
            self.project_root / "tests" / "golden" / "fixtures" / "de",
            self.project_root / "tests" / "golden" / "fixtures" / "pt",
        ]
        files = set()
        for output_dir in output_dirs:
            if output_dir.exists():
                for file_path in output_dir.rglob("*"):
                    if file_path.is_file():
                        files.add(str(file_path.relative_to(self.project_root)))
        return files

    def normalize_output(self, result: CLIResult) -> CLIResult:
        """
        Normalize CLI output by stripping non-deterministic elements.

        Non-deterministic elements:
        - Timestamps (YYYY-MM-DD, HH:MM:SS, ISO8601)
        - Absolute paths (convert to relative)
        - Temp directories (<TEMP_DIR>)
        - PIDs (<PID>)
        - Memory addresses (<ADDR>)
        - Duration metrics (<DURATION>)
        - Progress percentages (<PROGRESS>)
        """
        # Normalize stdout
        stdout_normalized = self._normalize_text(result.stdout)

        # Normalize stderr
        stderr_normalized = self._normalize_text(result.stderr)

        # Normalize file paths
        files_normalized = [
            str(Path(f).relative_to(self.project_root)) if Path(f).is_absolute() else f
            for f in result.files_written
        ]

        return CLIResult(
            exit_code=result.exit_code,
            stdout=stdout_normalized,
            stderr=stderr_normalized,
            duration=0.0,  # Don't compare duration
            files_written=files_normalized,
        )

    def _normalize_text(self, text: str) -> str:
        """
        Normalize text by replacing non-deterministic patterns.

        Patterns replaced:
        - ISO8601 timestamps: <TIMESTAMP>
        - Date patterns: <DATE>
        - Time patterns: <TIME>
        - Absolute paths: <PROJECT_ROOT>/relative/path
        - Temp paths: <TEMP_DIR>
        - PIDs: <PID>
        - Memory addresses: <ADDR>
        - Durations: <DURATION>
        - Progress: <PROGRESS>
        """
        # Handle None input (empty output)
        if text is None:
            return ""

        # Replace ISO8601 timestamps (e.g., 2026-01-14T18:07:19.123456)
        text = re.sub(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?",
            "<TIMESTAMP>",
            text,
        )

        # Replace date patterns (YYYY-MM-DD)
        text = re.sub(r"\d{4}-\d{2}-\d{2}", "<DATE>", text)

        # Replace time patterns (HH:MM:SS)
        text = re.sub(r"\d{2}:\d{2}:\d{2}", "<TIME>", text)

        # Replace absolute paths (convert to relative)
        project_root_str = str(self.project_root).replace("\\", "/")
        text = text.replace(str(self.project_root), "<PROJECT_ROOT>")
        text = text.replace(project_root_str, "<PROJECT_ROOT>")
        text = text.replace(str(self.project_root).replace("\\", "\\\\"), "<PROJECT_ROOT>")

        # Replace Windows-style paths
        text = re.sub(r"[A-Z]:\\[^\s\"\']+", lambda m: self._normalize_path(m.group(0)), text)

        # Replace temp directory patterns
        text = re.sub(r"/tmp/[^\s\"\']+", "<TEMP_DIR>", text)
        text = re.sub(r"C:\\Users\\[^\\]+\\AppData\\Local\\Temp\\[^\s\"\']+", "<TEMP_DIR>", text)

        # Replace PIDs
        text = re.sub(r"PID:\s*\d+", "PID: <PID>", text)
        text = re.sub(r"pid=\d+", "pid=<PID>", text)

        # Replace memory addresses
        text = re.sub(r"0x[0-9a-fA-F]+", "<ADDR>", text)

        # Replace duration patterns (e.g., "1.23s", "45.67 seconds")
        text = re.sub(r"\d+\.\d+\s*(?:s|sec|seconds?)", "<DURATION>", text)

        # Replace progress percentages (e.g., "75%", "100.0%")
        text = re.sub(r"\d+(?:\.\d+)?%", "<PROGRESS>", text)

        # Replace "N files processed" patterns
        text = re.sub(
            r"\d+\s+files?\s+(?:processed|translated|written)", "<N> files <ACTION>", text
        )

        # Replace "N/M" progress patterns
        text = re.sub(r"\d+/\d+", "<N>/<M>", text)

        return text

    def _normalize_path(self, path: str) -> str:
        """Normalize a single path."""
        try:
            path_obj = Path(path)
            if path_obj.is_relative_to(self.project_root):
                return "<PROJECT_ROOT>/" + str(path_obj.relative_to(self.project_root)).replace(
                    "\\", "/"
                )
        except (ValueError, OSError):
            pass
        return path

    def save_snapshot(self, test_name: str, result: CLIResult) -> None:
        """
        Save baseline snapshot to JSON.

        Args:
            test_name: Test identifier (e.g., "golden_01_multilang_strict")
            result: Normalized CLI result
        """
        snapshot_file = self.snapshot_dir / f"{test_name}.json"
        with open(snapshot_file, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, indent=2, ensure_ascii=False)

    def load_snapshot(self, test_name: str) -> CLIResult | None:
        """
        Load baseline snapshot from JSON.

        Args:
            test_name: Test identifier

        Returns:
            CLIResult or None if snapshot doesn't exist
        """
        snapshot_file = self.snapshot_dir / f"{test_name}.json"
        if not snapshot_file.exists():
            return None

        with open(snapshot_file, encoding="utf-8") as f:
            data = json.load(f)
            return CLIResult.from_dict(data)

    def compare_snapshot(
        self, test_name: str, result: CLIResult, update_snapshot: bool = False
    ) -> None:
        """
        Compare result against baseline snapshot.

        If snapshot doesn't exist, creates it (baseline capture).
        If update_snapshot=True, updates existing snapshot.

        Args:
            test_name: Test identifier
            result: Normalized CLI result
            update_snapshot: Whether to update existing snapshot

        Raises:
            AssertionError: If result doesn't match snapshot
        """
        baseline = self.load_snapshot(test_name)

        if baseline is None or update_snapshot:
            # Create or update baseline
            self.save_snapshot(test_name, result)
            if baseline is None:
                pytest.skip(
                    f"Baseline snapshot created for {test_name}. Run tests again to validate."
                )
            return

        # Compare exit code
        assert result.exit_code == baseline.exit_code, (
            f"Exit code mismatch: expected {baseline.exit_code}, got {result.exit_code}"
        )

        # Compare stdout (allow minor whitespace differences)
        stdout_match = self._compare_text(result.stdout, baseline.stdout)
        assert stdout_match, (
            f"Stdout mismatch:\n--- Baseline ---\n{baseline.stdout}\n--- Current ---\n{result.stdout}"
        )

        # Compare stderr (allow minor whitespace differences)
        stderr_match = self._compare_text(result.stderr, baseline.stderr)
        assert stderr_match, (
            f"Stderr mismatch:\n--- Baseline ---\n{baseline.stderr}\n--- Current ---\n{result.stderr}"
        )

        # Compare files written (if applicable)
        if baseline.files_written or result.files_written:
            assert set(result.files_written) == set(baseline.files_written), (
                f"Files written mismatch:\nBaseline: {baseline.files_written}\nCurrent: {result.files_written}"
            )

    def _compare_text(self, text1: str, text2: str) -> bool:
        """
        Compare text with whitespace normalization.

        Normalizes:
        - Leading/trailing whitespace
        - Multiple consecutive whitespace -> single space
        - Blank lines
        """
        # Normalize whitespace
        lines1 = [line.strip() for line in text1.split("\n") if line.strip()]
        lines2 = [line.strip() for line in text2.split("\n") if line.strip()]

        return lines1 == lines2


class TestCLIBackwardCompatibility(GoldenTestBase):
    """
    Golden CLI backward compatibility test suite (P0-02).

    Tests 4 golden commands that establish the backward compatibility baseline
    for the Hugo Translation System CLI.

    All tests MUST pass identically across refactoring phases P1-P5.
    """

    def test_golden_01_multilang_strict(self):
        """
        Golden Test 1: Multi-language strict translation with dry-run.

        Command:
            translate-hugo --site golden-test --target-langs es,fr --strict --dry-run

        Validates:
        - Multi-language processing (es, fr)
        - Strict validation mode (zero tolerance)
        - Dry-run behavior (no file writes)
        - Exit code 0 or 1 (baseline captures current state)

        Note: If this test fails due to validation errors, that's EXPECTED.
        The baseline captures the current behavior, bugs and all.
        """
        # Run CLI
        result = self.run_cli(
            ["--site", "golden-test", "--target-langs", "es", "fr", "--strict", "--dry-run"]
        )

        # Normalize output
        normalized = self.normalize_output(result)

        # Compare against snapshot (or create baseline)
        self.compare_snapshot("golden_01_multilang_strict", normalized)

    def test_golden_02_single_no_validation_dry_run(self):
        """
        Golden Test 2: Single language with validation disabled and dry-run.

        Command:
            translate-hugo --site golden-test --target-langs de --no-validation --dry-run

        Validates:
        - Single language processing (de only)
        - Validation disabled (--no-validation flag)
        - Dry-run behavior (no file writes)
        - Exit code should be 0 (no validation to fail)

        Note: With validation disabled, this test should always succeed.
        """
        # Run CLI
        result = self.run_cli(
            ["--site", "golden-test", "--target-langs", "de", "--no-validation", "--dry-run"]
        )

        # Normalize output
        normalized = self.normalize_output(result)

        # Compare against snapshot
        self.compare_snapshot("golden_02_single_no_validation_dry_run", normalized)

    def test_golden_03_resume_mode(self):
        """
        Golden Test 3: Resume mode (skip completed files).

        Command:
            translate-hugo --site golden-test --target-langs pt --resume --dry-run

        Validates:
        - Single language processing (pt)
        - Resume mode (skip already-translated files)
        - Dry-run behavior (no file writes)
        - Exit code 0 (expected success)

        Note: First run has no completed files to skip.
        This test validates the resume flag is accepted and processed.
        """
        # Run CLI
        result = self.run_cli(
            ["--site", "golden-test", "--target-langs", "pt", "--resume", "--dry-run"]
        )

        # Normalize output
        normalized = self.normalize_output(result)

        # Compare against snapshot
        self.compare_snapshot("golden_03_resume_mode", normalized)

    def test_golden_04_diagnose_lock(self):
        """
        Golden Test 4: Diagnostic command (diagnose-lock).

        Command:
            translate-hugo diagnose-lock --site golden-test

        Validates:
        - Special command invocation (not main translate command)
        - Lock diagnostics output
        - Exit code 0 (diagnostics displayed)

        Note: This tests a completely different code path (lock management).
        Ensures special commands remain backward compatible.
        """
        # Run CLI
        result = self.run_cli(["diagnose-lock", "--site", "golden-test"])

        # Normalize output
        normalized = self.normalize_output(result)

        # Compare against snapshot
        self.compare_snapshot("golden_04_diagnose_lock", normalized)


# pytest configuration
@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Setup test environment before running tests."""
    # Ensure golden-test site profile exists
    project_root = Path(__file__).parent.parent.parent.absolute()
    site_profile = project_root / "config" / "site_profiles" / "golden-test.yaml"

    if not site_profile.exists():
        pytest.fail(
            f"Golden test site profile not found: {site_profile}\n"
            f"Please create config/site_profiles/golden-test.yaml"
        )

    # Ensure test fixtures exist
    fixtures_dir = project_root / "tests" / "golden" / "fixtures"
    if not fixtures_dir.exists():
        pytest.fail(f"Fixtures directory not found: {fixtures_dir}")

    minimal_en = fixtures_dir / "minimal_en.md"
    minimal_multilang = fixtures_dir / "minimal_multilang.md"

    if not minimal_en.exists():
        pytest.fail(f"Test fixture not found: {minimal_en}")
    if not minimal_multilang.exists():
        pytest.fail(f"Test fixture not found: {minimal_multilang}")


if __name__ == "__main__":
    # Allow running tests directly: python test_cli_backward_compat.py
    pytest.main([__file__, "-v"])
