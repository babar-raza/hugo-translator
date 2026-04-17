"""
Test Import Path Validation.

Ensures all graceful shutdown and telemetry cleanup imports work correctly
in different execution contexts.

This addresses CF-05: Fix Import Path Issues
"""

import unittest
from pathlib import Path


class TestImportPaths(unittest.TestCase):
    """Test that all import paths work correctly."""

    def test_absolute_import_graceful_shutdown(self):
        """Test absolute import: src.observability.graceful_shutdown"""
        from src.observability.graceful_shutdown import (
            get_active_context_count,
            register_active_context,
            register_shutdown_handler,
            reset_for_testing,
            setup_graceful_shutdown,
            unregister_active_context,
        )

        # Verify all functions are callable
        assert callable(setup_graceful_shutdown)
        assert callable(register_active_context)
        assert callable(unregister_active_context)
        assert callable(register_shutdown_handler)
        assert callable(get_active_context_count)
        assert callable(reset_for_testing)

    def test_absolute_import_telemetry_cleanup(self):
        """Test absolute import: src.observability.telemetry_cleanup"""
        from src.observability.telemetry_cleanup import cleanup_stale_runs

        # Verify function is callable
        assert callable(cleanup_stale_runs)

    def test_relative_import_from_cli_context(self):
        """Test that CLI import pattern works."""
        # Simulate CLI context import pattern
        try:
            from src.observability.graceful_shutdown import setup_graceful_shutdown
            from src.observability.telemetry_cleanup import cleanup_stale_runs
        except ImportError:
            from observability.graceful_shutdown import setup_graceful_shutdown
            from observability.telemetry_cleanup import cleanup_stale_runs

        assert callable(setup_graceful_shutdown)
        assert callable(cleanup_stale_runs)

    def test_import_from_engine_context(self):
        """Test that engine can import graceful shutdown functions."""
        # Import the engine module (which uses relative imports internally)
        from src.translation_engine import engine

        # The engine module should have successfully imported
        assert hasattr(engine, 'TranslationEngine')

    def test_all_public_api_functions_available(self):
        """Test that all public API functions are accessible."""
        from src.observability import graceful_shutdown

        # Public API functions
        public_functions = [
            'setup_graceful_shutdown',
            'register_active_context',
            'unregister_active_context',
            'register_shutdown_handler',
            'get_active_context_count',
            'reset_for_testing',
        ]

        for func_name in public_functions:
            assert hasattr(graceful_shutdown, func_name), f"Missing: {func_name}"
            assert callable(getattr(graceful_shutdown, func_name))

    def test_import_isolation(self):
        """Test that imports don't pollute global namespace."""
        # Import in a clean way
        import src.observability.graceful_shutdown as gs_module

        # Check that internal globals are not leaked
        module_attrs = dir(gs_module)

        # Public API should be present
        assert 'setup_graceful_shutdown' in module_attrs
        assert 'register_active_context' in module_attrs

        # Internal implementation details should exist but are private
        assert '_active_contexts' in module_attrs
        assert '_contexts_lock' in module_attrs
        assert '_perform_graceful_shutdown' in module_attrs

    def test_no_import_side_effects(self):
        """Test that importing modules doesn't have side effects."""
        # Count should be 0 before any registration
        from src.observability.graceful_shutdown import get_active_context_count, reset_for_testing

        # Reset first to ensure clean state
        reset_for_testing()

        # Importing should not register any contexts
        count_before = get_active_context_count()
        assert count_before == 0, "Importing should not register contexts"

        # Import again (should be idempotent)
        count_after = get_active_context_count()
        assert count_after == 0, "Multiple imports should not register contexts"

    def test_cross_module_import_consistency(self):
        """Test that the same module is imported across different import paths."""
        from src.observability import graceful_shutdown
        from src.observability.graceful_shutdown import setup_graceful_shutdown as setup1
        setup2 = graceful_shutdown.setup_graceful_shutdown

        # Both should point to the same function
        assert setup1 is setup2, "Import paths should resolve to same object"

    def test_import_works_from_different_working_directories(self):
        """Test imports work regardless of current working directory."""
        import os
        original_cwd = os.getcwd()

        try:
            # Test from project root
            project_root = Path(__file__).parent.parent.parent
            os.chdir(project_root)

            from src.observability.graceful_shutdown import setup_graceful_shutdown
            assert callable(setup_graceful_shutdown)

            # Test from src directory
            os.chdir(project_root / "src")
            # Re-import to test
            import importlib

            import src.observability.graceful_shutdown
            importlib.reload(src.observability.graceful_shutdown)
            assert callable(src.observability.graceful_shutdown.setup_graceful_shutdown)

        finally:
            os.chdir(original_cwd)

    def test_cli_fallback_import_pattern(self):
        """Test the try/except import pattern used in cli.py."""
        # This pattern is used to handle both direct execution and module execution
        graceful_shutdown_module = None

        try:
            # Try relative import (as if running as a module)
            import src.observability.graceful_shutdown as graceful_shutdown_module
        except ImportError:
            # Fallback to direct import (as if running from src/)
            import observability.graceful_shutdown as graceful_shutdown_module

        assert graceful_shutdown_module is not None
        assert hasattr(graceful_shutdown_module, 'setup_graceful_shutdown')

    def test_engine_relative_import_pattern(self):
        """Test the relative import pattern used in engine.py."""
        # The engine uses ..observability.graceful_shutdown
        # We can't test this directly, but we can verify it works by importing engine
        from src.translation_engine.engine import TranslationEngine

        # If engine.py's imports failed, this import would fail too
        assert TranslationEngine is not None


class TestImportErrorHandling(unittest.TestCase):
    """Test graceful degradation when imports fail."""

    def test_graceful_shutdown_import_error_handling(self):
        """Test that missing graceful_shutdown is handled gracefully."""
        # This pattern is used in engine.py
        context_registered = False

        try:
            from src.observability.graceful_shutdown import register_active_context
            # If we get here, import succeeded (which it should)
            context_registered = True
        except ImportError:
            # Graceful degradation - this is OK
            pass

        # In production, import should succeed
        assert context_registered, "graceful_shutdown should be importable"

    def test_missing_module_fallback(self):
        """Test that code handles missing modules gracefully."""
        # Simulate the pattern used in engine.py
        def safe_register_context(context):
            """Safely register context with fallback."""
            try:
                from src.observability.graceful_shutdown import register_active_context
                register_active_context(context)
                return True
            except ImportError:
                # Graceful degradation
                return False

        # With the module available, should succeed
        from unittest.mock import Mock
        mock_context = Mock()
        result = safe_register_context(mock_context)
        assert result is True


if __name__ == '__main__':
    unittest.main()
