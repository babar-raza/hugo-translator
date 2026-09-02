"""TC-APT-003: governed git-commit provenance forensics (factored out of campaign_runner)."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from src.workers import git_provenance as gp


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "content"
    r.mkdir()
    _git(r, "init", "-b", "main")
    _git(r, "config", "user.email", "t@example.invalid")
    _git(r, "config", "user.name", "T")
    (r / "baseline.txt").write_text("b", encoding="utf-8")
    _git(r, "add", "baseline.txt")
    _git(r, "commit", "-q", "-m", "baseline")
    return r


def _add(repo: Path, rel: str, text: str, subject: str) -> str:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    _git(repo, "add", rel)
    _git(repo, "commit", "-q", "-m", subject)
    return _git(repo, "rev-parse", "HEAD")


GOOD = "content(locale): zero-defect shard w2:docs.aspose.org:words:net:es:1"


def test_verify_governed_add_accepts_one_file_governed_commit(repo):
    baseline = _git(repo, "rev-parse", "HEAD")
    rel = "content/docs.aspose.org/es/words/net/a.md"
    sha = _add(repo, rel, "hola", GOOD)
    pat = gp.governed_subject_pattern(
        wave=2, site_id="docs.aspose.org", family="words", platform="net", locale="es"
    )
    got = gp.verify_governed_add(
        repo,
        rel,
        subject_pattern=pat,
        baseline_sha=baseline,
        current_sha256=hashlib.sha256(b"hola").hexdigest(),
    )
    assert got.commit_sha == sha and got.subject == GOOD


def test_verify_rejects_ungoverned_multifile_drifted_and_unknown(repo):
    baseline = _git(repo, "rev-parse", "HEAD")
    pat = gp.governed_subject_pattern(
        wave=2, site_id="docs.aspose.org", family="words", platform="net", locale="es"
    )
    rel = "content/docs.aspose.org/es/words/net/a.md"
    _add(repo, rel, "hola", "content(locale): handoff batch (2116 files)")
    with pytest.raises(gp.GovernedProvenanceError, match="not governed"):
        gp.verify_governed_add(
            repo,
            rel,
            subject_pattern=pat,
            baseline_sha=baseline,
            current_sha256=hashlib.sha256(b"hola").hexdigest(),
        )
    # multi-file governed commit
    rel2 = "content/docs.aspose.org/es/words/net/b.md"
    rel3 = "content/docs.aspose.org/es/words/net/c.md"
    for r in (rel2, rel3):
        (repo / r).write_text("x", encoding="utf-8")
    _git(repo, "add", rel2, rel3)
    _git(repo, "commit", "-q", "-m", GOOD)
    with pytest.raises(gp.GovernedProvenanceError, match="one-file add"):
        gp.verify_governed_add(
            repo,
            rel2,
            subject_pattern=pat,
            baseline_sha=baseline,
            current_sha256=hashlib.sha256(b"x").hexdigest(),
        )
    # blob drift
    rel4 = "content/docs.aspose.org/es/words/net/d.md"
    _add(repo, rel4, "orig", GOOD.replace(":1", ":2"))
    (repo / rel4).write_text("edited", encoding="utf-8")
    with pytest.raises(gp.GovernedProvenanceError, match="blob drift"):
        gp.verify_governed_add(
            repo,
            rel4,
            subject_pattern=pat,
            baseline_sha=baseline,
            current_sha256=hashlib.sha256(b"edited").hexdigest(),
        )
    # no provenance at all
    (repo / "content/untracked.md").write_text("u", encoding="utf-8")
    with pytest.raises(gp.GovernedProvenanceError, match="no commit provenance"):
        gp.verify_governed_add(
            repo,
            "content/untracked.md",
            subject_pattern=pat,
            baseline_sha=baseline,
            current_sha256="0" * 64,
        )


def test_verify_rejects_commit_before_baseline(repo):
    rel = "content/docs.aspose.org/es/words/net/a.md"
    _add(repo, rel, "hola", GOOD)
    later = _add(repo, "other.txt", "o", "later baseline")
    pat = gp.governed_subject_pattern(
        wave=2, site_id="docs.aspose.org", family="words", platform="net", locale="es"
    )
    with pytest.raises(gp.GovernedProvenanceError, match="predates pinned baseline"):
        gp.verify_governed_add(
            repo,
            rel,
            subject_pattern=pat,
            baseline_sha=later,
            current_sha256=hashlib.sha256(b"hola").hexdigest(),
        )


def test_last_add_commits_bulk_walk_and_classify(repo):
    rel_ok = "content/docs.aspose.org/es/words/net/a.md"
    rel_bad = "content/docs.aspose.org/de/words/net/a.md"
    sha_ok = _add(repo, rel_ok, "hola", GOOD)
    _add(repo, rel_bad, "hallo", "content(locale): bulk handoff")
    adds = gp.last_add_commits(repo, [rel_ok, rel_bad, "missing.md"])
    assert adds[rel_ok][0] == sha_ok and adds[rel_bad][1] == "content(locale): bulk handoff"
    assert "missing.md" not in adds
    result = gp.classify_bulk(
        repo,
        {
            rel_ok: hashlib.sha256(b"hola").hexdigest(),
            rel_bad: hashlib.sha256(b"hallo").hexdigest(),
            "missing.md": "0" * 64,
        },
    )
    assert isinstance(result[rel_ok], gp.GovernedCommit)
    assert result[rel_bad] == "commit is not governed"
    assert result["missing.md"] == "no commit provenance"
