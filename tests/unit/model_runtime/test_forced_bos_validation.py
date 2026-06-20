"""
Unit tests for forced_bos_token_id validation in HuggingFaceBackend.

Verifies that when convert_tokens_to_ids() silently returns unk_token_id for
an unknown NLLB language token, the code:
  - logs a LANG_ROUTE_FAIL error
  - sets forced_bos_token_id to None
  - does NOT pass forced_bos_token_id to model.generate()

Root cause context: NLLB models silently return unk_token_id for language tokens
not in the tokenizer vocab (e.g. lvs_Latn, srp_Cyrl). This causes systematic
wrong-language output (Hungarian). Plan: validated-mixing-biscuit, Step 2.
"""

import sys
import types
import unittest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_model_info(model_id="nllb_200_600m", hf_model_id="facebook/nllb-200-distilled-600M"):
    info = MagicMock()
    info.model_id = model_id
    info.hf_model_id = hf_model_id
    info.local_path = None
    return info


def _make_torch_stub():
    """Minimal torch stub that satisfies HuggingFaceBackend.translate_with_token_counts."""
    torch_stub = types.ModuleType("torch")

    # inference_mode must work as a context manager
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=None)
    cm.__exit__ = MagicMock(return_value=False)
    torch_stub.inference_mode = MagicMock(return_value=cm)

    cuda_stub = types.ModuleType("torch.cuda")
    cuda_stub.is_available = MagicMock(return_value=False)
    cuda_stub.empty_cache = MagicMock()
    torch_stub.cuda = cuda_stub
    torch_stub.float16 = "float16"
    torch_stub.float32 = "float32"

    return torch_stub


def _make_fake_tensor():
    """Return a MagicMock that behaves like a minimal PyTorch tensor."""
    t = MagicMock()
    t.numel.return_value = 5
    t.shape = (1, 5)
    t.to.return_value = t  # .to(device) returns self
    return t


def _build_hf_backend(tokenizer, model, device="cpu"):
    """
    Build HuggingFaceBackend without real model load.

    Stubs heavy packages (ctranslate2/transformers/sentencepiece/torch) before
    importing loader so no real ML packages are required.
    """
    torch_stub = _make_torch_stub()
    stubs = {
        "ctranslate2": types.ModuleType("ctranslate2"),
        "transformers": types.ModuleType("transformers"),
        "sentencepiece": types.ModuleType("sentencepiece"),
    }
    with patch.dict(sys.modules, {**stubs, "torch": torch_stub}):
        from src.model_runtime.loader import HuggingFaceBackend

    backend = HuggingFaceBackend.__new__(HuggingFaceBackend)
    backend.model_info = _make_model_info()
    backend.device = device
    backend.model = model
    backend.tokenizer = tokenizer
    backend.loaded = True
    backend.use_fp16 = False
    backend.use_int8 = False
    backend.generation_config = {}
    backend.last_input_tokens = 0
    backend.last_output_tokens = 0
    backend.last_truncation_detected = False
    backend.truncation_count = 0
    return backend, torch_stub


def _setup_tokenizer_call(tokenizer):
    """Make tokenizer(texts, ...) return dict-like fake inputs."""
    fake_tensor = _make_fake_tensor()
    # Calling the tokenizer (tokenizer(texts, ...)) returns a plain dict
    # which {k: v.to(device) for k, v in inputs.items()} can iterate over.
    tokenizer.return_value = {"input_ids": fake_tensor, "attention_mask": fake_tensor}
    return fake_tensor


def _setup_model_generate(model):
    """Make model.generate() return fake outputs."""
    fake_out = MagicMock()
    fake_out.numel.return_value = 10
    fake_out.shape = (1, 10)  # well below default max_new_tokens=256 → no truncation
    model.generate.return_value = fake_out
    return fake_out


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestForcedBosTokenIdValidation(unittest.TestCase):
    """Tests for unk_token_id validation in NLLB forced_bos_token_id path."""

    def _make_nllb_tokenizer(self, unk_id, resolved_id):
        """
        Build a tokenizer mock that triggers the NLLB path:
        - has tgt_lang (so NLLB elif branch fires)
        - has convert_tokens_to_ids returning resolved_id
        - has unk_token_id = unk_id
        - does NOT have get_lang_id (so M2M100 path is skipped)
        """
        tokenizer = MagicMock()
        del tokenizer.get_lang_id  # removes M2M100 path
        tokenizer.tgt_lang = None
        tokenizer.src_lang = None
        tokenizer.unk_token_id = unk_id
        tokenizer.convert_tokens_to_ids.return_value = resolved_id
        tokenizer.batch_decode.return_value = ["translated text"]
        return tokenizer

    def test_lang_route_fail_logged_when_unk_token(self):
        """LANG_ROUTE_FAIL error must be logged when lvs_Latn resolves to unk_token_id."""
        UNK_ID = 1
        tokenizer = self._make_nllb_tokenizer(unk_id=UNK_ID, resolved_id=UNK_ID)
        model = MagicMock()
        backend, torch_stub = _build_hf_backend(tokenizer, model)
        _setup_tokenizer_call(tokenizer)
        _setup_model_generate(model)

        with patch("src.model_runtime.loader.torch", torch_stub):
            with self.assertLogs("src.model_runtime.loader", level="ERROR") as cm:
                backend.translate_with_token_counts(["hello world"], "en", "lv")

        error_msgs = [r for r in cm.output if "ERROR" in r]
        self.assertTrue(
            any("LANG_ROUTE_FAIL" in m for m in error_msgs),
            f"Expected LANG_ROUTE_FAIL in error log, got: {cm.output}",
        )

    def test_forced_bos_not_passed_to_generate_when_unk_token(self):
        """model.generate must NOT receive forced_bos_token_id when token resolves to unk."""
        UNK_ID = 1
        tokenizer = self._make_nllb_tokenizer(unk_id=UNK_ID, resolved_id=UNK_ID)
        model = MagicMock()
        backend, torch_stub = _build_hf_backend(tokenizer, model)
        _setup_tokenizer_call(tokenizer)
        _setup_model_generate(model)

        with patch("src.model_runtime.loader.torch", torch_stub):
            with self.assertLogs("src.model_runtime.loader", level="ERROR"):
                backend.translate_with_token_counts(["hello world"], "en", "lv")

        call_kwargs = model.generate.call_args[1]
        self.assertNotIn(
            "forced_bos_token_id",
            call_kwargs,
            "forced_bos_token_id should not be passed to generate() when token is unk",
        )

    def test_no_error_when_valid_token_id(self):
        """No LANG_ROUTE_FAIL when convert_tokens_to_ids returns a valid (non-unk) ID."""
        UNK_ID = 1
        VALID_NLLB_ID = 256047  # typical NLLB language token ID
        tokenizer = self._make_nllb_tokenizer(unk_id=UNK_ID, resolved_id=VALID_NLLB_ID)
        model = MagicMock()
        backend, torch_stub = _build_hf_backend(tokenizer, model)
        _setup_tokenizer_call(tokenizer)
        _setup_model_generate(model)

        with patch("src.model_runtime.loader.torch", torch_stub):
            with self.assertNoLogs("src.model_runtime.loader", level="ERROR"):
                backend.translate_with_token_counts(["hello world"], "en", "de")

        # forced_bos_token_id SHOULD be passed when valid
        call_kwargs = model.generate.call_args[1]
        self.assertIn("forced_bos_token_id", call_kwargs)
        self.assertEqual(call_kwargs["forced_bos_token_id"], VALID_NLLB_ID)

    def test_no_validation_when_unk_token_id_attr_absent(self):
        """If tokenizer lacks unk_token_id, validation is skipped (safe fallback)."""
        SOME_ID = 99
        tokenizer = self._make_nllb_tokenizer(unk_id=None, resolved_id=SOME_ID)
        del tokenizer.unk_token_id  # attribute absent → getattr returns None → validation skipped
        model = MagicMock()
        backend, torch_stub = _build_hf_backend(tokenizer, model)
        _setup_tokenizer_call(tokenizer)
        _setup_model_generate(model)

        with patch("src.model_runtime.loader.torch", torch_stub):
            with self.assertNoLogs("src.model_runtime.loader", level="ERROR"):
                backend.translate_with_token_counts(["hello world"], "en", "de")

        # forced_bos_token_id should be passed through unchanged
        call_kwargs = model.generate.call_args[1]
        self.assertEqual(call_kwargs.get("forced_bos_token_id"), SOME_ID)


if __name__ == "__main__":
    unittest.main()
