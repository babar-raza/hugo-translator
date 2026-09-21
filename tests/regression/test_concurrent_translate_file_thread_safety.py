"""TC-APT-043: concurrent frontmatter parsing must not cross-contaminate.

Root-cause reproduction + permanent regression guard for the shared-mutable-
state hazard behind the historical "intermittent empty-frontmatter crash"
(scripts/campaign/run_llm_qualification.py:161-168, reproduced at
concurrency=2, never at 1): ``hugo_parser`` constructed ONE module-level
``ruamel.yaml.YAML()`` instance shared by every ``HugoParser`` in the process,
and ``_parse_yaml_content`` swallows any exception from ``.load()`` into a
None/empty frontmatter.

Test A (plan §11): two frontmatter fixtures parsed on two threads with a
deterministic forced interleaving — thread 1 is suspended inside ``.load()``
right after wiring the YAML object to its stream, thread 2 then wires (the
same shared object pre-fix; its own private object post-fix), and both
complete. Pre-fix this reproduces cross-assignment/corruption; post-fix every
repetition must return each thread its own correct mapping. Repeated to also
catch timing-only races.
"""

import threading
from unittest.mock import Mock

import ruamel.yaml.main as ruamel_main

from src.translation_engine.parser.hugo_parser import HugoParser

FIXTURE_ALPHA = (
    'title: "Alpha document about spreadsheets"\n'
    'description: "Alpha covers workbook management in Go"\n'
    "weight: 10\n"
)
FIXTURE_BETA = (
    'title: "Beta document about presentations"\n'
    'description: "Beta covers slide rendering in Java"\n'
    "weight: 20\n"
)

_REPS = 50


class _InterleaveController:
    """Per-repetition rendezvous: first wirer suspends until the second wires."""

    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        with getattr(self, "lock", threading.Lock()):
            self.calls = 0
            self.first_wired = threading.Event()
            self.second_wired = threading.Event()


def _install_interleaving(monkeypatch, controller):
    original = ruamel_main.YAML.get_constructor_parser

    def wired(self, stream):
        result = original(self, stream)
        with controller.lock:
            controller.calls += 1
            order = controller.calls
        if order == 1:
            controller.first_wired.set()
            # Suspended mid-.load(): stream is wired, data not yet read.
            controller.second_wired.wait(timeout=5.0)
        elif order == 2:
            controller.second_wired.set()
        return result

    monkeypatch.setattr(ruamel_main.YAML, "get_constructor_parser", wired)


def _parse_pair_interleaved(controller):
    """Parse both fixtures on two threads under the forced interleaving."""
    controller.reset()
    results = {}

    def parse(key, text):
        try:
            results[key] = HugoParser()._parse_yaml_content(text)
        except Exception as error:  # _parse_yaml_content normally swallows; belt and braces
            results[key] = error

    thread_one = threading.Thread(target=parse, args=("one", FIXTURE_ALPHA))
    thread_two = threading.Thread(target=parse, args=("two", FIXTURE_BETA))
    thread_one.start()
    assert controller.first_wired.wait(timeout=5.0), "thread 1 never reached .load()"
    thread_two.start()
    thread_one.join(timeout=10.0)
    thread_two.join(timeout=10.0)
    assert not thread_one.is_alive() and not thread_two.is_alive(), "deadlocked parse"
    return results.get("one"), results.get("two")


def test_concurrent_frontmatter_parses_do_not_cross_contaminate(monkeypatch):
    controller = _InterleaveController()
    _install_interleaving(monkeypatch, controller)

    for rep in range(_REPS):
        result_one, result_two = _parse_pair_interleaved(controller)
        assert isinstance(result_one, dict) and result_one.get("title") == (
            "Alpha document about spreadsheets"
        ), f"rep {rep}: thread 1 frontmatter corrupted or lost: {result_one!r}"
        assert isinstance(result_two, dict) and result_two.get("title") == (
            "Beta document about presentations"
        ), f"rep {rep}: thread 2 frontmatter corrupted or lost: {result_two!r}"


def test_engine_parser_is_per_thread():
    """engine.parser lazily yields a distinct HugoParser per thread (TC-APT-043)."""
    from src.translation_engine.engine import TranslationEngine

    engine = TranslationEngine.__new__(TranslationEngine)
    main_parser = engine.parser
    assert engine.parser is main_parser, "parser must be stable within one thread"

    seen = {}
    thread = threading.Thread(target=lambda: seen.update(other=engine.parser))
    thread.start()
    thread.join(timeout=5.0)
    assert seen["other"] is not main_parser
    assert type(seen["other"]) is type(main_parser)


def test_engine_parser_assignment_pins_current_thread_and_types_others():
    from src.translation_engine.engine import TranslationEngine

    engine = TranslationEngine.__new__(TranslationEngine)
    custom = HugoParser(enable_tables=False)
    engine.parser = custom
    assert engine.parser is custom, "explicit assignment must win for the assigning thread"

    seen = {}
    thread = threading.Thread(target=lambda: seen.update(other=engine.parser))
    thread.start()
    thread.join(timeout=5.0)
    assert seen["other"] is not custom
    assert isinstance(seen["other"], HugoParser)


def test_unforced_concurrent_parses_are_stable():
    """Timing-only variant: no injected pause, many concurrent parse pairs."""
    for rep in range(_REPS):
        results = {}

        def parse(key, text):
            try:
                results[key] = HugoParser()._parse_yaml_content(text)
            except Exception as error:
                results[key] = error

        barrier = threading.Barrier(2)

        def synced(key, text):
            barrier.wait(timeout=5.0)
            parse(key, text)

        thread_one = threading.Thread(target=synced, args=("one", FIXTURE_ALPHA))
        thread_two = threading.Thread(target=synced, args=("two", FIXTURE_BETA))
        thread_one.start()
        thread_two.start()
        thread_one.join(timeout=10.0)
        thread_two.join(timeout=10.0)
        one, two = results.get("one"), results.get("two")
        assert isinstance(one, dict) and one.get("weight") == 10, f"rep {rep}: {one!r}"
        assert isinstance(two, dict) and two.get("weight") == 20, f"rep {rep}: {two!r}"


# ---------------------------------------------------------------------------
# Test B (plan §11, TC-APT-043): two real fixture files translated
# concurrently end-to-end through one shared TranslationEngine — real parser,
# extractor, and reconstructor; stubbed model backend — synchronized with a
# threading.Barrier(2). No output may contain the other file's content, and
# no output may lose its frontmatter (the historical corruption shape).
# ---------------------------------------------------------------------------

DOC_ALPHA = """---
title: "Alpha spreadsheets guide"
description: "Alpha covers workbook management in Go"
weight: 10
---

# Alpha heading

Alpha paragraph about workbook cells and styling in a spreadsheet library.

Alpha second paragraph mentioning charts and pivot tables for reports.
"""

DOC_BETA = """---
title: "Beta presentations guide"
description: "Beta covers slide rendering in Java"
weight: 20
---

# Beta heading

Beta paragraph about slide masters and layout rendering in a deck library.

Beta second paragraph mentioning transitions and speaker notes for talks.
"""


class _MarkerBackend:
    """Deterministic, thread-safe stub: prefixes each text with a marker."""

    def __init__(self, tag=None):
        self.tag = tag

    def translate(self, texts, source_lang, target_lang):
        return [f"[{self.tag or target_lang.upper()}]{t}" for t in texts]

    def translate_with_token_counts(self, texts, source_lang, target_lang):
        translations = self.translate(texts, source_lang, target_lang)
        return translations, len(texts), len(translations)


def _build_engine(tmp_path):
    from src.model_runtime import ModelLoader
    from src.tm import TranslationMemory
    from src.tm.models import LookupResult
    from src.translation_engine import TranslationEngine
    from src.utils.config_loader import ConfigService

    output_dir = tmp_path / "output"
    output_dir.mkdir(exist_ok=True)

    body_rules = Mock()
    body_rules.translate_markdown = True
    body_rules.preserve_blocks = []
    body_rules.preserve_patterns = []
    body_rules.placeholder_syntax = []
    body_rules.use_ast_body_reconstruction = True
    body_rules.allow_legacy_reconstruction = False
    body_rules.sort_segments_by_length = False
    body_rules.ast_segmentation_strategy = "sentence_only"
    body_rules.ast_batch_size = 32

    profile = Mock()
    profile.site_id = "test.site"
    profile.default_source_lang = "en"
    profile.target_langs = ["es"]
    profile.body = body_rules
    profile.frontmatter = {}
    profile.tm_prefs = None
    profile.output_dir = str(output_dir)
    profile.default_model = None
    output_layout = Mock()
    output_layout.per_language_folders = False
    output_layout.output_dir = str(output_dir)
    output_layout.pattern = None
    profile.output_layout = output_layout

    config = Mock(spec=ConfigService)
    config.get_config = Mock(return_value={})
    config.get_site_profile = Mock(return_value=profile)
    config.global_config = Mock()
    config.global_config.tm_data_dir = str(tmp_path / "tm")
    config.global_config.model_defaults = None

    tm = Mock(spec=TranslationMemory)
    tm.lookup = Mock(return_value=LookupResult(hit=False))
    tm.batch_lookup = Mock(
        side_effect=lambda requests, **kwargs: [LookupResult(hit=False) for _ in requests]
    )
    tm.store = Mock()
    tm.set_override_mode = Mock()

    loader = Mock(spec=ModelLoader)
    loader.load_model = Mock(return_value=_MarkerBackend())
    loader.get_tokenizer_for_counting = Mock(return_value=None)
    loader.check_and_clear_cache = Mock(return_value=False)
    loader.clear_cache_after_file = Mock()

    engine = TranslationEngine(
        config_service=config,
        tm=tm,
        model_loader=loader,
        enable_telemetry=False,
        enable_validation=False,
    )
    return engine, output_dir


def test_concurrent_translate_file_no_cross_contamination(tmp_path):
    engine, output_dir = _build_engine(tmp_path)
    source_dir = tmp_path / "source"
    source_dir.mkdir(exist_ok=True)
    alpha_path = source_dir / "alpha.md"
    beta_path = source_dir / "beta.md"
    alpha_path.write_text(DOC_ALPHA, encoding="utf-8", newline="\n")
    beta_path.write_text(DOC_BETA, encoding="utf-8", newline="\n")

    reps = 25
    for rep in range(reps):
        barrier = threading.Barrier(2)
        outcomes = {}

        def translate(key, path):
            try:
                barrier.wait(timeout=10.0)
                outcomes[key] = engine.translate_file(
                    site_id="test.site", file_path=path, target_langs=["es"]
                )
            except Exception as error:
                outcomes[key] = error

        thread_one = threading.Thread(target=translate, args=("alpha", alpha_path))
        thread_two = threading.Thread(target=translate, args=("beta", beta_path))
        thread_one.start()
        thread_two.start()
        thread_one.join(timeout=60.0)
        thread_two.join(timeout=60.0)
        assert not thread_one.is_alive() and not thread_two.is_alive(), f"rep {rep}: hung"

        for key in ("alpha", "beta"):
            outcome = outcomes.get(key)
            assert not isinstance(outcome, Exception), f"rep {rep}: {key} raised {outcome!r}"
            assert getattr(outcome, "success", False), f"rep {rep}: {key} failed: {outcome!r}"

        alpha_out = (output_dir / "es" / "alpha.md").read_text(encoding="utf-8")
        beta_out = (output_dir / "es" / "beta.md").read_text(encoding="utf-8")

        assert "Alpha" in alpha_out and "Beta" not in alpha_out, (
            f"rep {rep}: alpha output cross-contaminated"
        )
        assert "Beta" in beta_out and "Alpha" not in beta_out, (
            f"rep {rep}: beta output cross-contaminated"
        )
        # The historical corruption blanked frontmatter entirely.
        assert alpha_out.startswith("---") and "Alpha spreadsheets guide" in alpha_out, (
            f"rep {rep}: alpha frontmatter lost or corrupted"
        )
        assert beta_out.startswith("---") and "Beta presentations guide" in beta_out, (
            f"rep {rep}: beta frontmatter lost or corrupted"
        )


# ---------------------------------------------------------------------------
# TC-APT-044: the generation lock lives on the backend instance, not
# engine-wide in campaign_runner. GPU backends must still serialize their
# translate path (shared tokenizer src_lang state + CUDA generation + last_*
# counters); the LLM backend must have no such lock; campaign_runner's old
# process-wide _model_execution_lock must stay deleted.
# ---------------------------------------------------------------------------


def _assert_translate_serializes(backend, impl_attr, call):
    import time as _time

    overlap = {"current": 0, "max": 0}
    overlap_lock = threading.Lock()
    barrier = threading.Barrier(2)

    def probe(*args, **kwargs):
        with overlap_lock:
            overlap["current"] += 1
            overlap["max"] = max(overlap["max"], overlap["current"])
        _time.sleep(0.05)
        with overlap_lock:
            overlap["current"] -= 1
        return (["x"], 1, 1)

    setattr(backend, impl_attr, probe)

    def worker():
        barrier.wait(timeout=5.0)
        call(backend)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10.0)
    assert overlap["max"] == 1, (
        f"generation ran {overlap['max']}-way concurrent; backend lock is broken"
    )


def test_huggingface_backend_translate_serializes_on_instance():
    from src.model_runtime.loader import HuggingFaceBackend

    backend = HuggingFaceBackend(Mock(), "cpu")
    _assert_translate_serializes(
        backend,
        "_translate_with_token_counts_impl",
        lambda b: b.translate_with_token_counts(["x"], "en", "es"),
    )


def test_ctranslate2_backend_translate_serializes_on_instance():
    from src.model_runtime.loader import CTranslate2Backend

    backend = CTranslate2Backend(Mock(), "cpu")
    _assert_translate_serializes(
        backend, "_translate_impl", lambda b: b.translate(["x"], "en", "es")
    )


def test_llm_backend_has_no_generation_lock():
    import inspect

    import src.model_runtime.llm_backend as llm_module

    assert "_generation_lock" not in inspect.getsource(llm_module), (
        "LLMModelBackend is pure I/O and must not serialize (TC-APT-044)"
    )


def test_campaign_runner_engine_wide_lock_stays_deleted():
    import inspect

    import src.workers.campaign_runner as campaign_runner_module

    source = inspect.getsource(campaign_runner_module)
    assert "self._model_execution_lock" not in source, (
        "the engine-wide translate_file lock must not come back (TC-APT-044); "
        "GPU serialization lives on the backend instances"
    )


# ---------------------------------------------------------------------------
# Test C (plan §11, TC-APT-045): the campaign model pin is call-scoped.
# Two concurrent translate_file calls with different model_id values must each
# resolve their OWN backend end-to-end — the former engine.model_id_override
# attribute mutation could bleed one job's pin into the other.
# ---------------------------------------------------------------------------


def test_concurrent_model_id_no_cross_job_bleed(tmp_path):
    engine, output_dir = _build_engine(tmp_path)
    engine.model_loader.load_model = Mock(
        side_effect=lambda model_id: _MarkerBackend(tag=model_id)
    )
    source_dir = tmp_path / "source"
    source_dir.mkdir(exist_ok=True)
    alpha_path = source_dir / "alpha.md"
    beta_path = source_dir / "beta.md"
    alpha_path.write_text(DOC_ALPHA, encoding="utf-8", newline="\n")
    beta_path.write_text(DOC_BETA, encoding="utf-8", newline="\n")

    for rep in range(10):
        barrier = threading.Barrier(2)
        outcomes = {}

        def translate(key, path, model_id):
            try:
                barrier.wait(timeout=10.0)
                outcomes[key] = engine.translate_file(
                    site_id="test.site",
                    file_path=path,
                    target_langs=["es"],
                    model_id=model_id,
                )
            except Exception as error:
                outcomes[key] = error

        threads = [
            threading.Thread(target=translate, args=("alpha", alpha_path, "model-alpha")),
            threading.Thread(target=translate, args=("beta", beta_path, "model-beta")),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60.0)

        for key in ("alpha", "beta"):
            outcome = outcomes.get(key)
            assert not isinstance(outcome, Exception), f"rep {rep}: {key} raised {outcome!r}"
            assert getattr(outcome, "success", False), f"rep {rep}: {key} failed: {outcome!r}"

        alpha_out = (output_dir / "es" / "alpha.md").read_text(encoding="utf-8")
        beta_out = (output_dir / "es" / "beta.md").read_text(encoding="utf-8")
        assert "[model-alpha]" in alpha_out and "[model-beta]" not in alpha_out, (
            f"rep {rep}: alpha translated with the wrong job's model pin"
        )
        assert "[model-beta]" in beta_out and "[model-alpha]" not in beta_out, (
            f"rep {rep}: beta translated with the wrong job's model pin"
        )


def test_campaign_runner_no_attribute_model_pin_remains():
    import inspect

    import src.workers.campaign_runner as campaign_runner_module

    source = inspect.getsource(campaign_runner_module)
    assert "self.engine.model_id_override" not in source, (
        "campaign jobs must pin the model via translate_file(model_id=...) "
        "(TC-APT-045), never by mutating shared engine state"
    )
