"""
TC-REEXEC-09 / RISK-09: YAML formatter logging safety tests.

Proves that YAMLFormatter.format_frontmatter() is safe regardless of
logging transport failures. structlog calls in yaml_formatter.py must
never abort YAML formatting or alter output content.
"""
from __future__ import annotations

import io
import logging
from unittest.mock import patch, MagicMock

import pytest
import structlog

from src.translation_engine.reconstructor.yaml_formatter import YAMLFormatter


class _BrokenStream:
    """Simulates a Windows restricted pipe that raises OSError on write."""

    def write(self, msg):
        raise OSError(22, "Invalid argument")

    def flush(self):
        raise OSError(22, "Invalid argument")

# Try to import CommentedMap; skip if ruamel unavailable
try:
    from ruamel.yaml.comments import CommentedMap
except ImportError:
    CommentedMap = None


class TestYAMLFormatterLoggingSafety:
    """YAML formatter must produce correct output even when logging fails."""

    def test_unicode_heavy_frontmatter_succeeds(self):
        """Unicode-heavy frontmatter formats without error."""
        data = {
            "title": "Hu\u1edbng d\u1eabn t\u1ea1o t\u1ec7p ZIP",  # Vietnamese
            "description": "\u062a\u0648\u0636\u06cc\u062d\u0627\u062a",  # Arabic
            "keywords": "\u65e5\u672c\u8a9e\u30c6\u30b9\u30c8",  # Japanese
            "draft": False,
        }
        result = YAMLFormatter.format_frontmatter(data)
        assert result.startswith("---\n")
        assert result.endswith("---\n")
        assert "ZIP" in result

    def test_output_content_unchanged_when_stdout_fails(self):
        """format_frontmatter returns correct YAML even when logger.debug raises."""
        data = {"title": "Caf\u00e9 r\u00e9sum\u00e9", "draft": False}

        with patch(
            "src.translation_engine.reconstructor.yaml_formatter.logger"
        ) as mock_logger:
            mock_logger.debug.side_effect = OSError(22, "Invalid argument")
            result = YAMLFormatter.format_frontmatter(data)

        assert "---\n" in result
        assert "Caf\u00e9" in result
        assert "draft" in result

    def test_known_oserror_shape_does_not_propagate(self):
        """The exact RISK-09 failure shape (OSError errno 22) does not escape."""
        data = {"title": "Test", "date": "2026-04-23"}

        with patch(
            "src.translation_engine.reconstructor.yaml_formatter.logger"
        ) as mock_logger:
            mock_logger.debug.side_effect = OSError(22, "Invalid argument")
            # Must not raise
            result = YAMLFormatter.format_frontmatter(data)

        assert result.startswith("---\n")
        assert "Test" in result

    def test_ruamel_fallback_warning_does_not_abort(self):
        """When ruamel fails AND console stream is broken, PyYAML fallback still works.

        With RISK-09 fix, structlog routes through stdlib. StreamHandler.emit()
        catches the broken-stream OSError internally. The logger.warning() call
        in the except block does NOT propagate the pipe error.
        """
        # Configure structlog with stdlib routing (as the worker does)
        structlog.configure(
            processors=[
                structlog.stdlib.filter_by_level,
                structlog.stdlib.add_logger_name,
                structlog.stdlib.add_log_level,
                structlog.stdlib.PositionalArgumentsFormatter(),
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.processors.UnicodeDecoder(),
                structlog.dev.ConsoleRenderer(),
            ],
            wrapper_class=structlog.stdlib.BoundLogger,
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=False,
        )

        # Set up a broken stream handler on the logger that yaml_formatter uses
        fm_logger_name = "src.translation_engine.reconstructor.yaml_formatter"
        stdlib_logger = logging.getLogger(fm_logger_name)
        stdlib_logger.handlers.clear()
        stdlib_logger.setLevel(logging.DEBUG)
        stdlib_logger.propagate = False
        stdlib_logger.addHandler(logging.StreamHandler(_BrokenStream()))

        try:
            data = {"title": "Fallback test"}

            with patch(
                "src.translation_engine.reconstructor.yaml_formatter._yaml_dumper"
            ) as mock_dumper:
                mock_dumper.dump.side_effect = RuntimeError("ruamel failure")
                result = YAMLFormatter.format_frontmatter(data)

            assert result.startswith("---\n")
            assert "Fallback test" in result
        finally:
            stdlib_logger.handlers.clear()
            structlog.reset_defaults()

    @pytest.mark.skipif(CommentedMap is None, reason="ruamel.yaml not installed")
    def test_debug_call_arguments_do_not_affect_output(self):
        """The preserved_comments=True debug arg is read-only, not mutating data."""
        cm = CommentedMap()
        cm["title"] = "Hello"
        cm["draft"] = False

        plain = {"title": "Hello", "draft": False}

        result_cm = YAMLFormatter.format_frontmatter(cm)
        result_plain = YAMLFormatter.format_frontmatter(plain)

        # Both should produce valid YAML with the same key-value content
        assert "Hello" in result_cm
        assert "Hello" in result_plain
        assert result_cm.startswith("---\n")
        assert result_plain.startswith("---\n")

    def test_invalid_unicode_in_frontmatter_does_not_raise_oserror(self):
        """Surrogate or invalid unicode may fail yaml but must NOT raise OSError 22."""
        data = {"title": "test\ud800value"}
        try:
            result = YAMLFormatter.format_frontmatter(data)
            # If it succeeds, output should be valid
            assert "---" in result
        except OSError as e:
            # Must NOT be the structlog pipe error
            assert e.errno != 22, "OSError errno 22 must not escape from logging"
        except Exception:
            # Other exceptions (yaml encoding) are acceptable
            pass

    def test_warning_log_on_ruamel_failure_is_safe(self):
        """When ruamel fails, logger.warning is called and PyYAML fallback works."""
        data = {"title": "Safe fallback"}

        with patch(
            "src.translation_engine.reconstructor.yaml_formatter._yaml_dumper"
        ) as mock_dumper, patch(
            "src.translation_engine.reconstructor.yaml_formatter.logger"
        ) as mock_logger:
            mock_dumper.dump.side_effect = RuntimeError("ruamel error")
            mock_logger.warning = MagicMock()

            result = YAMLFormatter.format_frontmatter(data)

        mock_logger.warning.assert_called_once()
        call_kwargs = mock_logger.warning.call_args
        assert "yaml_ruamel_fallback" in str(call_kwargs)
        assert result.startswith("---\n")
        assert "Safe fallback" in result


class TestRC5YAMLValidation:
    """RC-5 regression tests: _validate_yaml_output raises ValueError for known-bad YAML.

    These tests guard against regressions in the RC-5 pre-write YAML validation
    (yaml_formatter.py:84-97). Each pattern corresponds to a confirmed failure class
    found in the 465 YAML-broken translated files created before the RC-5 fix (2026-05-04).
    """

    def test_unquoted_colon_in_value_raises(self):
        """Unquoted colon in a YAML value (RC-1 failure pattern) raises ValueError.

        Example: title: Cells: Advanced Spreadsheet Library
        YAML treats the second ': ' as a nested key, producing a scan error.
        """
        bad_yaml = "title: Cells: Advanced Spreadsheet Library\ndescription: test\n"
        with pytest.raises(ValueError, match="YAML"):
            YAMLFormatter._validate_yaml_output(bad_yaml)

    def test_bad_block_scalar_indentation_raises(self):
        """Block scalar content with mixed indentation raises ValueError.

        Example of real failure pattern from pre-RC-5 files:
            description: |
              two-space content
             bad_key: value   ← 1-space: terminates block scalar at wrong indent level
        The key at 1-space indentation is less than block content (2-space) but
        more than root mapping (0-space), causing a YAML structural error.
        """
        bad_yaml = "description: |\n  content line\n bad_key: value\n"
        with pytest.raises(ValueError, match="YAML"):
            YAMLFormatter._validate_yaml_output(bad_yaml)

    def test_collapsed_frontmatter_raises(self):
        """Collapsed frontmatter (all keys on one line) raises ValueError.

        Occurs when frontmatter serializer collapses multiple key-value pairs onto
        one line without newlines, making them unparseable as a block mapping.
        """
        bad_yaml = "title: Hello description: World date: 2024-01-01\n"
        with pytest.raises(ValueError, match="YAML"):
            YAMLFormatter._validate_yaml_output(bad_yaml)

    def test_format_frontmatter_raises_when_serializer_produces_invalid_yaml(self):
        """format_frontmatter() raises ValueError end-to-end when YAML is invalid.

        Patches the internal serializer to write known-bad YAML to the stream,
        confirming that _validate_yaml_output is called in the format_frontmatter
        code path and that the ValueError propagates to the caller.

        Note: _yaml_dumper.dump(data, stream) writes to the stream object; the code
        reads yaml_content from stream.getvalue(), not from dump's return value.
        Therefore the mock must use side_effect to write to the stream argument.
        """
        bad_yaml = "title: Cells: Advanced Spreadsheet Library\ndescription: test\n"

        def write_bad_yaml_to_stream(data, stream):
            stream.write(bad_yaml)

        with patch(
            "src.translation_engine.reconstructor.yaml_formatter._yaml_dumper"
        ) as mock_dumper:
            mock_dumper.dump.side_effect = write_bad_yaml_to_stream
            with pytest.raises(ValueError, match="YAML"):
                YAMLFormatter.format_frontmatter({"title": "anything"})
