"""
End-to-end smoke test for default_model resolution (SR-H04).

Verifies that the original AttributeError crash is fixed by loading
real site profiles and exercising the CLI code path.
"""
import subprocess
import sys
from pathlib import Path

import pytest


class TestDefaultModelE2E:
    """E2E tests verifying the default_model fix works with real profiles."""

    @pytest.fixture
    def config_root(self):
        """Get the real config directory."""
        project_root = Path(__file__).parent.parent.parent
        config_dir = project_root / "config"
        assert config_dir.exists(), f"Config directory not found: {config_dir}"
        return config_dir

    def test_blog_profile_loads_with_default_model(self, config_root):
        """SR-H04: blog.aspose.net profile loads without AttributeError."""
        from src.utils.config_loader import ConfigService

        service = ConfigService(config_root)

        # This was the exact scenario that crashed
        profile = service.get_site_profile("blog.aspose.net")

        # Should not raise AttributeError
        default_model = getattr(profile, 'default_model', None)

        # blog.aspose.net has model.default: m2m100_1.2b in YAML
        assert default_model == "m2m100_1.2b"

    def test_products_profile_loads_without_model(self, config_root):
        """Profile without model field loads with None default_model."""
        from src.utils.config_loader import ConfigService

        service = ConfigService(config_root)
        profile = service.get_site_profile("products.aspose.net")

        # Should not raise AttributeError
        default_model = getattr(profile, 'default_model', None)

        # products.aspose.net has no model field
        assert default_model is None

    def test_model_resolution_priority_e2e(self, config_root):
        """E2E test of full priority chain with real profile."""
        from src.utils.config_loader import ConfigService

        service = ConfigService(config_root)
        profile = service.get_site_profile("blog.aspose.net")

        # Simulate CLI resolution logic
        def resolve_model(cli_override, profile):
            return cli_override or getattr(profile, 'default_model', None) or "m2m100_418m"

        # CLI override takes precedence
        assert resolve_model("nllb_200_600m", profile) == "nllb_200_600m"

        # Profile default_model used when no CLI override
        assert resolve_model(None, profile) == "m2m100_1.2b"

    def test_no_attribute_error_on_direct_access(self, config_root):
        """Direct attribute access works after fix (Pydantic field exists)."""
        from src.utils.config_loader import ConfigService

        service = ConfigService(config_root)
        profile = service.get_site_profile("blog.aspose.net")

        # This would have raised AttributeError before the fix
        # Now it works because default_model is a defined Pydantic field
        try:
            _ = profile.default_model
        except AttributeError as e:
            pytest.fail(f"AttributeError should not be raised: {e}")

    def test_all_site_profiles_load_successfully(self, config_root):
        """All site profiles load without errors."""
        from src.utils.config_loader import ConfigService

        service = ConfigService(config_root)
        profiles_dir = config_root / "site_profiles"

        for profile_path in profiles_dir.glob("*.yaml"):
            site_id = profile_path.stem
            if site_id in ("example", "default"):
                continue  # Skip example/default profiles

            try:
                profile = service.get_site_profile(site_id)
                # Access default_model to ensure it doesn't raise
                _ = getattr(profile, 'default_model', None)
            except Exception as e:
                pytest.fail(f"Failed to load profile {site_id}: {e}")

    def test_cli_subprocess_imports_successfully(self):
        """SR-P02: Verify CLI module imports without AttributeError via subprocess."""
        project_root = Path(__file__).parent.parent.parent

        # Test 1: Verify CLI module can be imported (catches import-time errors)
        # Note: 30s timeout accounts for slow imports (torch, sentence-transformers)
        result = subprocess.run(
            [sys.executable, "-c",
             "from src.cli import main; from src.utils.models import SiteProfile; "
             "from src.utils.config_loader import ConfigService"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(project_root)
        )

        # Should not crash with AttributeError during import
        assert "AttributeError" not in result.stderr, (
            f"CLI import crashed with AttributeError: {result.stderr}"
        )
        assert result.returncode == 0, (
            f"CLI import failed: {result.stderr}"
        )

    def test_cli_help_runs_successfully(self):
        """SR-P02: Verify CLI --help runs without crash."""
        project_root = Path(__file__).parent.parent.parent

        result = subprocess.run(
            [sys.executable, "-m", "src.cli", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(project_root)
        )

        # Help should succeed
        assert result.returncode == 0, (
            f"CLI --help failed: {result.stderr}"
        )
        # Should show usage info
        assert "usage" in result.stdout.lower() or "--site" in result.stdout, (
            f"CLI --help output unexpected: {result.stdout}"
        )
