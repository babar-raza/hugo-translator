"""TC-APT-024: wave ordering is inspectable and matches the documented scoring rationale."""

from __future__ import annotations

from pathlib import Path

from src.workers import wave_ordering as wo
from src.workers.work_ledger import WorkLedger

SHA = "a" * 64


def _cell(**over):
    base = dict(
        source_chars=1000,
        target_lang="de",
        missing_lang_count=5,
        tm_fuzzy_hit_ratio=0.0,
        char_bounds=(100, 10000),
        max_missing=25,
    )
    base.update(over)
    return wo.score_cell(**base)


def test_smaller_pages_score_lower():
    assert _cell(source_chars=200).score < _cell(source_chars=9000).score


def test_lighter_language_tiers_score_lower():
    tiers = [_cell(target_lang=lang).score for lang in ("de", "ru", "ar", "ja")]
    assert tiers == sorted(tiers)
    assert wo.LANGUAGE_COST_TIER["de"] == 0 and wo.LANGUAGE_COST_TIER["ja"] == 3
    assert _cell(target_lang="xx").language_cost_tier == wo.MAX_TIER  # unknown -> heaviest


def test_fewer_missing_languages_scores_lower():
    assert _cell(missing_lang_count=2).score < _cell(missing_lang_count=25).score


def test_tm_leverage_subtracts_from_the_score():
    plain = _cell(tm_fuzzy_hit_ratio=0.0)
    templated = _cell(tm_fuzzy_hit_ratio=1.0)
    assert templated.score == plain.score - 1.0  # w4 = 1.0


def test_components_are_recorded_for_inspection():
    d = _cell(
        source_chars=5050, target_lang="ar", missing_lang_count=13, tm_fuzzy_hit_ratio=0.25
    ).as_dict()
    assert set(d) == {
        "source_chars",
        "size_norm",
        "language_cost_tier",
        "tier_norm",
        "missing_lang_count",
        "missing_norm",
        "tm_fuzzy_hit_ratio",
        "score",
    }
    assert d["language_cost_tier"] == 2 and 0.0 <= d["size_norm"] <= 1.0
    # the score IS the documented formula (exact on the unrounded components; the dict
    # rounds each term to 4 dp for readability, hence the looser tolerance there)
    c = _cell(source_chars=5050, target_lang="ar", missing_lang_count=13, tm_fuzzy_hit_ratio=0.25)
    assert (
        abs((c.size_norm + c.tier_norm + c.missing_norm - c.tm_fuzzy_hit_ratio) - c.score) < 1e-12
    )
    recomputed = d["size_norm"] + d["tier_norm"] + d["missing_norm"] - d["tm_fuzzy_hit_ratio"]
    assert abs(recomputed - d["score"]) < 1e-3


def test_tm_fuzzy_hit_ratio_detects_shared_boilerplate():
    shared = "This page documents the supported formats for the library and how to install it via the package manager."
    unique = "A completely different paragraph about an unrelated subject that appears exactly once in the corpus."
    ratios = wo.tm_fuzzy_hit_ratios(
        {
            "a.md": f"---\ntitle: a\n---\n{shared}\n\n{unique}\n",
            "b.md": f"---\ntitle: b\n---\n{shared}\n",
            "c.md": f"---\ntitle: c\n---\n{unique[::-1]}\n",
        }
    )
    assert ratios["a.md"] == 0.5 and ratios["b.md"] == 1.0 and ratios["c.md"] == 0.0


def test_assign_waves_is_quantile_and_ordered():
    scores = [float(i) for i in range(100)]
    waves = wo.assign_waves(scores, wave_count=10)
    assert waves[0] == 0 and waves[-1] == 9
    assert waves == sorted(waves)  # ascending score -> ascending wave
    assert len(set(waves)) == 10
    assert wo.assign_waves([], 10) == []


def test_compute_waves_writes_and_only_touches_actionable_cells(tmp_path: Path):
    repo = tmp_path / "repo"
    small = repo / "content/docs.aspose.org/en/a.md"
    big = repo / "content/docs.aspose.org/en/b.md"
    small.parent.mkdir(parents=True)
    small.write_text("---\ntitle: a\n---\nshort page\n", encoding="utf-8")
    big.write_text("---\ntitle: b\n---\n" + ("long paragraph text " * 400), encoding="utf-8")
    ledger = WorkLedger(tmp_path / "ledger.sqlite3")
    base = dict(
        site_id="docs.aspose.org",
        family="",
        platform="",
        source_sha256=SHA,
        profile_fingerprint="p" * 64,
        protection_fingerprint="q" * 64,
        target_exists=False,
    )
    for lang in ("de", "ja"):
        ledger.upsert(
            {
                **base,
                "source_path": "content/docs.aspose.org/en/a.md",
                "target_lang": lang,
                "expected_output_path": f"content/docs.aspose.org/{lang}/a.md",
                "eligibility_state": "MISSING_TRANSLATION",
                "eligibility_reason_code": "target_absent",
            }
        )
        ledger.upsert(
            {
                **base,
                "source_path": "content/docs.aspose.org/en/b.md",
                "target_lang": lang,
                "expected_output_path": f"content/docs.aspose.org/{lang}/b.md",
                "eligibility_state": "MISSING_TRANSLATION",
                "eligibility_reason_code": "target_absent",
            }
        )
    ledger.upsert(
        {
            **base,
            "source_path": "content/docs.aspose.org/en/a.md",
            "target_lang": "bg",
            "expected_output_path": "content/docs.aspose.org/bg/a.md",
            "eligibility_state": "EXCLUDED_BY_PROFILE",
            "eligibility_reason_code": "locale_not_in_profile_allowlist",
        }
    )
    try:
        report = wo.compute_waves(ledger, repo, wave_count=4)
        assert report["cells"] == 4 and report["updated"] >= 1  # the excluded cell is not scored
        rows = {(r["source_path"][-4:], r["target_lang"]): r["wave"] for r in ledger.query()}
        assert rows[("a.md", "de")] <= rows[("b.md", "de")]  # small page first
        assert rows[("a.md", "de")] <= rows[("a.md", "ja")]  # tier-0 language first
        assert rows[("a.md", "bg")] == 0  # untouched default
        assert "score = w1*normalize(source_chars)" in report["formula"]
        assert report["sample_extremes"] and "size_norm" in report["sample_extremes"][0]
        dry = wo.compute_waves(ledger, repo, wave_count=4, dry_run=True)
        assert dry["updated"] == 0  # idempotent
    finally:
        ledger.close()
