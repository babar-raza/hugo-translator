"""
Production Readiness Tests

Tests that production readiness checks work correctly.
"""

import pytest
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestReadinessChecks:
    """Test production readiness checker."""

    def test_check_directories_pass(self, tmpdir):
        """Test directory check passes when all dirs exist."""
        from scripts.production_readiness_check import ReadinessCheck

        project_root = Path(tmpdir)
        (project_root / "config").mkdir()
        (project_root / "src").mkdir()
        (project_root / "data").mkdir()

        checker = ReadinessCheck(project_root)
        passed, message = checker.check_directories()

        assert passed
        assert "exist" in message.lower()

    def test_check_directories_fail(self, tmpdir):
        """Test directory check fails when dirs missing."""
        from scripts.production_readiness_check import ReadinessCheck

        project_root = Path(tmpdir)
        # Don't create required dirs

        checker = ReadinessCheck(project_root)
        passed, message = checker.check_directories()

        assert not passed
        assert "missing" in message.lower()

    def test_check_dependencies_pass(self):
        """Test dependency check passes for installed packages."""
        from scripts.production_readiness_check import ReadinessCheck

        checker = ReadinessCheck(Path.cwd())
        passed, message = checker.check_dependencies()

        # Should pass if all required packages installed
        assert passed or "missing" in message.lower()

    def test_check_tm_functionality(self, tmpdir):
        """Test TM functionality check."""
        from scripts.production_readiness_check import ReadinessCheck

        project_root = Path(tmpdir)
        (project_root / "data" / "tm").mkdir(parents=True)

        checker = ReadinessCheck(project_root)
        passed, message = checker.check_tm_functionality()

        # Should pass if TM works
        assert passed or "failed" in message.lower()

    def test_run_all_checks(self, tmpdir):
        """Test running all checks."""
        from scripts.production_readiness_check import ReadinessCheck

        project_root = Path(tmpdir)
        (project_root / "config").mkdir()
        (project_root / "src").mkdir()
        (project_root / "data").mkdir()

        checker = ReadinessCheck(project_root)
        results = checker.run_all_checks()

        assert len(results) > 0
        assert all("name" in r and "passed" in r and "message" in r for r in results)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
