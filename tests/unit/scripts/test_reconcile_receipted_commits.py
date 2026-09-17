"""Unit tests for scripts/campaign/reconcile_receipted_commits.py.

Covers the governance fixes requested for aspose.org translation commits:
- exactly one Co-Authored-By trailer, defaulting to hugo-translator@aspose.org
- a `content(translation): {summary}` subject naming the affected pages/locales
- a group is committed as ONE batch as soon as it holds >= --min-batch-size
  receipts (default 5) -- never split into fixed-size chunks, never held
  back waiting for a larger batch once the minimum is met
- grouping stays by (subdomain, family, platform)
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from src.workers.campaign_manifest import CampaignManifest

from scripts.campaign.reconcile_receipted_commits import (
    build_commit_message,
    committed_batch_counts_by_group,
    main,
    manifest_output_index,
    summarize_batch,
    _page_label,
)


GROUP = ("blog.aspose.org", "pdf", "go")


def _row(source_path: str, target_lang: str) -> dict[str, Any]:
    return {"source_path": source_path, "target_lang": target_lang}


def test_page_label_uses_parent_directory_for_a_normal_page():
    assert _page_label("content/blog.aspose.org/pdf/go/go-pdf-create-merge-split/index.md", GROUP) == (
        "go-pdf-create-merge-split"
    )


def test_page_label_falls_back_to_index_for_a_bare_family_or_platform_index():
    assert _page_label("content/blog.aspose.org/pdf/go/_index.md", GROUP) == "_index"


def test_summarize_batch_lists_pages_and_locales_when_few():
    chunk = [
        _row("content/blog.aspose.org/pdf/go/go-pdf-create-merge-split/index.md", "fa"),
        _row("content/blog.aspose.org/pdf/go/go-pdf-create-merge-split/index.md", "de"),
        _row("content/blog.aspose.org/pdf/go/blog-pdf-go-overview/index.md", "nl"),
    ]
    summary = summarize_batch(GROUP, chunk)
    assert summary == "pdf/go — blog-pdf-go-overview, go-pdf-create-merge-split (de, fa, nl)"


def test_summarize_batch_truncates_to_counts_when_many():
    pages = [f"page-{i}" for i in range(6)]
    locales = [f"l{i}" for i in range(20)]
    # 20 rows cycling through only 6 distinct pages, so page and locale
    # cardinality can each cross their own truncation threshold independently.
    chunk = [
        _row(f"content/blog.aspose.org/pdf/go/{pages[i % len(pages)]}/index.md", locale)
        for i, locale in enumerate(locales)
    ]
    summary = summarize_batch(GROUP, chunk)
    assert summary == "pdf/go — 6 pages (20 locales)"


def test_build_commit_message_has_the_required_subject_and_skills_line_and_no_coauthor():
    chunk = [_row("content/blog.aspose.org/pdf/go/go-pdf-create-merge-split/index.md", "fa")]
    message = build_commit_message(GROUP, chunk)
    assert message.startswith("content(translation): pdf/go — go-pdf-create-merge-split (fa)\n\n")
    assert "Skills invoked: [S-76, S-HT-02]" in message
    # The single Co-Authored-By trailer is added by git_plumb_commit.py from
    # --co-author -- baking one into the message here would give it two,
    # which that tool explicitly refuses (CommitProvenanceError).
    assert "co-authored" not in message.lower()


def test_manifest_output_index_groups_by_the_sources_own_family_and_platform_fields(tmp_path):
    """A real regression: family names that collide with the locale-prefix
    shape ('words', 'cells', 'email' are all 5-letter alphabetic strings) used
    to get silently mis-grouped by a heuristic that re-derived family/platform
    from the output path. Found live 2026-09-17 on a real words/net receipt,
    which partitioned itself as family="net", platform="introducing-words-
    foss-net" instead of family="words", platform="net". The fix reads the
    authoritative family/platform already on the manifest source instead.
    """
    manifest_dict = {
        "schema_version": 1, "campaign_id": "x", "validation_policy": "zero-defect",
        "content_repo": str(tmp_path), "content_repo_sha": "a" * 40, "translator_repo_sha": "b" * 40,
        "config_fingerprint": "c" * 64, "model_fingerprints": {"model_registry": "e" * 64},
        "tm_fingerprint": "f" * 64, "knowledge_fingerprints": {}, "target_locales": ["ja"],
        "expected_source_count": 3, "expected_output_count": 3,
        "execution_policy": {"output_selection": "missing_only"},
        "retry_policy": {
            "primary_model": "m2m100_418m", "primary_attempts": 3,
            "llm_escalation_attempts": 2, "llm_model": "professionalize_llm",
        },
        "commit_policy": {"branch": "main", "max_outputs_per_commit": 250, "push": False},
        "sources": [
            {
                "site_id": "blog.aspose.org", "family": "words", "platform": "net",
                "source_path": "content/blog.aspose.org/words/net/introducing-words-foss-net/index.md",
                "source_sha256": "a" * 64, "wave": 1,
                "outputs": {"ja": "content/blog.aspose.org/words/net/introducing-words-foss-net/index.ja.md"},
            },
            {
                "site_id": "blog.aspose.org", "family": "cells", "platform": "net",
                "source_path": "content/blog.aspose.org/cells/net/spreadsheet-management-in-net/index.md",
                "source_sha256": "b" * 64, "wave": 1,
                "outputs": {"ja": "content/blog.aspose.org/cells/net/spreadsheet-management-in-net/index.ja.md"},
            },
            {
                "site_id": "blog.aspose.org", "family": "email", "platform": "python",
                "source_path": "content/blog.aspose.org/email/python/python-outlook-msg-create-read/index.md",
                "source_sha256": "c" * 64, "wave": 1,
                "outputs": {"ja": "content/blog.aspose.org/email/python/python-outlook-msg-create-read/index.ja.md"},
            },
        ],
    }
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(manifest_dict), encoding="utf-8")
    manifest = CampaignManifest.load(manifest_path)

    index = manifest_output_index(manifest)

    assert index["content/blog.aspose.org/words/net/introducing-words-foss-net/index.ja.md"] == (
        "blog.aspose.org", "words", "net"
    )
    assert index["content/blog.aspose.org/cells/net/spreadsheet-management-in-net/index.ja.md"] == (
        "blog.aspose.org", "cells", "net"
    )
    assert index["content/blog.aspose.org/email/python/python-outlook-msg-create-read/index.ja.md"] == (
        "blog.aspose.org", "email", "python"
    )


def test_committed_batch_counts_by_group_only_counts_committed_rows(tmp_path):
    path = tmp_path / "commit_batches.jsonl"
    rows = [
        {"status": "COMMITTED", "group": {"subdomain": "blog.aspose.org", "family": "pdf", "platform": "go"}},
        {"status": "COMMITTED", "group": {"subdomain": "blog.aspose.org", "family": "pdf", "platform": "go"}},
        {"status": "FAILED", "group": {"subdomain": "blog.aspose.org", "family": "pdf", "platform": "go"}},
        {"status": "COMMITTED", "group": {"subdomain": "blog.aspose.org", "family": "cells", "platform": "net"}},
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    counts = committed_batch_counts_by_group(path)
    assert counts[("blog.aspose.org", "pdf", "go")] == 2
    assert counts[("blog.aspose.org", "cells", "net")] == 1


def _init_content_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    (root / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=root, check=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=root, check=True)


def _write_output(content_repo: Path, rel_path: str, text: str) -> tuple[str, str]:
    path = content_repo / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    # newline="" so Windows doesn't translate \n -> \r\n and desync the bytes
    # on disk from the sha256 computed over the original string below.
    path.write_text(text, encoding="utf-8", newline="")
    return rel_path, hashlib.sha256(text.encode("utf-8")).hexdigest()


def _receipt(output_path: str, output_sha256: str, source_path: str, target_lang: str) -> dict[str, Any]:
    return {
        "output_path": output_path,
        "output_sha256": output_sha256,
        "source_path": source_path,
        "target_lang": target_lang,
        "gate_results": {"1": {"passed": True, "action": "verification", "error": None}},
        "receipt_sha256": hashlib.sha256(output_path.encode("utf-8")).hexdigest(),
    }


def test_main_commits_a_group_of_six_as_one_batch_and_holds_back_an_undersized_group(tmp_path):
    content_repo = tmp_path / "content_repo"
    content_repo.mkdir()
    _init_content_repo(content_repo)

    sources = []
    receipts = []
    outputs_a: dict[str, str] = {}
    for i, locale in enumerate(["cs", "de", "fa", "hi", "hu", "id"]):
        page = f"page-{i}"
        source_path = f"content/blog.aspose.org/pdf/go/{page}/index.md"
        rel_out, sha = _write_output(
            content_repo, f"content/blog.aspose.org/pdf/go/{page}/index.{locale}.md", f"body {i}\n"
        )
        outputs_a[locale] = rel_out
        sources.append({
            "site_id": "blog.aspose.org", "family": "pdf", "platform": "go",
            "source_path": source_path, "source_sha256": "a" * 64, "wave": 1,
            "outputs": {locale: rel_out},
        })
        receipts.append(_receipt(rel_out, sha, source_path, locale))

    outputs_b: dict[str, str] = {}
    for i, locale in enumerate(["it", "ja", "ko"]):
        page = f"other-{i}"
        source_path = f"content/blog.aspose.org/cells/net/{page}/index.md"
        rel_out, sha = _write_output(
            content_repo, f"content/blog.aspose.org/cells/net/{page}/index.{locale}.md", f"cells body {i}\n"
        )
        outputs_b[locale] = rel_out
        sources.append({
            "site_id": "blog.aspose.org", "family": "cells", "platform": "net",
            "source_path": source_path, "source_sha256": "b" * 64, "wave": 1,
            "outputs": {locale: rel_out},
        })
        receipts.append(_receipt(rel_out, sha, source_path, locale))

    manifest_dict = {
        "schema_version": 1,
        "campaign_id": "test-campaign",
        "validation_policy": "zero-defect",
        "content_repo": str(content_repo),
        "content_repo_sha": "a" * 40,
        "translator_repo_sha": "b" * 40,
        "config_fingerprint": "c" * 64,
        "model_fingerprints": {"model_registry": "e" * 64},
        "tm_fingerprint": "f" * 64,
        "knowledge_fingerprints": {},
        "target_locales": ["cs", "de", "fa", "hi", "hu", "id", "it", "ja", "ko"],
        "expected_source_count": len(sources),
        "expected_output_count": len(receipts),
        "execution_policy": {"output_selection": "missing_only"},
        "retry_policy": {
            "primary_model": "m2m100_418m", "primary_attempts": 3,
            "llm_escalation_attempts": 2, "llm_model": "professionalize_llm",
        },
        "commit_policy": {"branch": "main", "max_outputs_per_commit": 250, "push": False},
        "sources": sources,
    }
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(manifest_dict), encoding="utf-8")

    ledger_root = tmp_path / "ledger"
    campaign_dir = ledger_root / "test-campaign"
    campaign_dir.mkdir(parents=True)
    receipts_path = campaign_dir / "acceptance_receipts.jsonl"
    receipts_path.write_text(
        "\n".join(json.dumps(r) for r in receipts) + "\n", encoding="utf-8"
    )

    code = main([
        "--manifest", str(manifest_path),
        "--content-repo", str(content_repo),
        "--ledger-root", str(ledger_root),
    ])
    assert code == 0

    batches = [
        json.loads(line)
        for line in (campaign_dir / "commit_batches.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    # Exactly one record: the six-receipt pdf/go group, committed whole (not
    # split into a 5-chunk plus a leftover 1). The three-receipt cells/net
    # group stays below --min-batch-size and produces no record at all.
    assert len(batches) == 1
    record = batches[0]
    assert record["group"] == {"subdomain": "blog.aspose.org", "family": "pdf", "platform": "go"}
    assert record["planned"] == 6
    assert record["status"] == "VERIFIED"  # --execute was not passed
    assert set(record["outputs"]) == set(outputs_a.values())


def test_main_holds_back_a_group_at_exactly_min_batch_size_minus_one(tmp_path):
    content_repo = tmp_path / "content_repo"
    content_repo.mkdir()
    _init_content_repo(content_repo)

    sources = []
    receipts = []
    for i, locale in enumerate(["cs", "de", "fa", "hi"]):  # only 4 -- one short of the default 5
        page = f"page-{i}"
        source_path = f"content/blog.aspose.org/pdf/go/{page}/index.md"
        rel_out, sha = _write_output(
            content_repo, f"content/blog.aspose.org/pdf/go/{page}/index.{locale}.md", f"body {i}\n"
        )
        sources.append({
            "site_id": "blog.aspose.org", "family": "pdf", "platform": "go",
            "source_path": source_path, "source_sha256": "a" * 64, "wave": 1,
            "outputs": {locale: rel_out},
        })
        receipts.append(_receipt(rel_out, sha, source_path, locale))

    manifest_dict = {
        "schema_version": 1, "campaign_id": "test-campaign", "validation_policy": "zero-defect",
        "content_repo": str(content_repo), "content_repo_sha": "a" * 40, "translator_repo_sha": "b" * 40,
        "config_fingerprint": "c" * 64, "model_fingerprints": {"model_registry": "e" * 64},
        "tm_fingerprint": "f" * 64, "knowledge_fingerprints": {}, "target_locales": ["cs", "de", "fa", "hi"],
        "expected_source_count": len(sources), "expected_output_count": len(receipts),
        "execution_policy": {"output_selection": "missing_only"},
        "retry_policy": {
            "primary_model": "m2m100_418m", "primary_attempts": 3,
            "llm_escalation_attempts": 2, "llm_model": "professionalize_llm",
        },
        "commit_policy": {"branch": "main", "max_outputs_per_commit": 250, "push": False},
        "sources": sources,
    }
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(manifest_dict), encoding="utf-8")

    ledger_root = tmp_path / "ledger"
    campaign_dir = ledger_root / "test-campaign"
    campaign_dir.mkdir(parents=True)
    (campaign_dir / "acceptance_receipts.jsonl").write_text(
        "\n".join(json.dumps(r) for r in receipts) + "\n", encoding="utf-8"
    )

    code = main([
        "--manifest", str(manifest_path),
        "--content-repo", str(content_repo),
        "--ledger-root", str(ledger_root),
    ])
    assert code == 0
    batches_path = campaign_dir / "commit_batches.jsonl"
    assert not batches_path.exists() or batches_path.read_text(encoding="utf-8").strip() == ""


def test_min_batch_size_rejects_values_below_one(tmp_path):
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text("campaign_id: x\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        main([
            "--manifest", str(manifest_path),
            "--content-repo", str(tmp_path),
            "--min-batch-size", "0",
        ])
