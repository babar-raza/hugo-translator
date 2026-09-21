"""TC-APT-046 step 2: the canary verifier must actually detect what it claims to.

A verification script that only ever returns "passed" is worse than no script, so each
check here is driven by a fixture carrying exactly the defect it exists to find, plus a
clean control. The clean control matters: it was run against the real serial
gate5-pdf-foss-cpp-r2 campaign and reported zero violations across 10 cells, which is
what makes a violation in a concurrent run attributable to concurrency.
"""

import hashlib
import json
from pathlib import Path

from scripts.campaign.verify_concurrency_canary import (
    check_content_bleed,
    check_frontmatter,
    check_model_routing,
    check_receipt_integrity,
    split_frontmatter,
)

RETRY_POLICY = {"primary_model": "professionalize_llm", "llm_model": "m2m100_418m"}


def _page(title: str, body: str) -> str:
    return f"---\ntitle: {title}\ndescription: {title} description\n---\n{body}\n"


def _write(content_repo: Path, rel: str, text: str) -> None:
    path = content_repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _receipt(rel: str, locale: str, model: str = "professionalize_llm", source: str = "src/a.md"):
    return {
        "output_path": rel,
        "target_lang": locale,
        "source_path": source,
        "model_fingerprint": model,
    }


def _clean_corpus(content_repo: Path) -> list[dict]:
    receipts = []
    for locale, body in (("de", "Deutscher Text"), ("es", "Texto en espanol"), ("fr", "Texte")):
        rel = f"content/a/index.{locale}.md"
        _write(content_repo, rel, _page(f"Titel {locale}", body))
        receipts.append(_receipt(rel, locale))
    return receipts


def test_clean_corpus_reports_no_violations(tmp_path):
    receipts = _clean_corpus(tmp_path)

    assert check_model_routing(receipts, RETRY_POLICY) == []
    assert check_frontmatter(receipts, tmp_path) == []
    assert check_content_bleed(receipts, tmp_path) == []


def test_model_outside_manifest_routing_is_flagged(tmp_path):
    receipts = _clean_corpus(tmp_path)
    receipts[1]["model_fingerprint"] = "some_other_model"

    problems = check_model_routing(receipts, RETRY_POLICY)

    assert len(problems) == 1
    assert "some_other_model" in problems[0]


def test_escalation_model_is_accepted_routing(tmp_path):
    """m2m100_418m is the declared retry model, not a routing violation."""
    receipts = _clean_corpus(tmp_path)
    receipts[0]["model_fingerprint"] = "m2m100_418m"

    assert check_model_routing(receipts, RETRY_POLICY) == []


def test_empty_frontmatter_is_flagged(tmp_path):
    receipts = _clean_corpus(tmp_path)
    _write(tmp_path, receipts[0]["output_path"], "Body with no frontmatter at all\n")

    problems = check_frontmatter(receipts, tmp_path)

    assert len(problems) == 1
    assert "empty or absent frontmatter" in problems[0]


def test_blank_required_key_is_flagged(tmp_path):
    receipts = _clean_corpus(tmp_path)
    _write(tmp_path, receipts[0]["output_path"], "---\ntitle: ''\ndescription: x\n---\nbody\n")

    problems = check_frontmatter(receipts, tmp_path)

    assert len(problems) == 1
    assert "'title' is empty" in problems[0]


def test_missing_receipted_output_is_flagged(tmp_path):
    receipts = _clean_corpus(tmp_path)
    (tmp_path / receipts[2]["output_path"]).unlink()

    problems = check_frontmatter(receipts, tmp_path)

    assert len(problems) == 1
    assert "missing on disk" in problems[0]


def test_cross_language_bleed_is_flagged(tmp_path):
    """One job's body landing under another locale's name."""
    receipts = _clean_corpus(tmp_path)
    bled = (tmp_path / receipts[0]["output_path"]).read_text(encoding="utf-8")
    _, body = split_frontmatter(bled)
    _write(tmp_path, receipts[1]["output_path"], _page("Titel es", body.strip()))

    problems = check_content_bleed(receipts, tmp_path)

    assert len(problems) == 1
    assert "cross-language content bleed" in problems[0]


def test_cross_file_bleed_is_flagged(tmp_path):
    """Same locale, two different sources, one body: the cross-file form."""
    receipts = _clean_corpus(tmp_path)
    _write(tmp_path, "content/b/index.de.md", _page("Titel b", "Deutscher Text"))
    receipts.append(_receipt("content/b/index.de.md", "de", source="src/b.md"))

    problems = check_content_bleed(receipts, tmp_path)

    assert len(problems) == 1
    assert "cross-file content bleed" in problems[0]


def test_receipt_integrity_catches_a_post_acceptance_overwrite(tmp_path):
    receipts = _clean_corpus(tmp_path)
    for receipt in receipts:
        path = tmp_path / receipt["output_path"]
        receipt["output_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()

    assert check_receipt_integrity(receipts, tmp_path) == []

    overwritten = tmp_path / receipts[1]["output_path"]
    overwritten.write_text(_page("Titel es", "andere Bytes"), encoding="utf-8")

    problems = check_receipt_integrity(receipts, tmp_path)

    assert len(problems) == 1
    assert "overwritten after acceptance" in problems[0]


def test_split_frontmatter_handles_a_page_without_any():
    raw, body = split_frontmatter("no frontmatter here")

    assert raw == ""
    assert body == "no frontmatter here"


def test_report_shape_is_json_serialisable(tmp_path):
    """The canary's verdict is recorded as JSON evidence, so it must serialise."""
    receipts = _clean_corpus(tmp_path)
    report = {
        "checks": {
            "model_routing": check_model_routing(receipts, RETRY_POLICY),
            "empty_frontmatter": check_frontmatter(receipts, tmp_path),
            "content_bleed": check_content_bleed(receipts, tmp_path),
        }
    }

    assert json.loads(json.dumps(report))["checks"]["model_routing"] == []
