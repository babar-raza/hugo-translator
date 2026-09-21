"""Follow-up to TC-APT-047/094: config-gated switch from `try_acquire_gpu_lane`'s
single fleet-wide mutex to VR-01's `GPUAdmissionController`
(`src/hardware/gpu_admission.py`).

`config/global.yaml`'s `gpu_admission.enabled` (default False, left unchanged by
this task) is the one switch:

- False (today's real default): `main()` must behave exactly as it did before
  this task -- `try_acquire_gpu_lane` is still the function actually called, and
  `try_acquire_gpu_admission` is never invoked. `TestDisabledPathIsUnchanged`
  is the regression guard for that claim.
- True: `main()` uses `try_acquire_gpu_admission` instead, which asks
  `GPUAdmissionController` for a real-telemetry (nvidia-smi VRAM + temperature)
  admission slot rather than the single mutex. Unlike the old lane, more than
  one GPU-bound shard can be admitted at once fleet-wide when the measured
  evidence says there is room -- `TestConcurrentAdmissionAcrossTwoLaunchers`
  and `TestEnabledPathGrantsAndReleases` prove that capability, not just that
  admission is called.

All fake-probe tests use an isolated `tmp_path` registry/lock -- never the
real repo's `.local/gpu_admission_registry.json` -- so they cannot interfere
with a live campaign fleet on this machine.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from scripts.campaign import launch_parallel_campaign_shards as launcher
from scripts.campaign.launch_parallel_campaign_shards import (
    GPU_PRIMARY_LOCALES,
    is_gpu_admission_enabled,
    main,
    try_acquire_gpu_admission,
    try_acquire_gpu_lane,
)
from src.hardware.gpu_admission import GPUAdmissionController
from src.workers.campaign_manifest import CampaignManifest

LOCALES = ["de", "es", "hu", "ja", "ro"]


def _manifest_dict(tmp_path: Path, campaign_id: str) -> dict:
    return {
        "schema_version": 1,
        "campaign_id": campaign_id,
        "validation_policy": "zero-defect",
        "content_repo": str(tmp_path),
        "content_repo_sha": "a" * 40,
        "translator_repo_sha": "b" * 40,
        "config_fingerprint": "c" * 64,
        "model_fingerprints": {"model_registry": "e" * 64},
        "tm_fingerprint": "f" * 64,
        "knowledge_fingerprints": {},
        "target_locales": list(LOCALES),
        "expected_source_count": 1,
        "expected_output_count": len(LOCALES),
        "retry_policy": {
            "primary_model": "professionalize_llm",
            "primary_attempts": 3,
            "llm_escalation_attempts": 2,
            "llm_model": "m2m100_418m",
        },
        "commit_policy": {"branch": "main", "max_outputs_per_commit": 250, "push": False},
        "sources": [
            {
                "site_id": "blog.aspose.org",
                "family": "pdf",
                "platform": "cpp",
                "source_path": "content/blog.aspose.org/pdf/cpp/page/index.md",
                "source_sha256": "d" * 64,
                "wave": 0,
                "outputs": {
                    locale: f"content/blog.aspose.org/pdf/cpp/page/index.{locale}.md"
                    for locale in LOCALES
                },
            }
        ],
    }


def _load(tmp_path: Path, campaign_id: str = "gpu-admission-launcher") -> CampaignManifest:
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(_manifest_dict(tmp_path, campaign_id)), encoding="utf-8")
    return CampaignManifest.load(path)


def _run_dry(tmp_path, campaign_id: str = "gpu-admission-launcher") -> int:
    _load(tmp_path, campaign_id)
    argv = [
        "--campaign-manifest",
        str(tmp_path / "manifest.yaml"),
        "--ledger-root",
        str(tmp_path / "campaigns"),
        "--wait",
        "--dry-run",
        "--session-id",
        "gpu-admission-wiring-test",
    ]
    return main(argv)


def _fake_vram_probe(used_mib: float = 0.0, total_mib: float = 16376.0, source: str = "fake"):
    def _probe():
        return used_mib, total_mib, source

    return _probe


def _fake_temp_probe(temp_c: float = 60.0):
    def _probe():
        return temp_c

    return _probe


# ---------------------------------------------------------------------------
# is_gpu_admission_enabled()
# ---------------------------------------------------------------------------


class TestIsGpuAdmissionEnabled:
    def test_true_when_config_says_so(self, tmp_path):
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "global.yaml").write_text(
            "gpu_admission:\n  enabled: true\n", encoding="utf-8"
        )
        assert is_gpu_admission_enabled(tmp_path) is True

    def test_false_when_config_says_so(self, tmp_path):
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "global.yaml").write_text(
            "gpu_admission:\n  enabled: false\n", encoding="utf-8"
        )
        assert is_gpu_admission_enabled(tmp_path) is False

    def test_false_when_config_file_missing(self, tmp_path):
        assert is_gpu_admission_enabled(tmp_path) is False

    def test_false_when_gpu_admission_key_missing(self, tmp_path):
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "global.yaml").write_text("other_key: 1\n", encoding="utf-8")
        assert is_gpu_admission_enabled(tmp_path) is False

    def test_false_on_malformed_yaml_value(self, tmp_path):
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "global.yaml").write_text(
            "gpu_admission: [not, a, dict]\n", encoding="utf-8"
        )
        assert is_gpu_admission_enabled(tmp_path) is False

    def test_real_repo_config_parses_to_a_bool(self):
        """The actual config/global.yaml's gpu_admission.enabled must parse
        cleanly to a real bool via this function -- not a snapshot of which
        value it currently holds (that's an operational decision, made and
        changed outside this test file; see config/global.yaml's own comment
        history for the enable/disable rationale at any given time)."""
        repo_root = Path(__file__).resolve().parents[3]
        assert isinstance(is_gpu_admission_enabled(repo_root), bool)


# ---------------------------------------------------------------------------
# try_acquire_gpu_admission() in isolation
# ---------------------------------------------------------------------------


class TestTryAcquireGpuAdmission:
    def test_grants_and_registers_when_telemetry_allows(self, tmp_path, monkeypatch):
        registry_root = tmp_path / "registry"
        monkeypatch.setattr(
            launcher,
            "make_admission_controller",
            lambda: GPUAdmissionController(
                registry_path=".registry.json",
                vram_budget_percent=80.0,
                thermal_ceiling_c=80.0,
                root=registry_root,
                vram_probe=_fake_vram_probe(),
                temp_probe=_fake_temp_probe(),
                per_process_vram_mib={"m2m100_418m": 1100.0},
            ),
        )

        controller = try_acquire_gpu_admission(tmp_path / "campaigns", "campaign-x:shard-hu")

        assert controller is not None
        assert isinstance(controller, GPUAdmissionController)
        registry = controller.current_registry()
        assert len(registry) == 1
        entry = next(iter(registry.values()))
        assert entry["shard_id"] == "campaign-x:shard-hu"
        assert entry["model_id"] == "m2m100_418m"
        controller.release_admission()
        assert controller.current_registry() == {}

    def test_returns_none_when_telemetry_denies(self, tmp_path, monkeypatch):
        registry_root = tmp_path / "registry"
        monkeypatch.setattr(
            launcher,
            "make_admission_controller",
            lambda: GPUAdmissionController(
                registry_path=".registry.json",
                vram_budget_percent=80.0,
                thermal_ceiling_c=80.0,
                root=registry_root,
                vram_probe=_fake_vram_probe(used_mib=0.0, total_mib=1000.0),  # budget=800
                temp_probe=_fake_temp_probe(),
                per_process_vram_mib={"m2m100_418m": 1100.0},  # exceeds budget alone
            ),
        )

        controller = try_acquire_gpu_admission(tmp_path / "campaigns", "campaign-x:shard-hu")

        assert controller is None

    def test_ledger_root_argument_does_not_affect_which_registry_is_used(self, tmp_path, monkeypatch):
        """ledger_root is accepted only for call-site symmetry with
        try_acquire_gpu_lane(ledger_root) -- prove two different ledger_root
        values still land in the SAME (mocked) registry."""
        registry_root = tmp_path / "registry"
        monkeypatch.setattr(
            launcher,
            "make_admission_controller",
            lambda: GPUAdmissionController(
                registry_path=".registry.json",
                root=registry_root,
                vram_probe=_fake_vram_probe(),
                temp_probe=_fake_temp_probe(),
                per_process_vram_mib={"m2m100_418m": 1100.0},
            ),
        )

        first = try_acquire_gpu_admission(tmp_path / "campaigns_a", "campaign-a:shard-hu")
        assert first is not None
        # Same PID as `first` (same test process) -- request_admission's own
        # idempotency path grants it "already registered" rather than adding
        # a second entry; the point here is only that it reads/writes the
        # same underlying registry file regardless of ledger_root.
        second = try_acquire_gpu_admission(tmp_path / "campaigns_b", "campaign-a:shard-hu")
        assert second is not None
        assert len(first.current_registry()) == 1


# ---------------------------------------------------------------------------
# Regression guard: gpu_admission.enabled = false is byte-identical to today
# ---------------------------------------------------------------------------


class TestDisabledPathIsUnchanged:
    def test_default_path_calls_try_acquire_gpu_lane_and_never_admission(self, tmp_path, monkeypatch):
        """The safety-critical claim: with gpu_admission.enabled false (today's
        real default), main()'s wave loop must still call try_acquire_gpu_lane
        -- not the new admission path -- exactly as before this task existed."""
        calls: list[Path] = []
        original_lane = launcher.try_acquire_gpu_lane

        def spy_lane(ledger_root):
            calls.append(ledger_root)
            return original_lane(ledger_root)

        def fail_if_called(*_args, **_kwargs):
            raise AssertionError(
                "try_acquire_gpu_admission must not be called when gpu_admission.enabled is false"
            )

        monkeypatch.setattr(launcher, "is_gpu_admission_enabled", lambda root: False)
        monkeypatch.setattr(launcher, "try_acquire_gpu_lane", spy_lane)
        monkeypatch.setattr(launcher, "try_acquire_gpu_admission", fail_if_called)

        status = _run_dry(tmp_path)

        assert status == 0
        assert len(calls) == 1
        assert calls[0] == tmp_path / "campaigns"

    def test_disabled_path_output_is_identical_in_shape_to_pre_task_behaviour(
        self, tmp_path, monkeypatch, capsys
    ):
        """Same dry-run assertions the pre-existing lane-based test suite
        (test_launcher_gpu_lane_and_family_claims.py) makes against main() with
        a free lane -- proves output shape is unaffected by this task when
        disabled."""
        monkeypatch.setattr(launcher, "is_gpu_admission_enabled", lambda root: False)

        status = _run_dry(tmp_path)
        out = capsys.readouterr().out

        assert status == 0
        assert "deferring" not in out
        assert all(f":{locale}:" in out for locale in GPU_PRIMARY_LOCALES)


# ---------------------------------------------------------------------------
# Enabled path: full wave grant + release, and correct denial/deferral
# ---------------------------------------------------------------------------


class TestEnabledPathGrantsAndReleases:
    def test_admission_is_requested_granted_and_released_through_a_full_wave(
        self, tmp_path, monkeypatch, capsys
    ):
        registry_root = tmp_path / "registry"
        controller = GPUAdmissionController(
            registry_path=".registry.json",
            vram_budget_percent=80.0,
            thermal_ceiling_c=80.0,
            root=registry_root,
            vram_probe=_fake_vram_probe(),
            temp_probe=_fake_temp_probe(),
            per_process_vram_mib={"m2m100_418m": 1100.0},
        )
        monkeypatch.setattr(launcher, "is_gpu_admission_enabled", lambda root: True)
        monkeypatch.setattr(launcher, "make_admission_controller", lambda: controller)

        status = _run_dry(tmp_path)
        out = capsys.readouterr().out

        assert status == 0
        assert "deferring" not in out
        assert all(f":{locale}:" in out for locale in GPU_PRIMARY_LOCALES)
        # The finally block's .release_admission() ran even though --dry-run
        # returned before any child was launched -- no slot is left held.
        assert controller.current_registry() == {}

    def test_denied_admission_defers_gpu_bound_shards_same_as_the_old_lane(
        self, tmp_path, monkeypatch, capsys
    ):
        registry_root = tmp_path / "registry"
        controller = GPUAdmissionController(
            registry_path=".registry.json",
            vram_budget_percent=80.0,
            thermal_ceiling_c=80.0,
            root=registry_root,
            vram_probe=_fake_vram_probe(used_mib=0.0, total_mib=1200.0),  # budget=960
            temp_probe=_fake_temp_probe(),
            per_process_vram_mib={"m2m100_418m": 1100.0},  # exceeds budget alone
        )
        monkeypatch.setattr(launcher, "is_gpu_admission_enabled", lambda root: True)
        monkeypatch.setattr(launcher, "make_admission_controller", lambda: controller)

        status = _run_dry(tmp_path)
        out = capsys.readouterr().out

        assert status == 0
        assert "deferring 3 GPU-bound shard(s)" in out
        for gpu_locale in GPU_PRIMARY_LOCALES:
            assert f":{gpu_locale}:" not in out


# ---------------------------------------------------------------------------
# The actual point of this task: MORE THAN ONE concurrent GPU-bound admission
# ---------------------------------------------------------------------------


class TestConcurrentAdmissionAcrossTwoLaunchers:
    """Simulates two independent launcher processes/instances (distinct PIDs,
    like two real OS processes would have) sharing one registry. psutil's
    stale-PID cleanup is disabled here exactly like test_gpu_admission.py's own
    fake-entry tests -- these synthetic PIDs are not real running processes."""

    def test_two_controller_instances_can_both_hold_a_slot_at_once(self, tmp_path):
        registry_root = tmp_path / "shared_registry"

        def make(pid: int) -> GPUAdmissionController:
            ctrl = GPUAdmissionController(
                registry_path=".registry.json",
                vram_budget_percent=80.0,
                thermal_ceiling_c=80.0,
                root=registry_root,
                vram_probe=_fake_vram_probe(used_mib=0.0, total_mib=16376.0),
                temp_probe=_fake_temp_probe(),
                per_process_vram_mib={"m2m100_418m": 1100.0},
            )
            ctrl._pid = str(pid)
            return ctrl

        launcher_a = make(555101)
        launcher_b = make(555102)

        # The whole simulation (grant, inspect, release) stays inside one
        # patched context: current_registry()'s stale-PID cleanup would
        # otherwise treat these synthetic PIDs (not real running processes)
        # as dead and silently strip them the moment the patch is lifted.
        with patch("src.hardware.gpu_admission._HAS_PSUTIL", False):
            granted_a, reason_a, _telemetry_a = launcher_a.request_admission(
                "campaign-a:shard-hu", "m2m100_418m"
            )
            granted_b, reason_b, _telemetry_b = launcher_b.request_admission(
                "campaign-b:shard-ja", "m2m100_418m"
            )

            assert granted_a, f"expected grant; got: {reason_a}"
            assert granted_b, f"expected grant; got: {reason_b}"

            registry = launcher_a.current_registry()
            assert len(registry) == 2, "both launchers must hold a slot in the SAME registry at once"
            assert {entry["shard_id"] for entry in registry.values()} == {
                "campaign-a:shard-hu",
                "campaign-b:shard-ja",
            }

            launcher_a.release_admission()
            launcher_b.release_admission()
            assert launcher_a.current_registry() == {}

    def test_two_calls_to_try_acquire_gpu_admission_can_both_grant(self, tmp_path, monkeypatch):
        """Same capability, through this task's actual new wiring function --
        two calls with the same ledger_root, standing in for two concurrent
        launcher processes."""
        registry_root = tmp_path / "shared_registry_via_function"
        pids = iter([555201, 555202, 555203])

        def fake_make_admission_controller() -> GPUAdmissionController:
            ctrl = GPUAdmissionController(
                registry_path=".registry.json",
                vram_budget_percent=80.0,
                thermal_ceiling_c=80.0,
                root=registry_root,
                vram_probe=_fake_vram_probe(used_mib=0.0, total_mib=16376.0),
                temp_probe=_fake_temp_probe(),
                per_process_vram_mib={"m2m100_418m": 1100.0},
            )
            ctrl._pid = str(next(pids))
            return ctrl

        monkeypatch.setattr(launcher, "make_admission_controller", fake_make_admission_controller)
        ledger_root = tmp_path / "campaigns"

        with patch("src.hardware.gpu_admission._HAS_PSUTIL", False):
            first = try_acquire_gpu_admission(ledger_root, "campaign-a:shard-hu")
            second = try_acquire_gpu_admission(ledger_root, "campaign-b:shard-ja")

            assert first is not None, "first concurrent admission must be granted"
            assert second is not None, "second concurrent admission must ALSO be granted -- this is the point"
            registry = first.current_registry()
            assert len(registry) == 2

    def test_admission_beyond_the_configured_cap_is_denied(self, tmp_path, monkeypatch):
        """Two slots fit; a third (over budget) must be denied/deferred, not
        silently granted -- concurrency is bounded by real telemetry, not
        unlimited."""
        registry_root = tmp_path / "capped_registry"
        pids = iter([555301, 555302, 555303])

        def fake_make_admission_controller() -> GPUAdmissionController:
            ctrl = GPUAdmissionController(
                registry_path=".registry.json",
                vram_budget_percent=80.0,
                thermal_ceiling_c=80.0,
                root=registry_root,
                # budget = 80% of 2500 = 2000 MiB; two 1000 MiB slots fit, a third does not.
                vram_probe=_fake_vram_probe(used_mib=0.0, total_mib=2500.0),
                temp_probe=_fake_temp_probe(),
                per_process_vram_mib={"m2m100_418m": 1000.0},
            )
            ctrl._pid = str(next(pids))
            return ctrl

        monkeypatch.setattr(launcher, "make_admission_controller", fake_make_admission_controller)
        ledger_root = tmp_path / "campaigns"

        with patch("src.hardware.gpu_admission._HAS_PSUTIL", False):
            first = try_acquire_gpu_admission(ledger_root, "campaign-a:shard-hu")
            second = try_acquire_gpu_admission(ledger_root, "campaign-b:shard-ja")
            third = try_acquire_gpu_admission(ledger_root, "campaign-c:shard-ro")

        assert first is not None
        assert second is not None
        assert third is None, "a third slot beyond the configured VRAM budget must be denied"


# ---------------------------------------------------------------------------
# Real (unmocked) nvidia-smi telemetry -- admission-only, no model load
# ---------------------------------------------------------------------------


class TestRealNvidiaSmiConcurrentAdmission:
    def test_two_concurrent_admissions_succeed_on_the_real_idle_gpu(self, tmp_path):
        """Not mocked: uses the real nvidia-smi VRAM + temperature probes
        (GPUAdmissionController's defaults). Proves the capability this task
        adds is real on this machine's actual hardware right now, not just
        arithmetic over fake numbers. No model is loaded -- admission only."""
        from src.hardware.gpu_admission import TelemetryError, query_temperature_c, query_vram_mib

        try:
            query_vram_mib()
            query_temperature_c()
        except TelemetryError as exc:
            pytest.skip(f"nvidia-smi not available in this environment: {exc}")

        registry_root = tmp_path / "real_telemetry_registry"

        def make(pid: int) -> GPUAdmissionController:
            ctrl = GPUAdmissionController(
                registry_path=".registry.json",
                root=registry_root,
                per_process_vram_mib={"m2m100_418m": 1100.0},
                # vram_probe / temp_probe deliberately left at their real
                # nvidia-smi defaults -- not mocked.
            )
            ctrl._pid = str(pid)
            return ctrl

        launcher_a = make(555401)
        launcher_b = make(555402)
        try:
            with patch("src.hardware.gpu_admission._HAS_PSUTIL", False):
                granted_a, reason_a, telemetry_a = launcher_a.request_admission(
                    "real-a:shard-hu", "m2m100_418m"
                )
                granted_b, reason_b, telemetry_b = launcher_b.request_admission(
                    "real-b:shard-ja", "m2m100_418m"
                )

            assert granted_a, f"expected real grant; got: {reason_a} / {telemetry_a}"
            assert granted_b, f"expected real grant; got: {reason_b} / {telemetry_b}"
        finally:
            with patch("src.hardware.gpu_admission._HAS_PSUTIL", False):
                launcher_a.release_admission()
                launcher_b.release_admission()
