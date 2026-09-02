"""Measure the live rerun-determinism baseline (TC-APT-023, plan 5.1 item 5).

Runs the mission corpus segments through the production backend TWICE under pinned config and
records the byte-identical and semantic-equivalence rates, together with the fingerprints the
contract is conditioned on (profile, protection, model identity).  Gate 9 re-runs this and
compares against the recorded baseline to catch drift introduced during the mission.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.model_runtime import model_identity
from src.utils.atomic_write import atomic_write
from src.workers import determinism as det


def build_backend(model_id: str, registry_path: Path):
    from src.model_runtime.loader import ModelLoader
    from src.model_runtime.registry import ModelRegistry
    from src.utils.config_loader import get_global_config

    raw = get_global_config()
    hardware = raw.get("hardware", {}) or {}
    device = "cpu"
    if hardware.get("enable_gpu", True):
        try:
            import torch

            if torch.cuda.is_available():
                device = "cuda"
        except Exception:
            device = "cpu"
    return ModelLoader(ModelRegistry(registry_path), device=device, config=raw).load_model(model_id)


def current_fingerprints(model_id: str, translator_repo: Path, site_id: str) -> dict[str, str]:
    from src.utils.config_loader import ConfigService
    from src.workers.fingerprints import site_fingerprints

    profile = ConfigService(translator_repo / "config").get_site_profile(site_id)
    fps = site_fingerprints(profile, translator_repo)
    baseline = model_identity.load_baseline(model_id) or {}
    return {
        "site_id": site_id,
        "profile_fingerprint": fps["profile_fingerprint"],
        "protection_fingerprint": fps["protection_fingerprint"],
        "model_id": model_id,
        "model_identity_sha256": baseline.get("response_sha256", "unknown"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TC-APT-023 live determinism measurement")
    parser.add_argument("--model-id", default="professionalize_llm")
    parser.add_argument("--registry", type=Path, default=Path("config/model_registry.yaml"))
    parser.add_argument("--translator-repo", type=Path, default=Path.cwd())
    parser.add_argument(
        "--segments",
        type=Path,
        default=Path("data/benchmark_corpus/aspose_org_mission_segments.json"),
    )
    parser.add_argument("--site-id", default="docs.aspose.org")
    parser.add_argument("--langs", default="de,fr,ar,ja")
    parser.add_argument("--max-segments", type=int, default=8)
    parser.add_argument("--threshold", type=float, default=det.DEFAULT_SIMILARITY_THRESHOLD)
    parser.add_argument("--baseline", type=Path, default=det.DEFAULT_BASELINE_PATH)
    parser.add_argument("--write-baseline", action="store_true")
    parser.add_argument(
        "--report", type=Path, default=Path("data/quality/rerun_determinism_run.json")
    )
    args = parser.parse_args(argv)

    segments = json.loads(args.segments.read_text(encoding="utf-8"))[: args.max_segments]
    texts = [s["text_en"] for s in segments]
    backend = build_backend(args.model_id, args.registry)
    pairs: list[tuple[str, str, str]] = []
    for lang in (x.strip() for x in args.langs.split(",") if x.strip()):
        pairs.extend(det.translate_twice(backend, texts, "en", lang))
    fingerprints = current_fingerprints(args.model_id, args.translator_repo.resolve(), args.site_id)
    report = det.measure(pairs, fingerprints=fingerprints, similarity_threshold=args.threshold)
    payload = report.as_dict()
    payload["comparison_with_baseline"] = det.compare_with_baseline(report, args.baseline)
    payload["measured_at"] = datetime.now(timezone.utc).isoformat()
    atomic_write(path=args.report, content=json.dumps(payload, indent=2))
    if args.write_baseline:
        det.write_baseline(report, args.baseline)
        payload["baseline_written"] = str(args.baseline)
    print(json.dumps({k: v for k, v in payload.items() if k != "results"}, indent=2)[:4000])
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
