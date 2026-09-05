"""TC-APT-046 Test D + TC-APT-044's serialization half — permanent CI regression guards.

Plan §0.3/G-30: an engine-wide ``_model_execution_lock`` in ``campaign_runner`` used to
serialize *every* ``translate_file`` call, GPU and API alike, which silently defeated LLM
concurrency — raising ``max_parallel_jobs`` bought nothing. TC-APT-044 moved the lock onto
the backend instances that actually own non-thread-safe state.

These tests pin both halves of that, so the broad lock cannot quietly come back:

* Test D — concurrent ``LLMModelBackend`` calls overlap: K calls finish in about one call's
  latency, not K times it.
* Its counterpart — concurrent ``HuggingFaceBackend`` generation still serializes, because
  the shared tokenizer's ``src_lang``/``tgt_lang`` mutation and the ``last_*`` counters are
  genuinely per-instance shared state (no CUDA-concurrency regression).

Both drive the real classes with only the model/provider call replaced, so a lock
reintroduced anywhere above that seam is caught.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from src.model_runtime.llm_backend import LLMModelBackend
from src.model_runtime.loader import HuggingFaceBackend
from src.model_runtime.registry import ModelInfo

CALL_DELAY = 0.20
CONCURRENCY = 4
REPO_ROOT = Path(__file__).resolve().parents[2]


class _OverlapRecorder:
    """Track how many calls are inside the guarded region at the same time."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0

    def enter(self) -> None:
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)

    def exit(self) -> None:
        with self._lock:
            self.active -= 1

    def sleep_through(self, delay: float = CALL_DELAY) -> None:
        self.enter()
        try:
            time.sleep(delay)
        finally:
            self.exit()


def _model_info(model_id: str, backend: str) -> ModelInfo:
    return ModelInfo(
        model_id=model_id,
        name=model_id,
        backend=backend,
        supported_pairs="all",
        model_size_mb=1,
        min_ram_gb=0.1,
        optimal_device="cpu",
    )


def _run_concurrently(call, count: int = CONCURRENCY) -> float:
    started = threading.Barrier(count)

    def _job(index: int):
        started.wait(timeout=10)
        return call(index)

    begin = time.perf_counter()
    with ThreadPoolExecutor(max_workers=count) as pool:
        list(pool.map(_job, range(count)))
    return time.perf_counter() - begin


def test_llm_backend_jobs_run_concurrently_not_serialized(monkeypatch):
    """Test D: K concurrent LLM calls take ~one call's latency, not K x it."""
    backend = LLMModelBackend(_model_info("professionalize_llm", "llm"), "api")
    backend.loaded = True
    monkeypatch.setattr(type(backend), "_term_manager", property(lambda self: None))

    recorder = _OverlapRecorder()

    def _fake_segment(text, idx, total, src_lang, tgt_lang, tm, translations):
        recorder.sleep_through()
        translations[idx] = f"{tgt_lang}:{text}"
        return 1, 1

    monkeypatch.setattr(backend, "_translate_single_segment", _fake_segment)

    elapsed = _run_concurrently(lambda i: backend.translate([f"text {i}"], "en", "de"))

    assert recorder.max_active == CONCURRENCY, (
        "LLM backend calls did not overlap — an engine-wide or backend-level lock is "
        "serializing pure-I/O API work again (plan §0.3/G-30)"
    )
    assert elapsed < CALL_DELAY * CONCURRENCY * 0.6, (
        f"{CONCURRENCY} concurrent LLM calls took {elapsed:.3f}s; serialized would be "
        f"~{CALL_DELAY * CONCURRENCY:.3f}s and concurrent ~{CALL_DELAY:.3f}s"
    )


def test_llm_backend_holds_no_generation_lock():
    """Structural counterpart: the LLM backend must not acquire a generation lock.

    It deliberately does not subclass ``ModelBackend`` and owns no GPU state, so
    a ``_generation_lock`` appearing here would be the G-30 regression itself.
    """
    backend = LLMModelBackend(_model_info("professionalize_llm", "llm"), "api")

    assert not hasattr(backend, "_generation_lock")
    assert not isinstance(backend, HuggingFaceBackend)


def test_huggingface_backend_generation_still_serializes(monkeypatch):
    """TC-APT-044's other half: GPU generation on one instance must not overlap."""
    backend = HuggingFaceBackend(_model_info("m2m100_418m", "huggingface"), "cpu")
    recorder = _OverlapRecorder()

    def _fake_impl(texts, src_lang, tgt_lang, max_new_tokens=None, generation_params=None):
        recorder.sleep_through()
        return [f"{tgt_lang}:{text}" for text in texts], 1, 1

    monkeypatch.setattr(backend, "_translate_with_token_counts_impl", _fake_impl)

    elapsed = _run_concurrently(
        lambda i: backend.translate_with_token_counts([f"text {i}"], "en", "de")
    )

    assert recorder.max_active == 1, (
        "HuggingFace generation overlapped — the shared tokenizer's src_lang/tgt_lang "
        "mutation and last_* counters are not thread-safe (CUDA-concurrency regression)"
    )
    assert elapsed >= CALL_DELAY * CONCURRENCY * 0.8, (
        f"serialized {CONCURRENCY} calls should take ~{CALL_DELAY * CONCURRENCY:.3f}s, "
        f"took {elapsed:.3f}s"
    )


def test_two_huggingface_instances_do_not_serialize_against_each_other(monkeypatch):
    """The lock is per instance, not per class — two loaded models stay independent."""
    backends = [
        HuggingFaceBackend(_model_info(f"m2m100_{i}", "huggingface"), "cpu") for i in range(2)
    ]
    recorder = _OverlapRecorder()

    for backend in backends:

        def _fake_impl(texts, src_lang, tgt_lang, max_new_tokens=None, generation_params=None):
            recorder.sleep_through()
            return list(texts), 1, 1

        monkeypatch.setattr(backend, "_translate_with_token_counts_impl", _fake_impl)

    _run_concurrently(
        lambda i: backends[i].translate_with_token_counts(["text"], "en", "de"), count=2
    )

    assert recorder.max_active == 2


def test_campaign_runner_has_no_engine_wide_model_lock():
    """The deleted engine-wide lock must not reappear in the campaign path."""
    source = (REPO_ROOT / "src" / "workers" / "campaign_runner.py").read_text(encoding="utf-8")

    assert "_model_execution_lock = threading" not in source
    assert "with self._model_execution_lock" not in source
