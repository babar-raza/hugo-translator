"""TC-APT-003 acceptance: every cell has exactly one ledger row; ledger hashes == tracker records."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

import scripts.campaign.backfill_provenance as bp
from src.utils.metadata_tracker import MetadataTracker
from src.utils.models import BodyRules, OutputLayout, SiteProfile
from src.workers.work_ledger import WorkLedger, metadata_path_for_site

KNOWN = ("ar", "bg", "de", "en", "fr")


def _profile(root: Path, site_id: str = "docs.test.org") -> SiteProfile:
    return SiteProfile(
        site_id=site_id,
        content_roots=[str(root)],
        default_source_lang="en",
        target_langs=["ar", "de", "fr"],
        body=BodyRules(translate_markdown=True),
        output_layout=OutputLayout(per_language_folders=True, pattern="{lang}/{path}"),
        strict_locale_allowlist=True,
    )


def _w(path: Path, text: str = "---\ntitle: t\n---\nbody\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture()
def content_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "aspose.org"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "T")
    docs = repo / "content/docs.test.org"
    _w(docs / "en/_index.md")
    _w(docs / "en/cells/net/a.md", "source A")
    _w(docs / "en/cells/net/empty.md", "")
    _w(docs / "de/cells/net/a.md", "quelle A de")  # existing target, ungoverned history
    _w(docs / "bg/cells/net/a.md", "legacy bg")  # excluded legacy locale
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "content(locale): bulk handoff")
    # governed one-file add commit for fr
    _w(docs / "fr/cells/net/a.md", "source A fr")
    _git(repo, "add", "content/docs.test.org/fr/cells/net/a.md")
    _git(
        repo,
        "commit",
        "-q",
        "-m",
        "content(locale): zero-defect shard w0:docs.test.org:cells:net:fr:1",
    )
    return repo


def _translator(tmp_path: Path) -> Path:
    t = tmp_path / "translator"
    for rel in (
        "config/terminology.yaml",
        "config/terminology/technical_terms.yaml",
        "config/terminology/protected_terms.yaml",
        "config/terminology/aspose_terms.txt",
    ):
        _w(t / rel, f"# {rel}\n")
    return t


def _receipts(tmp_path: Path, content_repo: Path) -> dict:
    """A receipt for de/a.md whose source sha matches the current source -> UP_TO_DATE."""
    src_sha = hashlib.sha256(
        (content_repo / "content/docs.test.org/en/cells/net/a.md").read_bytes()
    ).hexdigest()
    out_sha = hashlib.sha256(
        (content_repo / "content/docs.test.org/de/cells/net/a.md").read_bytes()
    ).hexdigest()
    receipt = {
        "campaign_id": "old",
        "source_path": "content/docs.test.org/en/cells/net/a.md",
        "output_path": "content/docs.test.org/de/cells/net/a.md",
        "source_sha256": src_sha,
        "output_sha256": out_sha,
        "receipt_sha256": "r" * 64,
        "config_fingerprint": "cfg" * 21 + "x",
        "gate_results": {
            str(i): {"passed": True, "action": "block", "error": None} for i in range(1, 45)
        },
    }
    path = _w(tmp_path / "data/campaigns/old/acceptance_receipts.jsonl", json.dumps(receipt) + "\n")
    return bp.load_receipt_index([path])


def test_backfill_site_rows_states_and_provenance(content_repo, tmp_path):
    translator = _translator(tmp_path)
    profile = _profile(content_repo / "content/docs.test.org")
    receipts = _receipts(tmp_path, content_repo)
    rows, tracker, facts = bp.backfill_site(
        content_repo=content_repo,
        translator_repo=translator,
        profile=profile,
        known_codes=KNOWN,
        metadata_dir=tmp_path / "meta",
        receipts=receipts,
        workers=2,
    )
    # 3 sources x (3 allowlisted + 1 excluded 'bg') = 12 cells
    assert len(rows) == 12 and facts["rows"] == 12
    by = {(r["source_path"].rsplit("/", 1)[-1], r["target_lang"]): r for r in rows}
    a_de, a_fr, a_ar = by[("a.md", "de")], by[("a.md", "fr")], by[("a.md", "ar")]
    assert a_de["provenance_kind"] == "RECEIPT_BACKED" and a_de["eligibility_state"] == "UP_TO_DATE"
    assert (
        a_fr["provenance_kind"] == "GIT_COMMIT_BACKED"
        and a_fr["eligibility_state"] == "UNKNOWN_PROVENANCE"
    )
    assert a_fr["eligibility_reason_code"] == "git_commit_backed_receipt_missing"
    assert a_ar["eligibility_state"] == "MISSING_TRANSLATION" and a_ar["target_exists"] is False
    assert (
        by[("a.md", "bg")]["eligibility_state"] == "EXCLUDED_BY_PROFILE"
        and by[("a.md", "bg")]["target_exists"] is True
    )
    assert by[("empty.md", "de")]["eligibility_state"] == "SOURCE_INVALID"
    assert by[("_index.md", "fr")]["eligibility_state"] == "MISSING_TRANSLATION"
    assert facts["git_governed_commits"] == 1 and facts["receipt_backed"] == 1
    # tracker file written at the canonical per-site location with relative keys
    assert tracker.metadata_file == metadata_path_for_site("docs.test.org", tmp_path / "meta")
    assert "content/docs.test.org/en/cells/net/a.md" in tracker.entries()


def test_ledger_hashes_match_tracker_records_acceptance(content_repo, tmp_path):
    translator = _translator(tmp_path)
    profile = _profile(content_repo / "content/docs.test.org")
    rows, tracker, _ = bp.backfill_site(
        content_repo=content_repo,
        translator_repo=translator,
        profile=profile,
        known_codes=KNOWN,
        metadata_dir=tmp_path / "meta",
        receipts={},
        workers=2,
        git_provenance_enabled=False,
    )
    with WorkLedger(tmp_path / "ledger.sqlite3") as ledger:
        assert ledger.bulk_upsert(rows) == 12
        assert ledger.total() == 12 and ledger.duplicate_cells() == 0
        assert bp.ledger_matches_tracker(ledger, tracker) == []
        # independent recomputation agrees with both
        for row in ledger.query(site_id="docs.test.org"):
            assert (
                row["source_sha256"]
                == hashlib.sha256((content_repo / row["source_path"]).read_bytes()).hexdigest()
            )
            if row["target_exists"] and row["eligibility_state"] != "EXCLUDED_BY_PROFILE":
                assert (
                    row["target_sha256"]
                    == hashlib.sha256(
                        (content_repo / row["expected_output_path"]).read_bytes()
                    ).hexdigest()
                )
        # re-running the backfill is idempotent: same row count, no duplicates
        rows2, _, _ = bp.backfill_site(
            content_repo=content_repo,
            translator_repo=translator,
            profile=profile,
            known_codes=KNOWN,
            metadata_dir=tmp_path / "meta",
            receipts={},
            workers=2,
            git_provenance_enabled=False,
        )
        ledger.bulk_upsert(rows2)
        assert ledger.total() == 12
    # the reloaded tracker independently agrees
    reloaded = MetadataTracker(
        metadata_path_for_site("docs.test.org", tmp_path / "meta"),
        hash_algorithm="sha256",
        root=content_repo,
    )
    assert (
        reloaded.entries()["content/docs.test.org/en/cells/net/a.md"].outputs["de"].status
        == "unknown_provenance"
    )


def test_receipt_index_ignores_content_bearing_and_failed_receipts(tmp_path):
    good = {
        "output_path": "x.md",
        "output_sha256": "a" * 64,
        "gate_results": {"1": {"passed": True}},
    }
    bad_content = {**good, "output_path": "y.md", "content": "leak"}
    bad_gate = {**good, "output_path": "z.md", "gate_results": {"1": {"passed": False}}}
    path = _w(
        tmp_path / "r.jsonl", "\n".join(json.dumps(r) for r in (good, bad_content, bad_gate)) + "\n"
    )
    idx = bp.load_receipt_index([path])
    assert set(idx) == {"x.md"}
