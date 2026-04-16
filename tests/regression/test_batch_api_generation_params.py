"""
Regression test for batch translation API mismatch.

Tests that HuggingFaceBackend.translate() accepts generation_params parameter
without throwing "unexpected keyword argument" error.

MISSION: Fix batch translation API mismatch identified in PHASE10_PROD_FORCE_TRANSLATE.md
"""
import sys
import os
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

# Add src to path
REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.chdir(str(REPO_ROOT))

import pytest


def test_translate_accepts_generation_params():
    """
    Test that translate() method accepts generation_params parameter.

    This test should FAIL before the fix (TypeError: unexpected keyword argument)
    and PASS after the fix.
    """
    print("\n" + "=" * 80)
    print("TEST: Batch API generation_params Parameter Support")
    print("=" * 80)

    # Import after path setup
    from src.model_runtime.loader import HuggingFaceBackend
    from src.model_runtime.registry import ModelInfo

    # Create minimal ModelInfo
    model_info = ModelInfo(
        model_id="test-model",
        name="Test M2M100 Model",
        backend="huggingface",
        supported_pairs="all",
        model_size_mb=1000,
        min_ram_gb=2.0,
        optimal_device="cpu",
        hf_model_id="facebook/m2m100_418M"
    )

    # Create backend instance (don't actually load the model)
    backend = HuggingFaceBackend(model_info, device="cpu")

    # Mock the model and tokenizer to avoid actual loading
    backend.model = MagicMock()
    backend.tokenizer = MagicMock()
    backend.loaded = True
    backend.generation_config = {"speed_mode": True}

    # Configure mock tokenizer
    backend.tokenizer.return_value = {
        "input_ids": MagicMock(numel=MagicMock(return_value=10), to=MagicMock(return_value=MagicMock())),
        "attention_mask": MagicMock(to=MagicMock(return_value=MagicMock()))
    }
    backend.tokenizer.get_lang_id = MagicMock(return_value=123)

    # Configure mock model.generate() to return fake token IDs
    mock_outputs = MagicMock()
    mock_outputs.numel = MagicMock(return_value=15)
    mock_outputs.shape = [1, 15]  # batch_size=1, seq_len=15
    backend.model.generate = MagicMock(return_value=mock_outputs)
    backend.model.eval = MagicMock()

    # Configure mock tokenizer.batch_decode()
    backend.tokenizer.batch_decode = MagicMock(return_value=["Translated text"])

    print("\n[1/3] Created mock HuggingFaceBackend")

    # Test texts
    texts = ["Hello world"]
    src_lang = "en"
    tgt_lang = "fr"

    # Custom generation parameters
    generation_params = {
        "num_beams": 4,
        "temperature": 0.7,
        "top_p": 0.9
    }

    print(f"[2/3] Calling translate() with generation_params: {generation_params}")

    # CRITICAL TEST: Call translate() with generation_params
    # Before fix: TypeError: translate() got an unexpected keyword argument 'generation_params'
    # After fix: No exception
    try:
        translations = backend.translate(
            texts=texts,
            src_lang=src_lang,
            tgt_lang=tgt_lang,
            max_new_tokens=256,
            generation_params=generation_params
        )
        print("[3/3] translate() call succeeded (no exception)")
    except TypeError as e:
        if "generation_params" in str(e):
            pytest.fail(
                f"translate() does not accept generation_params parameter. "
                f"Error: {e}"
            )
        else:
            raise

    # ASSERTIONS
    print("\n" + "=" * 80)
    print("ASSERTIONS:")
    print("=" * 80)

    # Assert no exception was raised
    assert translations is not None, "translate() returned None"
    assert len(translations) == 1, f"Expected 1 translation, got {len(translations)}"
    print("[PASS] translate() accepts generation_params without exception")

    # Verify model.generate() was called (meaning translation happened)
    assert backend.model.generate.called, "model.generate() was not called"
    print("[PASS] model.generate() was invoked")

    # Verify generation_params were passed to model.generate()
    # The generate() call should include our custom parameters
    call_kwargs = backend.model.generate.call_args.kwargs

    assert "num_beams" in call_kwargs, "num_beams not passed to model.generate()"
    assert call_kwargs["num_beams"] == 4, f"Expected num_beams=4, got {call_kwargs['num_beams']}"
    print(f"[PASS] Custom num_beams parameter applied: {call_kwargs['num_beams']}")

    assert "temperature" in call_kwargs, "temperature not passed to model.generate()"
    assert call_kwargs["temperature"] == 0.7, f"Expected temperature=0.7, got {call_kwargs['temperature']}"
    print(f"[PASS] Custom temperature parameter applied: {call_kwargs['temperature']}")

    assert "top_p" in call_kwargs, "top_p not passed to model.generate()"
    assert call_kwargs["top_p"] == 0.9, f"Expected top_p=0.9, got {call_kwargs['top_p']}"
    print(f"[PASS] Custom top_p parameter applied: {call_kwargs['top_p']}")

    print("\n" + "=" * 80)
    print("TEST PASSED: generation_params parameter supported and applied!")
    print("=" * 80)


def test_translate_with_token_counts_accepts_generation_params():
    """
    Test that translate_with_token_counts() method also accepts generation_params.

    This ensures the parameter is propagated through the entire call chain.
    """
    print("\n" + "=" * 80)
    print("TEST: translate_with_token_counts() generation_params Support")
    print("=" * 80)

    # Import after path setup
    from src.model_runtime.loader import HuggingFaceBackend
    from src.model_runtime.registry import ModelInfo

    # Create minimal ModelInfo
    model_info = ModelInfo(
        model_id="test-model",
        name="Test M2M100 Model",
        backend="huggingface",
        supported_pairs="all",
        model_size_mb=1000,
        min_ram_gb=2.0,
        optimal_device="cpu",
        hf_model_id="facebook/m2m100_418M"
    )

    # Create backend instance
    backend = HuggingFaceBackend(model_info, device="cpu")

    # Mock the model and tokenizer
    backend.model = MagicMock()
    backend.tokenizer = MagicMock()
    backend.loaded = True
    backend.generation_config = {"speed_mode": True}

    # Configure mocks
    backend.tokenizer.return_value = {
        "input_ids": MagicMock(numel=MagicMock(return_value=10), to=MagicMock(return_value=MagicMock())),
        "attention_mask": MagicMock(to=MagicMock(return_value=MagicMock()))
    }
    backend.tokenizer.get_lang_id = MagicMock(return_value=123)

    mock_outputs = MagicMock()
    mock_outputs.numel = MagicMock(return_value=15)
    mock_outputs.shape = [1, 15]
    backend.model.generate = MagicMock(return_value=mock_outputs)
    backend.model.eval = MagicMock()
    backend.tokenizer.batch_decode = MagicMock(return_value=["Translated text"])

    print("[1/2] Created mock HuggingFaceBackend")

    # Test call with generation_params
    generation_params = {"num_beams": 2}

    try:
        translations, input_tokens, output_tokens = backend.translate_with_token_counts(
            texts=["Test"],
            src_lang="en",
            tgt_lang="fr",
            max_new_tokens=256,
            generation_params=generation_params
        )
        print("[2/2] translate_with_token_counts() call succeeded")
    except TypeError as e:
        if "generation_params" in str(e):
            pytest.fail(
                f"translate_with_token_counts() does not accept generation_params. "
                f"Error: {e}"
            )
        else:
            raise

    # ASSERTIONS
    print("\n" + "=" * 80)
    print("ASSERTIONS:")
    print("=" * 80)

    assert translations is not None, "translations is None"
    assert input_tokens is not None, "input_tokens is None"
    assert output_tokens is not None, "output_tokens is None"
    print("[PASS] translate_with_token_counts() accepts generation_params and returns token counts")

    print("\n" + "=" * 80)
    print("TEST PASSED: translate_with_token_counts() supports generation_params!")
    print("=" * 80)


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("REGRESSION TEST SUITE: Batch API generation_params Support")
    print("=" * 80)

    try:
        test_translate_accepts_generation_params()
        print("\n[OK] Test 1 passed\n")
    except (AssertionError, TypeError) as e:
        print(f"\n[FAIL] Test 1 FAILED: {e}\n")
        raise

    try:
        test_translate_with_token_counts_accepts_generation_params()
        print("\n[OK] Test 2 passed\n")
    except (AssertionError, TypeError) as e:
        print(f"\n[FAIL] Test 2 FAILED: {e}\n")
        raise

    print("\n" + "=" * 80)
    print("ALL TESTS PASSED!")
    print("=" * 80)
