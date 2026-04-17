"""
Unit tests for force_retranslate parameter in TranslationEngine (T202: federated-splashing-panda).

Tests that --force-retranslate flag bypasses cache lookup and forces fresh translation.
"""
from pathlib import Path
from unittest.mock import Mock, patch

from src.tm.translation_memory import TMResult
from src.translation_engine.engine import TranslationEngine


class TestForceRetranslate:
    """Test force_retranslate parameter in TranslationEngine."""

    def test_force_retranslate_parameter_stored(self):
        """Test force_retranslate parameter is stored in engine instance."""
        with patch('src.translation_engine.engine.ModelLoader'):
            with patch('src.translation_engine.engine.TranslationMemory'):
                engine = TranslationEngine(
                    config_dir=Path("config"),
                    force_retranslate=True,
                )

                assert engine.force_retranslate is True

    def test_force_retranslate_default_false(self):
        """Test force_retranslate defaults to False."""
        with patch('src.translation_engine.engine.ModelLoader'):
            with patch('src.translation_engine.engine.TranslationMemory'):
                engine = TranslationEngine(
                    config_dir=Path("config"),
                )

                assert engine.force_retranslate is False

    def test_force_retranslate_bypasses_cache_lookup(self, tmp_path):
        """Test that force=True bypasses TM lookup in _translate_to_language."""
        # Create minimal test file
        test_file = tmp_path / "test.md"
        test_file.write_text("---\ntitle: Test\n---\n\nHello world")

        # Mock dependencies
        with patch('src.translation_engine.engine.ModelLoader') as mock_loader_cls:
            with patch('src.translation_engine.engine.TranslationMemory') as mock_tm_cls:
                with patch('src.translation_engine.engine.HugoParser') as mock_parser_cls:
                    with patch('src.translation_engine.engine.SegmentExtractor') as mock_extractor_cls:
                        with patch('src.translation_engine.engine.MarkdownReconstructor') as mock_reconstructor_cls:
                            # Setup mocks
                            mock_tm = Mock()
                            mock_tm_cls.return_value = mock_tm
                            mock_tm.lookup.return_value = TMResult(hit=True, translation="Cached translation", source="l2_exact")

                            mock_backend = Mock()
                            mock_backend.translate.return_value = ["Fresh translation"]
                            mock_loader = Mock()
                            mock_loader.load_model.return_value = mock_backend
                            mock_loader_cls.return_value = mock_loader

                            mock_doc = Mock()
                            mock_doc.frontmatter = {"title": "Test"}
                            mock_parser = Mock()
                            mock_parser.parse.return_value = mock_doc
                            mock_parser_cls.return_value = mock_parser

                            mock_segment = Mock()
                            mock_segment.id = "seg1"
                            mock_segment.source_text = "Hello world"
                            mock_segment.context = None
                            mock_extractor = Mock()
                            mock_extractor.extract.return_value = [mock_segment]
                            mock_extractor_cls.return_value = mock_extractor

                            mock_reconstructor = Mock()
                            mock_reconstructor.reconstruct.return_value = "Translated content"
                            mock_reconstructor_cls.return_value = mock_reconstructor

                            # Create engine with force_retranslate=False
                            engine = TranslationEngine(
                                config_dir=Path("config"),
                                force_retranslate=False,
                            )

                            # Translate with force=False (should use cache)
                            with patch.object(engine, '_get_site_profile'):
                                with patch.object(engine, '_write_output'):
                                    result = engine.translate_file(
                                        site_id="test",
                                        file_path=test_file,
                                        target_langs=["de"],
                                        force=False,
                                    )

                            # TM lookup should be called when force=False
                            assert mock_tm.lookup.called

                            # Reset mock
                            mock_tm.lookup.reset_mock()
                            mock_backend.translate.reset_mock()

                            # Translate with force=True (should bypass cache)
                            with patch.object(engine, '_get_site_profile'):
                                with patch.object(engine, '_write_output'):
                                    result = engine.translate_file(
                                        site_id="test",
                                        file_path=test_file,
                                        target_langs=["de"],
                                        force=True,
                                    )

                            # TM lookup should NOT be called when force=True
                            assert not mock_tm.lookup.called

                            # Model translate should be called
                            assert mock_backend.translate.called

    def test_force_retranslate_updates_cache(self, tmp_path):
        """Test that force=True updates cache with fresh translations."""
        # Create minimal test file
        test_file = tmp_path / "test.md"
        test_file.write_text("---\ntitle: Test\n---\n\nHello world")

        # Mock dependencies
        with patch('src.translation_engine.engine.ModelLoader') as mock_loader_cls:
            with patch('src.translation_engine.engine.TranslationMemory') as mock_tm_cls:
                with patch('src.translation_engine.engine.HugoParser') as mock_parser_cls:
                    with patch('src.translation_engine.engine.SegmentExtractor') as mock_extractor_cls:
                        with patch('src.translation_engine.engine.MarkdownReconstructor') as mock_reconstructor_cls:
                            # Setup mocks
                            mock_tm = Mock()
                            mock_tm_cls.return_value = mock_tm

                            mock_backend = Mock()
                            mock_backend.translate.return_value = ["Fresh translation"]
                            mock_loader = Mock()
                            mock_loader.load_model.return_value = mock_backend
                            mock_loader_cls.return_value = mock_loader

                            mock_doc = Mock()
                            mock_doc.frontmatter = {"title": "Test"}
                            mock_parser = Mock()
                            mock_parser.parse.return_value = mock_doc
                            mock_parser_cls.return_value = mock_parser

                            mock_segment = Mock()
                            mock_segment.id = "seg1"
                            mock_segment.source_text = "Hello world"
                            mock_segment.context = None
                            mock_extractor = Mock()
                            mock_extractor.extract.return_value = [mock_segment]
                            mock_extractor_cls.return_value = mock_extractor

                            mock_reconstructor = Mock()
                            mock_reconstructor.reconstruct.return_value = "Translated content"
                            mock_reconstructor_cls.return_value = mock_reconstructor

                            # Create engine
                            engine = TranslationEngine(
                                config_dir=Path("config"),
                            )

                            # Translate with force=True
                            with patch.object(engine, '_get_site_profile'):
                                with patch.object(engine, '_write_output'):
                                    result = engine.translate_file(
                                        site_id="test",
                                        file_path=test_file,
                                        target_langs=["de"],
                                        force=True,
                                    )

                            # TM.store should be called with force_update=True
                            assert mock_tm.store.called
                            # Check that force_update=True was passed
                            store_calls = mock_tm.store.call_args_list
                            for call_args in store_calls:
                                if 'force_update' in call_args.kwargs:
                                    assert call_args.kwargs['force_update'] is True

    def test_force_retranslate_logs_correctly(self, tmp_path, caplog):
        """Test that force=True logs bypass message."""
        import logging
        caplog.set_level(logging.INFO)

        # Create minimal test file
        test_file = tmp_path / "test.md"
        test_file.write_text("---\ntitle: Test\n---\n\nHello world")

        # Mock dependencies
        with patch('src.translation_engine.engine.ModelLoader') as mock_loader_cls:
            with patch('src.translation_engine.engine.TranslationMemory') as mock_tm_cls:
                with patch('src.translation_engine.engine.HugoParser') as mock_parser_cls:
                    with patch('src.translation_engine.engine.SegmentExtractor') as mock_extractor_cls:
                        with patch('src.translation_engine.engine.MarkdownReconstructor') as mock_reconstructor_cls:
                            # Setup mocks
                            mock_tm = Mock()
                            mock_tm_cls.return_value = mock_tm

                            mock_backend = Mock()
                            mock_backend.translate.return_value = ["Fresh translation"]
                            mock_loader = Mock()
                            mock_loader.load_model.return_value = mock_backend
                            mock_loader_cls.return_value = mock_loader

                            mock_doc = Mock()
                            mock_doc.frontmatter = {"title": "Test"}
                            mock_parser = Mock()
                            mock_parser.parse.return_value = mock_doc
                            mock_parser_cls.return_value = mock_parser

                            mock_segment = Mock()
                            mock_segment.id = "seg1"
                            mock_segment.source_text = "Hello world"
                            mock_segment.context = None
                            mock_extractor = Mock()
                            mock_extractor.extract.return_value = [mock_segment]
                            mock_extractor_cls.return_value = mock_extractor

                            mock_reconstructor = Mock()
                            mock_reconstructor.reconstruct.return_value = "Translated content"
                            mock_reconstructor_cls.return_value = mock_reconstructor

                            # Create engine
                            engine = TranslationEngine(
                                config_dir=Path("config"),
                            )

                            # Translate with force=True
                            with patch.object(engine, '_get_site_profile'):
                                with patch.object(engine, '_write_output'):
                                    result = engine.translate_file(
                                        site_id="test",
                                        file_path=test_file,
                                        target_langs=["de"],
                                        force=True,
                                    )

                            # Check log messages
                            log_messages = [record.message for record in caplog.records]
                            assert any("Force retranslate enabled" in msg and "bypassing cache lookup" in msg for msg in log_messages)

    def test_cache_write_mode_parameter_stored(self):
        """Test cache_write_mode parameter is stored in engine instance."""
        with patch('src.translation_engine.engine.ModelLoader'):
            with patch('src.translation_engine.engine.TranslationMemory'):
                engine = TranslationEngine(
                    config_dir=Path("config"),
                    cache_write_mode="always",
                )

                assert engine.cache_write_mode == "always"

    def test_cache_write_mode_default_auto(self):
        """Test cache_write_mode defaults to 'auto'."""
        with patch('src.translation_engine.engine.ModelLoader'):
            with patch('src.translation_engine.engine.TranslationMemory'):
                engine = TranslationEngine(
                    config_dir=Path("config"),
                )

                assert engine.cache_write_mode == "auto"
