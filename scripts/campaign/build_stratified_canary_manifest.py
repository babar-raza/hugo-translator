"""Derive the deterministic stratified canary from a full campaign manifest."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml

from src.utils.atomic_write import atomic_write


def _risk_score(path: Path) -> tuple[int, int, int, int, int, str]:
    text = path.read_text(encoding="utf-8")
    frontmatter = text.split("---", 2)[1] if text.startswith("---") else ""
    return (
        text.count("```") + text.count("~~~"),
        sum(1 for line in text.splitlines() if line.lstrip().startswith("|")),
        len(re.findall(r"\{\{[<%].*?[>%]\}\}", text)),
        len(re.findall(r"(?m)^[A-Za-z0-9_-]+:\s*[>|]\s*$", frontmatter)),
        len(re.findall(r"\[[^\]]+\]\([^)]+\)", text)),
        path.as_posix(),
    )


def _is_index(source: dict) -> bool:
    name = Path(source["source_path"]).name
    return name in {"_index.md", "index.md"}


def select_canary_sources(payload: dict) -> list[dict]:
    content_repo = Path(payload["content_repo"])
    grouped: dict[tuple[str, str, str], list[dict]] = {}
    for source in payload["sources"]:
        key = (source["site_id"], source["family"], source["platform"])
        grouped.setdefault(key, []).append(source)

    selected: list[dict] = []
    for key in sorted(grouped):
        group = sorted(grouped[key], key=lambda item: item["source_path"])
        index_candidates = [item for item in group if _is_index(item)]
        if index_candidates:
            selected.append(index_candidates[0])
        non_index = [item for item in group if not _is_index(item)]
        if non_index:
            scored = [
                (
                    _risk_score(content_repo / item["source_path"]),
                    item,
                )
                for item in non_index
            ]
            highest = max(score[:5] for score, _item in scored)
            tied = [item for score, item in scored if score[:5] == highest]
            selected.append(min(tied, key=lambda item: item["source_path"]))
    return selected


def build_canary(payload: dict) -> dict:
    selected = select_canary_sources(payload)
    result = dict(payload)
    result["sources"] = selected
    result["expected_source_count"] = len(selected)
    result["expected_output_count"] = sum(len(item["outputs"]) for item in selected)
    result["campaign_phase"] = "stratified-canary"
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)

    payload = yaml.safe_load(args.campaign_manifest.read_text(encoding="utf-8"))
    canary = build_canary(payload)
    atomic_write(
        path=args.output,
        content=yaml.safe_dump(canary, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
        fsync=True,
        create_parents=True,
    )
    print(
        f"Wrote {args.output}: {canary['expected_source_count']} sources, "
        f"{canary['expected_output_count']} outputs"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
