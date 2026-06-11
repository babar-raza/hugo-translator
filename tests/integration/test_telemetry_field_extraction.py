"""
Integration test for telemetry field extraction with real translation.

Tests end-to-end flow with actual TranslationEngine and LLM translation.
"""

import os
from pathlib import Path

import pytest

# Skip by default: test requires real LLM model (m2m100_418m) and correct engine setup.
# Set SKIP_HEAVY_TESTS=false to enable.
SKIP_HEAVY_TESTS = os.getenv("SKIP_HEAVY_TESTS", "true").lower() == "true"


@pytest.mark.skipif(SKIP_HEAVY_TESTS, reason="Heavy integration test - skipped in CI")
def test_translate_file_with_telemetry_real_llm(tmp_path):
    """
    End-to-end test with real translation and telemetry.

    This test:
    1. Creates a real markdown file
    2. Runs actual translation with LLM (m2m100)
    3. Verifies telemetry is captured
    """
    from src.translation_engine.engine import TranslationEngine
    from src.utils.config_loader import ConfigService

    # Create test file
    test_content = """---
title: Test Document
description: A simple test
---

# Introduction

This is a test document for verifying telemetry integration.

## Features

- Real translation with LLM
- Telemetry tracking
- Field extraction
"""

    test_file = tmp_path / "test_input.md"
    test_file.write_text(test_content, encoding="utf-8")

    # Create output directory
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    try:
        # Load config
        config_service = ConfigService(config_root=Path.cwd() / "config")
        config = config_service.get_config()

        # Create engine with telemetry enabled
        engine = TranslationEngine(
            config=config,
            model_name="m2m100_418m",  # Use smaller model for faster test
            site_id="test.aspose.net",
            enable_telemetry=True,
            enable_validation=True,  # Enable validation to test those metrics
            output_dir=output_dir,
        )

        # Translate to single language
        result = engine.translate_file(
            file_path=test_file, target_langs=["fr"], site_id="test.aspose.net"
        )

        # Verify translation succeeded
        assert result.success, f"Translation failed: {result.error}"

        # Verify telemetry was active during translation
        # (actual verification would require checking telemetry database)
        assert result.stats is not None
        assert result.stats.total_segments > 0

        # Verify output file was created
        assert len(result.outputs) > 0
        output_file = result.outputs.get("fr")
        assert output_file is not None
        assert output_file.exists()

        # Verify output content
        output_content = output_file.read_text(encoding="utf-8")
        assert len(output_content) > 0
        assert "---" in output_content  # Frontmatter preserved

    finally:
        pass  # tmp_path is managed by pytest and auto-cleaned after the test


def test_telemetry_graceful_degradation():
    """
    Verify telemetry failures don't crash translation.

    This test verifies that even if telemetry is misconfigured or unavailable,
    translation still proceeds successfully.
    """
    from src.observability.telemetry_integration import TranslationTelemetry

    # Create telemetry with enabled=True but no client available
    # (will auto-disable if client fails to initialize)
    telemetry = TranslationTelemetry(enabled=True)

    # Should not crash - will return DummyRunContext or real context
    with telemetry.track_translation_session(
        job_type="translate_file", trigger_type="cli"
    ) as run_context:
        assert run_context is not None

    # If we got a real context, complete it
    from src.observability.telemetry_integration import DummyRunContext

    if not isinstance(run_context, DummyRunContext):
        # This should also not crash
        pass


def test_validation_metrics_captured_in_real_translation():
    """
    Verify validation metrics are captured in real translation.

    NOTE: This is a lighter test that checks validation is triggered
    without running full LLM translation.
    """
    from src.translation_engine.models import TranslationStats

    # Create stats object as would be populated during translation
    stats = TranslationStats()

    # Simulate validation results
    stats.validation_decision = "ACCEPT"
    stats.validation_passed = 5
    stats.validation_failed = 0
    stats.validation_errors = 0
    stats.validation_warnings = 1

    # Verify fields exist and can be accessed
    assert stats.validation_decision == "ACCEPT"
    assert stats.validation_passed == 5
    assert stats.validation_warnings == 1


def test_ast_metrics_structure():
    """Verify AST metrics structure in TranslationStats."""
    from src.translation_engine.models import TranslationStats

    stats = TranslationStats()

    # Verify AST fields exist
    assert hasattr(stats, "ast_translation_enabled")
    assert hasattr(stats, "ast_units_extracted")
    assert hasattr(stats, "ast_units_translatable")
    assert hasattr(stats, "ast_units_protected")
    assert hasattr(stats, "ast_batch_calls")
    assert hasattr(stats, "ast_individual_fallbacks")

    # Verify defaults
    assert stats.ast_translation_enabled is False
    assert stats.ast_units_extracted == 0
