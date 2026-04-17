r"""Safely recover legacy translation backlog directly in a live content repo."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.observability.legacy_backlog_recovery import recover_legacy_translation_backlog
from src.utils.config_loader import ConfigService
from src.workers.autonomous_content_translation_worker import AutonomousContentTranslationWorker


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--config-root", type=Path, default=Path("config"))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()

    report = recover_legacy_translation_backlog(
        repo=args.repo.resolve(),
        config_service=ConfigService(str(args.config_root)),
        validate_fn=AutonomousContentTranslationWorker._validate_orphan_structural_integrity,
        build_message_fn=AutonomousContentTranslationWorker._build_orphan_commit_message,
        apply=args.apply,
    )

    output = report.to_json()
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
