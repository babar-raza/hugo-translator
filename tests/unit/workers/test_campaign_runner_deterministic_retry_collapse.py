"""A deterministic (non-LLM) primary backend must not spend two guaranteed
no-op guided retries before LLM escalation.

Every MT backend in config/model_registry.yaml (m2m100, nllb, opus, marian,
small100 -- anything routed to HuggingFaceBackend/CTranslate2Backend in
src/model_runtime/loader.py) runs with do_sample=False and a fixed
num_beams, and never receives retry-feedback text (that channel is only
wired for isinstance(mt_model, LLMModelBackend) in
src/translation_engine/segment_translator.py). So once such a backend
rejects attempt 1, attempts 2 and 3 are guaranteed to reproduce
byte-identical output. CampaignRunner._primary_backend_is_deterministic
detects this from the model registry's `backend` field (the same field
_llm_identity_gate already reads) and CampaignRunner._run_campaign_job
collapses the primary retry budget to 0 (one real attempt) before
escalating, instead of the previous unconditional primary_attempts - 1 (2)
budget every manifest paid regardless of backend family.

An LLM primary backend (the approved inverse pairing --
primary_model="professionalize_llm", llm_model="m2m100_418m", see
CampaignManifest's _valid_pairs) must keep today's exact 3-attempt primary
budget: it has a real retry-feedback channel, so its repeated attempts are
not guaranteed no-ops.

These tests exercise CampaignRunner._run_campaign_job directly (constructed
through the real __init__, matching
tests/unit/workers/test_campaign_replace_existing_and_dirty_scope.py's
fixture style) against a fake engine whose translate_file() simulates the
retry_budget_override-bounded internal attempt loop that really lives in
src/translation_engine/file_pipeline.py (out of scope for this task, and not
touched here) -- enough to prove the campaign_runner-selected retry budget
is what changes, without loading a real model or editing
segment_translator.py.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from src.workers.campaign_manifest import sha256_file
from src.workers.campaign_runner import CampaignRunner

SRC_REL = "content/docs.aspose.org/en/words/net/page.md"
OUT_REL = "content/docs.aspose.org/hu/words/net/page.md"

M2M100 = "m2m100_418m"
PROFESSIONALIZE_LLM = "professionalize_llm"


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "content-repo"
    src = repo / SRC_REL
    src.parent.mkdir(parents=True)
    src.write_text("source text", encoding="utf-8")
    return repo


def _manifest(repo: Path, *, primary_model: str, llm_model: str) -> SimpleNamespace:
    """A bare stand-in for CampaignManifest exposing only what
    CampaignRunner.__init__ and _run_campaign_job read: .content_repo,
    .campaign_id, .retry_policy. Building a fully validated CampaignManifest
    (git repo, model_registry.yaml, fingerprints) is unnecessary for a test
    scoped to the retry-phase loop, per the lighter fixture style already
    used in tests/unit/workers/test_campaign_runner_quarantine_skip.py.
    """
    return SimpleNamespace(
        content_repo=str(repo),
        campaign_id="unit-det-collapse",
        retry_policy={
            "primary_model": primary_model,
            "primary_attempts": 3,
            "llm_escalation_attempts": 2,
            "llm_model": llm_model,
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
    """Stands in for ModelLoader.registry: same shape CampaignRunner reads
    via self.engine.model_loader.registry.get_model(model_id).backend.
    """

    def __init__(self, backend_by_model: dict[str, str]) -> None:
        self._backend_by_model = backend_by_model

    def get_model(self, model_id: str):
        return SimpleNamespace(backend=self._backend_by_model[model_id])


class _FakeEngine:
    """A fake engine.translate_file() that simulates the retry_budget_override
    -bounded internal attempt loop (real home: file_pipeline.py) just enough
    to count how many times the "model" backing each campaign role
    (primary/escalation) would actually be invoked -- the thing this task
    changes -- without loading a real model or touching segment_translator.py
    / file_pipeline.py.
    """

    def __init__(
        self,
        *,
        out: Path,
        src: Path,
        primary_model: str,
        backend_by_model: dict[str, str],
        reject_roles: frozenset[str],
    ) -> None:
        self.campaign_context: dict = {}
        self.config = SimpleNamespace(get_site_profile=lambda _s: SimpleNamespace())
        self.model_loader = SimpleNamespace(registry=_FakeRegistry(backend_by_model))
        self.backend_calls: dict[str, int] = {"primary": 0, "escalation": 0}
        self._out = out
        self._src = src
        self._primary_model = primary_model
        self._reject_roles = reject_roles

    def _get_output_path(self, *_a):
        return self._out

    def translate_file(self, site_id, file_path, **kwargs):
        model_id = kwargs["model_id"]
        retry_budget = kwargs["retry_budget_override"]
        locale = kwargs["target_langs"][0]
        role = "primary" if model_id == self._primary_model else "escalation"
        will_accept = role not in self._reject_roles
        accepted = False
        for _attempt in range(retry_budget + 1):
            self.backend_calls[role] += 1
            if will_accept:
                accepted = True
                break
        if not accepted:
            return SimpleNamespace(
                success=False, acceptance_receipts={}, errors=["rejected"], retry_attempts=retry_budget
            )
        self._out.parent.mkdir(parents=True, exist_ok=True)
        self._out.write_text("translated", encoding="utf-8")
        receipt = {
            "campaign_id": "unit-det-collapse",
            "source_path": str(self._src.resolve()),
            "output_path": str(self._out.resolve()),
            "source_sha256": sha256_file(self._src),
            "output_sha256": sha256_file(self._out),
            "target_lang": locale,
            "validation_policy": "zero-defect",
            "config_fingerprint": "c" * 64,
            "model_fingerprint": model_id,
            "gate_results": {i: {"passed": True} for i in range(1, 45)},
        }
        self.campaign_context["receipt_sink"](receipt)
        return SimpleNamespace(
            success=True,
            acceptance_receipts={locale: receipt},
            errors=[],
            retry_attempts=retry_budget,
        )


def _run(tmp_path: Path, *, primary_model: str, llm_model: str, backend_by_model: dict[str, str]):
    repo = _repo(tmp_path)
    out = repo / OUT_REL
    manifest = _manifest(repo, primary_model=primary_model, llm_model=llm_model)
    engine = _FakeEngine(
        out=out,
        src=repo / SRC_REL,
        primary_model=primary_model,
        backend_by_model=backend_by_model,
        reject_roles=frozenset({"primary"}),
    )
    runner = CampaignRunner(
        manifest=manifest,
        translation_engine=engine,
        translator_repo=tmp_path,
        ledger_root=tmp_path / "ledger",
    )
    # _run_locked() normally wires this into engine.campaign_context before
    # any job runs; calling _run_campaign_job directly (to isolate the
    # retry-phase loop from shard/commit machinery, matching the lighter
    # fixture style already used for this class) means it must be wired here
    # instead.
    engine.campaign_context["receipt_sink"] = runner._append_campaign_receipt
    accepted, output = runner._run_campaign_job(
        shard={"shard_id": "s0"},
        source=_FakeSource(),
        locale="hu",
        expected_output=OUT_REL,
    )
    return accepted, output, engine


class TestDeterministicPrimaryRetryCollapse:
    def test_deterministic_primary_gets_exactly_one_attempt_then_escalates(self, tmp_path):
        accepted, _output, engine = _run(
            tmp_path,
            primary_model=M2M100,
            llm_model=PROFESSIONALIZE_LLM,
            backend_by_model={M2M100: "huggingface", PROFESSIONALIZE_LLM: "llm"},
        )

        assert accepted is True
        # The deterministic primary always rejects in this fixture: proves
        # attempts 2 and 3 were skipped (fail-fast to escalation), not that
        # attempt 1 happened to succeed.
        assert engine.backend_calls["primary"] == 1
        assert engine.backend_calls["escalation"] == 1

    def test_llm_primary_keeps_the_existing_three_attempt_budget(self, tmp_path):
        """Regression guard: the approved inverse pairing (LLM primary,
        M2M100 escalation) must be completely unaffected by the collapse --
        an LLM backend has a real retry-feedback channel, so its repeated
        attempts are not guaranteed no-ops.
        """
        accepted, _output, engine = _run(
            tmp_path,
            primary_model=PROFESSIONALIZE_LLM,
            llm_model=M2M100,
            backend_by_model={PROFESSIONALIZE_LLM: "llm", M2M100: "huggingface"},
        )

        assert accepted is True
        assert engine.backend_calls["primary"] == 3
        assert engine.backend_calls["escalation"] == 1

    def test_unresolvable_primary_model_preserves_the_full_retry_budget(self, tmp_path):
        """A model_id the registry can't resolve (e.g. a manifest referencing
        a model this lightweight engine double doesn't know about) must not
        be guessed at as deterministic -- preserve today's full 3-attempt
        behaviour rather than risk collapsing a backend that might carry a
        real retry-feedback channel.
        """
        accepted, _output, engine = _run(
            tmp_path,
            primary_model="unregistered_model",
            llm_model=PROFESSIONALIZE_LLM,
            backend_by_model={PROFESSIONALIZE_LLM: "llm"},  # "unregistered_model" absent on purpose
        )

        assert accepted is True
        assert engine.backend_calls["primary"] == 3
        assert engine.backend_calls["escalation"] == 1


class TestPrimaryBackendIsDeterministic:
    """Direct unit coverage of the detection helper, independent of the full
    job flow above."""

    @staticmethod
    def _runner_with_registry(backend_by_model: dict[str, str]) -> CampaignRunner:
        runner = CampaignRunner.__new__(CampaignRunner)
        runner.engine = SimpleNamespace(
            model_loader=SimpleNamespace(registry=_FakeRegistry(backend_by_model))
        )
        return runner

    def test_huggingface_backend_is_deterministic(self):
        runner = self._runner_with_registry({M2M100: "huggingface"})
        assert runner._primary_backend_is_deterministic(M2M100) is True

    def test_ctranslate2_backend_is_deterministic(self):
        runner = self._runner_with_registry({"opus_en_de": "ctranslate2"})
        assert runner._primary_backend_is_deterministic("opus_en_de") is True

    def test_llm_backend_is_not_deterministic(self):
        runner = self._runner_with_registry({PROFESSIONALIZE_LLM: "llm"})
        assert runner._primary_backend_is_deterministic(PROFESSIONALIZE_LLM) is False

    def test_local_llm_backend_is_not_deterministic(self):
        runner = self._runner_with_registry({"local_llm_model": "local_llm"})
        assert runner._primary_backend_is_deterministic("local_llm_model") is False

    def test_unresolvable_model_defaults_to_not_deterministic(self):
        runner = self._runner_with_registry({})
        assert runner._primary_backend_is_deterministic("anything") is False

    def test_missing_model_loader_defaults_to_not_deterministic(self):
        runner = CampaignRunner.__new__(CampaignRunner)
        runner.engine = SimpleNamespace()  # no model_loader at all
        assert runner._primary_backend_is_deterministic(M2M100) is False
