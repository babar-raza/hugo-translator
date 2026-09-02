"""TC-APT-006: provider comparison scoring/aggregation (offline, fake translate functions)."""

from __future__ import annotations

import scripts.campaign.run_provider_comparison as rpc

SEGS = [
    {"id": "a", "text_en": "Aspose.Cells reads `Workbook` files.", "domain": "api_heavy"},
    {"id": "b", "text_en": "Convert PDF to DOCX in C#", "domain": "short_metadata"},
    {"id": "c", "text_en": "Use {{< shortcode >}} here.", "domain": "placeholder_heavy"},
]


def test_identifier_extraction_and_pair_scoring():
    ids = rpc.identifiers(SEGS[0]["text_en"])
    assert "Aspose.Cells" in ids and "`Workbook`" in ids
    good = rpc.score_pair(SEGS[0]["text_en"], "Aspose.Cells liest `Workbook`-Dateien.", "de")
    assert (
        good["identifiers_preserved"] is True
        and good["same_as_source"] is False
        and good["empty"] is False
    )
    bad = rpc.score_pair(SEGS[0]["text_en"], "Aspose.Zellen liest Arbeitsmappe-Dateien.", "de")
    assert bad["identifiers_preserved"] is False
    same = rpc.score_pair(SEGS[1]["text_en"], SEGS[1]["text_en"], "de")
    assert same["same_as_source"] is True
    assert rpc.score_pair("x", "", "de")["empty"] is True


def test_run_model_aggregates_and_records_errors():
    comp = rpc.Comparison(SEGS, ("de", "fr"))

    def good_translate(texts, lang):
        return [f"[{lang}] {t}" for t in texts], 10 * len(texts), 12 * len(texts)

    def flaky_translate(texts, lang):
        if lang == "fr":
            raise TimeoutError("down")
        return [t for t in texts], 0, 0  # same-as-source passthrough

    comp.run_model("good", good_translate, batch_size=2, concurrency=2)
    comp.run_model("flaky", flaky_translate, batch_size=8)
    report = comp.report()
    good = report["models"]["good"]["overall"]
    assert good["n"] == 6 and good["errors"] == 0 and good["same_as_source_rate"] == 0.0
    assert good["input_tokens"] == 60 and good["output_tokens"] == 72
    flaky = report["models"]["flaky"]
    assert flaky["overall"]["errors"] == 3  # the whole fr batch errored
    assert flaky["by_lang"]["de"]["same_as_source_rate"] == 1.0
    assert set(report["models"]["good"]["by_domain"]) == {
        "api_heavy",
        "short_metadata",
        "placeholder_heavy",
    }
    verdict = report["per_lang_verdict"]
    assert verdict["de"]["better"] == "good" and verdict["fr"]["better"] == "good"


def test_aggregate_handles_empty_and_no_identifiers():
    assert rpc.aggregate([]) == {"n": 0}
    cells = [
        {
            "empty": False,
            "same_as_source": False,
            "lang_match": True,
            "identifiers_total": 0,
            "identifiers_preserved": True,
            "length_ratio": 1.1,
            "seconds": 0.5,
        }
    ]
    agg = rpc.aggregate(cells)
    assert (
        agg["identifier_preservation_rate"] is None
        and agg["lang_match_rate"] == 1.0
        and agg["length_ratio_median"] == 1.1
    )


def test_detect_lang_alias_mapping(monkeypatch):
    import langdetect

    monkeypatch.setattr(langdetect, "detect", lambda text: "zh-cn")
    assert rpc.detect_lang("测试文本") == "zh"
    monkeypatch.setattr(
        langdetect, "detect", lambda text: (_ for _ in ()).throw(RuntimeError("no features"))
    )
    assert rpc.detect_lang("...") is None
