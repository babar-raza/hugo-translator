"""
Unit tests for cache_write_mode in TM layers (T203: federated-splashing-panda).

Tests that --cache-write-mode flag controls cache write behavior.
"""
import pytest
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch, call
from src.translation_engine.engine import TranslationEngine


class TestCacheWriteMode:
    """Test cache_write_mode parameter in TranslationEngine and TM layers."""

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

    def test_cache_write_mode_auto_writes_to_cache(self, tmp_path):
        """Test cache_write_mode='auto' writes to cache (default behavior)."""
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
                            mock_backend.translate.return_value = ["Translation"]
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

                            # Create engine with cache_write_mode='auto'
                            engine = TranslationEngine(
                                config_dir=Path("config"),
                                cache_write_mode="auto",
                            )

                            # Translate
                            with patch.object(engine, '_get_site_profile'):
                                with patch.object(engine, '_write_output'):
                                    result = engine.translate_file(
                                        site_id="test",
                                        file_path=test_file,
                                        target_langs=["de"],
                                        force=False,
                                    )

                            # TM.store should be called with force_update=False (auto mode)
                            assert mock_tm.store.called
                            store_calls = mock_tm.store.call_args_list
                            for call_args in store_calls:
                                if 'force_update' in call_args.kwargs:
                                    assert call_args.kwargs['force_update'] is False

    def test_cache_write_mode_always_overwrites_existing(self, tmp_path):
        """Test cache_write_mode='always' overwrites existing cache entries."""
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

                            # Create engine with cache_write_mode='always'
                            engine = TranslationEngine(
                                config_dir=Path("config"),
                                cache_write_mode="always",
                            )

                            # Translate
                            with patch.object(engine, '_get_site_profile'):
                                with patch.object(engine, '_write_output'):
                                    result = engine.translate_file(
                                        site_id="test",
                                        file_path=test_file,
                                        target_langs=["de"],
                                        force=False,
                                    )

                            # TM.store should be called with force_update=True (always mode)
                            assert mock_tm.store.called
                            store_calls = mock_tm.store.call_args_list
                            for call_args in store_calls:
                                if 'force_update' in call_args.kwargs:
                                    assert call_args.kwargs['force_update'] is True

    def test_cache_write_mode_never_skips_writes(self, tmp_path):
        """Test cache_write_mode='never' skips all cache writes."""
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
                            mock_backend.translate.return_value = ["Translation"]
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

                            # Create engine with cache_write_mode='never'
                            engine = TranslationEngine(
                                config_dir=Path("config"),
                                cache_write_mode="never",
                            )

                            # Translate
                            with patch.object(engine, '_get_site_profile'):
                                with patch.object(engine, '_write_output'):
                                    result = engine.translate_file(
                                        site_id="test",
                                        file_path=test_file,
                                        target_langs=["de"],
                                        force=False,
                                    )

                            # TM.store should NOT be called in never mode
                            assert not mock_tm.store.called

    def test_cache_write_mode_logs_correctly(self, tmp_path, caplog):
        """Test that cache_write_mode logs configuration message."""
        import logging
        caplog.set_level(logging.INFO)

        with patch('src.translation_engine.engine.ModelLoader'):
            with patch('src.translation_engine.engine.TranslationMemory'):
                # Create engine with cache_write_mode='always'
                engine = TranslationEngine(
                    config_dir=Path("config"),
                    cache_write_mode="always",
                )

                # Check log messages
                log_messages = [record.message for record in caplog.records]
                assert any("Cache write mode: always" in msg for msg in log_messages)

    def test_force_retranslate_with_cache_write_mode_always(self, tmp_path):
        """Test combining force_retranslate with cache_write_mode='always'."""
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

                            # Create engine with both force_retranslate and cache_write_mode='always'
                            engine = TranslationEngine(
                                config_dir=Path("config"),
                                force_retranslate=True,
                                cache_write_mode="always",
                            )

                            # Translate
                            with patch.object(engine, '_get_site_profile'):
                                with patch.object(engine, '_write_output'):
                                    result = engine.translate_file(
                                        site_id="test",
                                        file_path=test_file,
                                        target_langs=["de"],
                                        force=True,  # force_retranslate passed as force parameter
                                    )

                            # TM.lookup should NOT be called (force_retranslate bypasses cache)
                            assert not mock_tm.lookup.called

                            # TM.store should be called with force_update=True (cache_write_mode='always')
                            assert mock_tm.store.called
                            store_calls = mock_tm.store.call_args_list
                            for call_args in store_calls:
                                if 'force_update' in call_args.kwargs:
                                    assert call_args.kwargs['force_update'] is True

    def test_force_retranslate_with_cache_write_mode_never(self, tmp_path):
        """Test combining force_retranslate with cache_write_mode='never' (unusual but valid)."""
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

                            # Create engine with force_retranslate=True and cache_write_mode='never'
                            engine = TranslationEngine(
                                config_dir=Path("config"),
                                force_retranslate=True,
                                cache_write_mode="never",
                            )

                            # Translate
                            with patch.object(engine, '_get_site_profile'):
                                with patch.object(engine, '_write_output'):
                                    result = engine.translate_file(
                                        site_id="test",
                                        file_path=test_file,
                                        target_langs=["de"],
                                        force=True,
                                    )

                            # TM.lookup should NOT be called (force_retranslate bypasses cache)
                            assert not mock_tm.lookup.called

                            # TM.store should NOT be called (cache_write_mode='never' skips writes)
                            assert not mock_tm.store.called
