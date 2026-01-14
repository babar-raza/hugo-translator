"""
Unit tests for translation backends (ITranslationBackend, MTBackend, LLMBackend).

Tests backend interface contract and implementation behavior with mocked dependencies.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from src.translation_engine.backends import ITranslationBackend, MTBackend, LLMBackend


class TestITranslationBackend(unittest.TestCase):
    """Test abstract interface contract."""

    def test_interface_cannot_be_instantiated(self):
        """Test that abstract interface cannot be instantiated directly."""
        with self.assertRaises(TypeError):
            ITranslationBackend()  # type: ignore

    def test_interface_requires_translate_implementation(self):
        """Test that subclasses must implement translate()."""
        class IncompleteBackend(ITranslationBackend):
            def get_model_info(self):
                return {}

        with self.assertRaises(TypeError):
            IncompleteBackend()  # Missing translate() implementation

    def test_interface_default_translate_batch(self):
        """Test that default translate_batch() calls translate() sequentially."""
        class MinimalBackend(ITranslationBackend):
            def translate(self, text, src_lang, tgt_lang, **kwargs):
                return f"{text}_translated"

            def get_model_info(self):
                return {"backend_type": "test"}

        backend = MinimalBackend()
        results = backend.translate_batch(["hello", "world"], "en", "es")
        self.assertEqual(results, ["hello_translated", "world_translated"])

    def test_interface_default_supports_language_pair(self):
        """Test that default supports_language_pair() returns True."""
        class MinimalBackend(ITranslationBackend):
            def translate(self, text, src_lang, tgt_lang, **kwargs):
                return text

            def get_model_info(self):
                return {}

        backend = MinimalBackend()
        self.assertTrue(backend.supports_language_pair("en", "es"))
        self.assertTrue(backend.supports_language_pair("zh", "fr"))

    def test_interface_default_warmup_shutdown(self):
        """Test that default warmup() and shutdown() are no-ops."""
        class MinimalBackend(ITranslationBackend):
            def translate(self, text, src_lang, tgt_lang, **kwargs):
                return text

            def get_model_info(self):
                return {}

        backend = MinimalBackend()
        # Should not raise
        backend.warmup()
        backend.shutdown()


class TestMTBackend(unittest.TestCase):
    """Test MT backend (wraps ModelLoader)."""

    @patch('src.translation_engine.backends.mt_backend.ModelLoader')
    @patch('src.translation_engine.backends.mt_backend.ModelRegistry')
    def test_mt_backend_initialization(self, mock_registry, mock_loader):
        """Test MTBackend initializes with correct parameters."""
        backend = MTBackend(
            model_id="m2m100_418m",
            device="cuda",
            max_memory_mb=4096,
            load_mode="fp16"
        )

        self.assertEqual(backend.model_id, "m2m100_418m")
        self.assertEqual(backend.device, "cuda")
        self.assertEqual(backend.max_memory_mb, 4096)
        self.assertEqual(backend.load_mode, "fp16")
        self.assertFalse(backend._loaded)

    @patch('src.translation_engine.backends.mt_backend.ModelLoader')
    @patch('src.translation_engine.backends.mt_backend.ModelRegistry')
    def test_mt_backend_lazy_loading(self, mock_registry, mock_loader):
        """Test that model is loaded on first translate() call."""
        mock_model = Mock()
        mock_model.translate.return_value = ["hola"]
        mock_loader_instance = mock_loader.return_value
        mock_loader_instance.load_model.return_value = mock_model

        backend = MTBackend(model_id="m2m100_418m", device="cuda")

        # Model not loaded initially
        self.assertFalse(backend._loaded)
        self.assertIsNone(backend.backend)

        # Translate triggers loading
        result = backend.translate("hello", "en", "es")

        # Verify loading occurred
        self.assertTrue(backend._loaded)
        self.assertIsNotNone(backend.backend)
        mock_loader_instance.load_model.assert_called_once_with(
            model_id="m2m100_418m",
            device="cuda"
        )

        # Verify translation
        self.assertEqual(result, "hola")
        mock_model.translate.assert_called_once_with(
            texts=["hello"],
            src_lang="en",
            tgt_lang="es",
            max_new_tokens=None
        )

    @patch('src.translation_engine.backends.mt_backend.ModelLoader')
    @patch('src.translation_engine.backends.mt_backend.ModelRegistry')
    def test_mt_backend_translate_batch(self, mock_registry, mock_loader):
        """Test batch translation."""
        mock_model = Mock()
        mock_model.translate.return_value = ["hola", "mundo"]
        mock_loader_instance = mock_loader.return_value
        mock_loader_instance.load_model.return_value = mock_model

        backend = MTBackend(model_id="m2m100_418m", device="cuda")
        results = backend.translate_batch(["hello", "world"], "en", "es")

        self.assertEqual(results, ["hola", "mundo"])
        mock_model.translate.assert_called_once_with(
            texts=["hello", "world"],
            src_lang="en",
            tgt_lang="es",
            max_new_tokens=None
        )

    @patch('src.translation_engine.backends.mt_backend.ModelLoader')
    @patch('src.translation_engine.backends.mt_backend.ModelRegistry')
    def test_mt_backend_get_model_info(self, mock_registry, mock_loader):
        """Test get_model_info() returns correct metadata."""
        backend = MTBackend(
            model_id="m2m100_418m",
            device="cuda",
            max_memory_mb=4096,
            load_mode="fp16"
        )

        info = backend.get_model_info()

        self.assertEqual(info["backend_type"], "mt")
        self.assertEqual(info["model_id"], "m2m100_418m")
        self.assertEqual(info["device"], "cuda")
        self.assertEqual(info["load_mode"], "fp16")
        self.assertEqual(info["max_memory_mb"], 4096)
        self.assertFalse(info["loaded"])

    @patch('src.translation_engine.backends.mt_backend.ModelLoader')
    @patch('src.translation_engine.backends.mt_backend.ModelRegistry')
    def test_mt_backend_warmup(self, mock_registry, mock_loader):
        """Test warmup() pre-loads model."""
        mock_model = Mock()
        mock_loader_instance = mock_loader.return_value
        mock_loader_instance.load_model.return_value = mock_model

        backend = MTBackend(model_id="m2m100_418m", device="cuda")
        self.assertFalse(backend._loaded)

        # Warmup should load model
        backend.warmup()

        self.assertTrue(backend._loaded)
        mock_loader_instance.load_model.assert_called_once()

    @patch('src.translation_engine.backends.mt_backend.ModelLoader')
    @patch('src.translation_engine.backends.mt_backend.ModelRegistry')
    def test_mt_backend_shutdown(self, mock_registry, mock_loader):
        """Test shutdown() unloads model."""
        mock_model = Mock()
        mock_loader_instance = mock_loader.return_value
        mock_loader_instance.load_model.return_value = mock_model

        backend = MTBackend(model_id="m2m100_418m", device="cuda")
        backend.warmup()  # Load model

        # Shutdown should unload
        backend.shutdown()

        self.assertFalse(backend._loaded)
        self.assertIsNone(backend.backend)
        mock_model.unload.assert_called_once()


class TestLLMBackend(unittest.TestCase):
    """Test LLM backend (Anthropic Claude API)."""

    @patch('src.translation_engine.backends.llm_backend.anthropic')
    @patch('src.translation_engine.backends.llm_backend.ANTHROPIC_AVAILABLE', True)
    def test_llm_backend_initialization(self, mock_anthropic):
        """Test LLMBackend initializes with API key."""
        mock_client = Mock()
        mock_anthropic.Anthropic.return_value = mock_client

        backend = LLMBackend(
            model_id="claude-sonnet-4",
            api_key="test_api_key",
            max_tokens=2048,
            temperature=0.3
        )

        self.assertEqual(backend.model_id, "claude-sonnet-4")
        self.assertEqual(backend.api_key, "test_api_key")
        self.assertEqual(backend.max_tokens, 2048)
        self.assertEqual(backend.temperature, 0.3)
        mock_anthropic.Anthropic.assert_called_once_with(api_key="test_api_key")

    @patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'env_api_key'})
    @patch('src.translation_engine.backends.llm_backend.anthropic')
    @patch('src.translation_engine.backends.llm_backend.ANTHROPIC_AVAILABLE', True)
    def test_llm_backend_api_key_from_env(self, mock_anthropic):
        """Test LLMBackend reads API key from environment."""
        mock_anthropic.Anthropic.return_value = Mock()

        backend = LLMBackend(model_id="claude-sonnet-4")

        self.assertEqual(backend.api_key, "env_api_key")

    @patch('src.translation_engine.backends.llm_backend.ANTHROPIC_AVAILABLE', True)
    @patch('src.translation_engine.backends.llm_backend.anthropic')
    def test_llm_backend_translate(self, mock_anthropic):
        """Test translate() calls Claude API correctly."""
        mock_client = Mock()
        mock_response = Mock()
        mock_response.content = [Mock(text="hola")]
        mock_response.usage = Mock(input_tokens=10, output_tokens=5)
        mock_client.messages.create.return_value = mock_response
        mock_anthropic.Anthropic.return_value = mock_client

        backend = LLMBackend(model_id="claude-sonnet-4", api_key="test_key")
        result = backend.translate("hello", "en", "es")

        self.assertEqual(result, "hola")
        mock_client.messages.create.assert_called_once()
        call_kwargs = mock_client.messages.create.call_args[1]
        self.assertEqual(call_kwargs["model"], "claude-sonnet-4")
        self.assertEqual(call_kwargs["max_tokens"], 4096)
        self.assertEqual(call_kwargs["temperature"], 0.0)
        self.assertIn("Spanish", call_kwargs["system"])
        self.assertEqual(call_kwargs["messages"][0]["content"], "hello")

    @patch('src.translation_engine.backends.llm_backend.ANTHROPIC_AVAILABLE', True)
    @patch('src.translation_engine.backends.llm_backend.anthropic')
    def test_llm_backend_translate_batch(self, mock_anthropic):
        """Test translate_batch() makes sequential calls."""
        mock_client = Mock()
        mock_response_1 = Mock()
        mock_response_1.content = [Mock(text="hola")]
        mock_response_1.usage = Mock(input_tokens=10, output_tokens=5)
        mock_response_2 = Mock()
        mock_response_2.content = [Mock(text="mundo")]
        mock_response_2.usage = Mock(input_tokens=10, output_tokens=5)
        mock_client.messages.create.side_effect = [mock_response_1, mock_response_2]
        mock_anthropic.Anthropic.return_value = mock_client

        backend = LLMBackend(model_id="claude-sonnet-4", api_key="test_key")
        results = backend.translate_batch(["hello", "world"], "en", "es")

        self.assertEqual(results, ["hola", "mundo"])
        self.assertEqual(mock_client.messages.create.call_count, 2)

    @patch('src.translation_engine.backends.llm_backend.ANTHROPIC_AVAILABLE', True)
    @patch('src.translation_engine.backends.llm_backend.anthropic')
    def test_llm_backend_get_model_info(self, mock_anthropic):
        """Test get_model_info() returns correct metadata."""
        mock_anthropic.Anthropic.return_value = Mock()

        backend = LLMBackend(
            model_id="claude-opus-4",
            api_key="test_key",
            max_tokens=8192,
            temperature=0.5
        )

        info = backend.get_model_info()

        self.assertEqual(info["backend_type"], "llm")
        self.assertEqual(info["model_id"], "claude-opus-4")
        self.assertEqual(info["device"], "api")
        self.assertEqual(info["max_tokens"], 8192)
        self.assertEqual(info["temperature"], 0.5)

    @patch('src.translation_engine.backends.llm_backend.ANTHROPIC_AVAILABLE', True)
    @patch('src.translation_engine.backends.llm_backend.anthropic')
    def test_llm_backend_supports_all_languages(self, mock_anthropic):
        """Test supports_language_pair() returns True for all pairs."""
        mock_anthropic.Anthropic.return_value = Mock()

        backend = LLMBackend(model_id="claude-sonnet-4", api_key="test_key")

        self.assertTrue(backend.supports_language_pair("en", "es"))
        self.assertTrue(backend.supports_language_pair("zh", "ar"))
        self.assertTrue(backend.supports_language_pair("unknown", "code"))

    @patch('src.translation_engine.backends.llm_backend.ANTHROPIC_AVAILABLE', False)
    def test_llm_backend_requires_anthropic_sdk(self):
        """Test LLMBackend raises error if anthropic SDK not installed."""
        with self.assertRaises(RuntimeError) as ctx:
            LLMBackend(model_id="claude-sonnet-4", api_key="test_key")

        self.assertIn("anthropic SDK not installed", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
