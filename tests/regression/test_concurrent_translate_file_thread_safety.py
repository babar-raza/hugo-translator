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
