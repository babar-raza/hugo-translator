"""TC-APT-023: the rerun-determinism contract, its measurement, and its drift check.

Plan section 5.1 item 5: nothing stated what a rerun is supposed to produce, so no consistency
regression could be detected. The contract is now explicit and MEASURED -- byte-identical and
semantic-equivalence rates are recorded as ongoing metrics rather than assumed to be 100%,
because hosted-LLM nondeterminism at temperature 0 is real and outside this system's control.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.workers import determinism as det

FPS = {
    "profile_fingerprint": "p" * 64,
    "protection_fingerprint": "q" * 64,
    "model_identity_sha256": "m" * 64,
}


def test_identical_output_is_byte_identical():
    result = det.classify_pair("k", "Die Datei wird geladen.", "Die Datei wird geladen.")
    assert result.outcome is det.Outcome.BYTE_IDENTICAL and result.similarity == 1.0
    assert result.first_sha256 == result.second_sha256


def test_small_wording_change_with_passing_gates_is_semantically_equivalent():
    a = "Die Datei wird mit der Workbook-Klasse geladen und anschliessend gespeichert."
    b = "Die Datei wird mit der Workbook-Klasse geladen und danach gespeichert."
    result = det.classify_pair("k", a, b, gates_passed_both=True, similarity_threshold=0.85)
    assert result.outcome is det.Outcome.SEMANTICALLY_EQUIVALENT
    assert 0.85 <= result.similarity < 1.0


def test_same_text_but_failing_gates_is_divergent():
    a = "Die Datei wird geladen."
    b = "Die Datei wird geoeffnet."
    result = det.classify_pair("k", a, b, gates_passed_both=False, similarity_threshold=0.5)
    assert result.outcome is det.Outcome.DIVERGENT  # gate failure alone breaks equivalence


def test_large_rewrite_is_divergent():
    result = det.classify_pair(
        "k", "Die Datei wird geladen.", "Ein vollkommen anderer Satz ueber etwas anderes."
    )
    assert result.outcome is det.Outcome.DIVERGENT and result.similarity < 0.95


def test_rates_are_measured_not_assumed():
    pairs = [
        ("a", "same", "same"),
        ("b", "the file is loaded and saved", "the file is loaded and stored"),
        ("c", "one thing", "something entirely different here"),
    ]
    report = det.measure(pairs, fingerprints=FPS, similarity_threshold=0.5)
    assert report.byte_identical_rate == 1 / 3
    assert report.semantic_equivalence_rate == 2 / 3  # byte-identical + near-duplicate
    assert report.divergent_rate == 1 / 3
    payload = report.as_dict()
    assert payload["taskcard"] == "TC-APT-023" and payload["pairs"] == 3
    assert payload["fingerprints"] == FPS and payload["similarity_threshold"] == 0.5
    assert len(payload["divergent"]) == 1 and payload["divergent"][0]["key"] == "c"
    assert payload["similarity_min"] is not None


def test_empty_measurement_has_zero_rates():
    report = det.measure([], fingerprints=FPS)
    assert report.byte_identical_rate == 0.0 and report.semantic_equivalence_rate == 0.0
    assert report.as_dict()["similarity_median"] is None


def test_fingerprints_precondition():
    ok, changed = det.fingerprints_unchanged(FPS, dict(FPS))
    assert ok and changed == []
    ok, changed = det.fingerprints_unchanged(FPS, {**FPS, "protection_fingerprint": "z" * 64})
    assert not ok and changed == ["protection_fingerprint"]


def test_baseline_write_and_drift_detection(tmp_path: Path):
    baseline_path = tmp_path / "baseline.json"
    good = det.measure([("a", "x", "x"), ("b", "y", "y")], fingerprints=FPS)
    det.write_baseline(good, baseline_path)
    assert json.loads(baseline_path.read_text(encoding="utf-8"))["semantic_equivalence_rate"] == 1.0

    same = det.compare_with_baseline(good, baseline_path)
    assert same["drift"] is False and same["delta"] == 0.0

    degraded = det.measure(
        [("a", "x", "x"), ("b", "y", "completely different output text")], fingerprints=FPS
    )
    drifted = det.compare_with_baseline(degraded, baseline_path)
    assert drifted["drift"] is True and drifted["delta"] == -0.5

    # a changed fingerprint legitimately changes output -> re-baseline, not a regression
    rebaseline = det.measure(
        [("a", "x", "z")], fingerprints={**FPS, "profile_fingerprint": "n" * 64}
    )
    verdict = det.compare_with_baseline(rebaseline, baseline_path)
    assert verdict["drift"] is False and verdict["changed_fingerprints"] == ["profile_fingerprint"]
    assert "re-baseline" in verdict["note"]

    assert det.compare_with_baseline(good, tmp_path / "missing.json")["baseline"] is None


def test_translate_twice_uses_one_backend_twice():
    class Backend:
        def __init__(self):
            self.calls = 0

        def translate_with_token_counts(self, texts, src, tgt):
            self.calls += 1
            suffix = "" if self.calls == 1 else "."  # second run differs slightly
            return [f"[{tgt}] {t}{suffix}" for t in texts], 1, 1

    backend = Backend()
    triples = det.translate_twice(backend, ["one", "two"], "en", "de")
    assert backend.calls == 2 and [k for k, _, _ in triples] == ["de:0", "de:1"]
    report = det.measure(triples, fingerprints=FPS, similarity_threshold=0.5)
    assert report.byte_identical_rate == 0.0 and report.semantic_equivalence_rate == 1.0
