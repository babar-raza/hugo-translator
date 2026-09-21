"""RT-01: does `duplicate_paid_candidate` actually stop wasted compute?

Live incident (wave-cellsrust-go-t1a-20260910r2, quickstart.md): a
deterministic MT backend (m2m100_418m) used for LLM escalation produced a
byte-identical rejected candidate across its 2 configured escalation
attempts, yet the campaign's own audit found no `duplicate_retry_suppressed`
ledger row and could not observe any compute saved.

This test settles the question empirically against the real
`CampaignRunner._run_campaign_job` phase loop (not a re-derivation of it):
with only 2 escalation attempts configured, the `break` in
`_run_campaign_job` fires on the LAST phase in the list, so there is no
further phase left to skip -- the mechanism cannot possibly reduce compute
in that specific configuration, correct or not. With 3+ escalation attempts
configured, a correctly-firing `duplicate_paid_candidate` DOES have an
observable effect: escalation attempt 3 must never run.

Reuses the fixture style from
tests/unit/workers/test_campaign_runner_deterministic_retry_collapse.py
(fake engine simulating the retry_budget_override-bounded call, real
CampaignRunner/_run_campaign_job) rather than a new one.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from src.workers.campaign_manifest import sha256_file
from src.workers.campaign_runner import CampaignRunner

SRC_REL = "content/docs.aspose.org/en/cells/go/getting-started/quickstart.md"
OUT_REL = "content/docs.aspose.org/de/cells/go/getting-started/quickstart.md"

PROFESSIONALIZE_LLM = "professionalize_llm"
M2M100 = "m2m100_418m"


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "content-repo"
    src = repo / SRC_REL
    src.parent.mkdir(parents=True)
    src.write_text("source text", encoding="utf-8")
    return repo


def _manifest(repo: Path, *, llm_escalation_attempts: int) -> SimpleNamespace:
    return SimpleNamespace(
        content_repo=str(repo),
        campaign_id="unit-dup-suppress",
        retry_policy={
            "primary_model": PROFESSIONALIZE_LLM,
            "primary_attempts": 3,
            "llm_escalation_attempts": llm_escalation_attempts,
            "llm_model": M2M100,
            "llm_escalation_mode": "immediate",
        },
    )


class _FakeSource:
    def __init__(self) -> None:
        self.site_id = "docs.aspose.org"
        self.source_path = SRC_REL
        self.source_sha256 = "s" * 64

    def replacement_for(self, locale):
        return None


class _FakeRegistry:
    def __init__(self, backend_by_model: dict[str, str]) -> None:
        self._backend_by_model = backend_by_model

    def get_model(self, model_id: str):
        return SimpleNamespace(backend=self._backend_by_model[model_id])


class _RejectingIssue:
    def __init__(self, validator: str) -> None:
        self.validator = validator
        self.severity = "error"
        self.details = {"source_count": 6, "translation_count": 7}


class _FakeEngine:
    """Every call is rejected. The escalation model (simulating deterministic
    m2m100) always produces the SAME candidate_sha256/gate -- the exact
    live-incident fingerprint shape. The primary model (LLM) gets a distinct
    hash per attempt, matching a real LLM's non-deterministic output."""

    def __init__(self, *, out: Path, primary_model: str, backend_by_model: dict[str, str]) -> None:
        self.campaign_context: dict = {}
        self.config = SimpleNamespace(get_site_profile=lambda _s: SimpleNamespace())
        self.model_loader = SimpleNamespace(registry=_FakeRegistry(backend_by_model))
        self.calls: dict[str, int] = {"primary": 0, "escalation": 0}
        self._out = out
        self._primary_model = primary_model

    def _get_output_path(self, *_a):
        return self._out

    def translate_file(self, site_id, file_path, **kwargs):
        model_id = kwargs["model_id"]
        role = "primary" if model_id == self._primary_model else "escalation"
        self.calls[role] += 1
        candidate_sha256 = (
            f"primary-attempt-{self.calls['primary']}"
            if role == "primary"
            else "escalation-identical-hash"
        )
        return SimpleNamespace(
            success=False,
            acceptance_receipts={},
            errors=["rejected"],
            retry_attempts=kwargs["retry_budget_override"],
            candidate_sha256={kwargs["target_langs"][0]: candidate_sha256},
            validation_result=SimpleNamespace(issues=[_RejectingIssue("LinkValidator")]),
        )


def _run(tmp_path: Path, *, llm_escalation_attempts: int):
    repo = _repo(tmp_path)
    out = repo / OUT_REL
    manifest = _manifest(repo, llm_escalation_attempts=llm_escalation_attempts)
    engine = _FakeEngine(
        out=out,
        primary_model=PROFESSIONALIZE_LLM,
        backend_by_model={PROFESSIONALIZE_LLM: "llm", M2M100: "huggingface"},
    )
    runner = CampaignRunner(
        manifest=manifest,
        translation_engine=engine,
        translator_repo=tmp_path,
        ledger_root=tmp_path / "ledger",
    )
    engine.campaign_context["receipt_sink"] = runner._append_campaign_receipt
    accepted, _output = runner._run_campaign_job(
        shard={"shard_id": "s0"},
        source=_FakeSource(),
        locale="de",
        expected_output=OUT_REL,
    )
    failures = runner.ledger.recent_failures(output_path=OUT_REL, target_lang="de")
    return accepted, engine, failures


class TestDuplicateSuppressionObservableEffect:
    def test_two_escalation_attempts_has_no_observable_savings_either_way(self, tmp_path):
        """The live incident's actual manifest shape (llm_escalation_attempts=2):
        the second escalation attempt IS the last phase in the list, so
        whether `duplicate_paid_candidate` fires or not, there is no third
        phase left to `break` out of -- both attempts always run. This is
        the real, structural reason the live audit observed 'no compute
        saved', independent of whether the fingerprint match itself is
        working -- confirmed by both escalation attempts running here.
        """
        accepted, engine, failures = _run(tmp_path, llm_escalation_attempts=2)

        assert accepted is False
        assert engine.calls["escalation"] == 2, (
            "both escalation attempts run regardless of duplicate detection "
            "when there are only 2 configured -- matches the live incident"
        )

    def test_three_escalation_attempts_third_is_skipped_when_fingerprint_repeats(self, tmp_path):
        """With a THIRD escalation attempt configured, a correctly-firing
        `duplicate_paid_candidate` must skip it: attempts 1 and 2 already
        proved the identical (candidate_sha256, gate) pair repeats, so a
        3rd real model call would be a guaranteed-identical, wasted
        invocation. This is the scenario where the mechanism's compute
        savings are actually observable.
        """
        accepted, engine, failures = _run(tmp_path, llm_escalation_attempts=3)

        assert accepted is False
        assert engine.calls["escalation"] == 2, (
            f"expected escalation attempt 3 to be skipped via the "
            f"duplicate-fingerprint break, but the backend was called "
            f"{engine.calls['escalation']} times"
        )
        suppressed = [f for f in failures if f.get("gate") == "duplicate_retry_suppressed"]
        assert len(suppressed) == 1, (
            f"expected exactly one duplicate_retry_suppressed ledger row, "
            f"found {len(suppressed)} in {failures}"
        )
