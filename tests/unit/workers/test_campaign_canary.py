from pathlib import Path

from scripts.campaign.build_stratified_canary_manifest import (
    build_canary,
    select_canary_sources,
)


def _source(path: str, site: str = "docs.aspose.org") -> dict:
    return {
        "site_id": site,
        "family": "words",
        "platform": "net",
        "source_path": path,
        "outputs": {"es": f"out/{Path(path).stem}.md"},
    }


def test_canary_selects_index_and_highest_structural_risk(tmp_path):
    root = tmp_path
    paths = [
        "content/docs.aspose.org/en/words/net/_index.md",
        "content/docs.aspose.org/en/words/net/plain.md",
        "content/docs.aspose.org/en/words/net/risky.md",
    ]
    for relative in paths:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("plain", encoding="utf-8")
    (root / paths[2]).write_text(
        "```python\nprint('x')\n```\n| a | b |\n|---|---|\n",
        encoding="utf-8",
    )
    payload = {
        "content_repo": str(root),
        "sources": [_source(path) for path in paths],
    }

    selected = select_canary_sources(payload)

    assert [Path(item["source_path"]).name for item in selected] == [
        "_index.md",
        "risky.md",
    ]


def test_canary_preserves_campaign_identity_and_recounts(tmp_path):
    index = "content/docs.aspose.org/en/words/net/_index.md"
    path = tmp_path / index
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("index", encoding="utf-8")
    payload = {
        "campaign_id": "pilot",
        "content_repo": str(tmp_path),
        "expected_source_count": 99,
        "expected_output_count": 99,
        "sources": [_source(index)],
    }

    canary = build_canary(payload)

    assert canary["campaign_id"] == "pilot"
    assert canary["expected_source_count"] == 1
    assert canary["expected_output_count"] == 1
    assert canary["campaign_phase"] == "stratified-canary"
