"""Same-read, full-corpus comparator for every detector changed by plan v2."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[7]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.quality import audit_all_content as current  # noqa: E402
from src.translation_engine.write_gate import WriteGateResult  # noqa: E402
from src.utils.content_discovery import (  # noqa: E402
    discover_source_files,
    resolve_source_root,
    resolve_translated_path,
)

historical_source = subprocess.check_output(
    ["git", "show", "3599a45:scripts/quality/audit_all_content.py"],
    text=True,
    encoding="utf-8",
)
historical: dict[str, object] = {
    "__name__": "historical_audit_all_content",
    "__file__": str(ROOT / "scripts" / "quality" / "audit_all_content.py"),
}
exec(compile(historical_source, historical["__file__"], "exec"), historical)

CHECKS = ("purity_issue", "code_fence_dropped", "artifact_corruption", "shortcode_leak", "eu_hallucination", "link_path_corrupted")


def old_hit(check: str, source: str, target: str, locale: str) -> bool:
    source_body = historical["get_body"](source)
    target_body = historical["get_body"](target)
    if check == "purity_issue":
        return locale in historical["NON_LATIN"] and historical["check_purity"](target_body, locale)[0]
    if check == "code_fence_dropped":
        return "```" in source_body and historical["check_code_fence_dropped"](source_body, target_body)[0]
    if check == "artifact_corruption":
        return bool(historical["NLLB_ARTIFACTS"].search(target_body))
    if check == "shortcode_leak":
        return bool(historical["SHORTCODE_LEAK"].search(target_body) and not historical["SHORTCODE_LEAK"].search(source_body))
    if check == "eu_hallucination":
        return bool(historical["EU_HALLUCINATION"].search(target_body) and not historical["EU_HALLUCINATION"].search(source_body))
    if check == "link_path_corrupted":
        en_links = {m.group(2) for m in historical["_LINK_RE"].finditer(source_body) if m.group(2).startswith(("../", "./", "/"))}
        target_links = {m.group(2) for m in historical["_LINK_RE"].finditer(target_body) if m.group(2).startswith(("../", "./", "/"))}
        return bool(en_links and target_links and target_links - en_links)
    raise ValueError(check)


def new_hit(check: str, source: str, target: str, locale: str, path: Path) -> bool:
    source_body = current.get_body(source)
    target_body = current.get_body(target)
    if check == "purity_issue":
        return locale in current.NON_LATIN and current.check_purity(target_body, locale)[0]
    if check == "code_fence_dropped":
        if "```" not in source_body and "```" not in target_body:
            return False
        # BUGFIX 2026-07-27 (found during TC-DCF-022 manual disposition):
        # _gate_fence_parity strips frontmatter itself via self._get_body().
        # Calling it with the already-stripped *_body variables (computed
        # above for every other check in this function) double-strips real
        # files, which corrupts the result -- confirmed on a real file
        # (blog.aspose.net/zip/compress-files-folders-in-zip-csharp/index.ca.md,
        # a genuine src=17/tgt=0 fence-loss defect) where this produced a
        # false "passed" and misclassified a true finding as old_only.
        #
        # First attempt at a fix routed through current.check_code_fence_dropped(),
        # which is production-faithful (matches _run_registry_gates's raw-content
        # convention) but internally calls run_all_content_gates() -- the FULL
        # ~20-gate battery, including FastText-based whole-page language
        # detection (Gate 42) -- for every single file, purely to read gate 26's
        # verdict back out. That made a full-corpus run impractically slow (no
        # output after 50+ minutes, corpus-wide). Calling _gate_fence_parity
        # directly with RAW (unstripped) content is the correct, narrow fix:
        # it does its own single self._get_body() strip internally, so passing
        # raw content avoids the double-strip bug without paying for the other
        # ~19 unrelated gates.
        result = WriteGateResult(passed=True)
        current._GATE_EVALUATOR._gate_fence_parity(source, target, path, result)
        return not result.passed
    if check == "artifact_corruption":
        if not current.NLLB_ARTIFACTS.search(target_body):
            return False
        return bool(current.check_artifact_corruption(target_body))
    if check == "shortcode_leak":
        if not current.SHORTCODE_LEAK.search(target_body):
            return False
        return current.check_shortcode_leak(source_body, target_body)
    if check == "eu_hallucination":
        if not current.EU_HALLUCINATION.search(target_body):
            return False
        return bool(current.check_eu_hallucination(source_body, target_body))
    if check == "link_path_corrupted":
        if "[" not in source_body or "[" not in target_body:
            return False
        return bool(current.check_link_path_corrupted(source_body, target_body))
    raise ValueError(check)


def main(output: Path) -> None:
    started = time.monotonic()
    counts = {check: Counter() for check in CHECKS}
    samples = {check: {"old_only": [], "new_only": []} for check in CHECKS}
    stats = Counter()
    for site in current.SITES:
        try:
            profile = current._CONFIG.get_site_profile(site)
            content_root = current._CONFIG.resolve_content_root(profile.content_roots[0])
        except Exception as exc:
            stats["profile_errors"] += 1
            print(f"PROFILE_ERROR {site}: {type(exc).__name__}: {exc}", flush=True)
            continue
        if not content_root.exists():
            stats["missing_content_roots"] += 1
            print(f"MISSING_CONTENT_ROOT {site}: {content_root}", flush=True)
            continue
        source_root = resolve_source_root(profile, content_root)
        source_files = discover_source_files(profile, content_root)
        print(f"SITE {site}: {len(source_files)} sources", flush=True)
        for index, source_path in enumerate(source_files, start=1):
            if index % 1000 == 0:
                print(f"PROGRESS {site} {index}/{len(source_files)}", flush=True)
            try:
                source = source_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                stats["source_read_errors"] += 1
                continue
            for locale in profile.target_langs:
                target_path = resolve_translated_path(profile, source_path, locale)
                if not target_path.exists():
                    stats["missing_targets"] += 1
                    continue
                try:
                    target = target_path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    stats["target_read_errors"] += 1
                    continue
                stats["paired_targets"] += 1
                relative = str(target_path.relative_to(content_root))
                for check in CHECKS:
                    before = old_hit(check, source, target, locale)
                    after = new_hit(check, source, target, locale, target_path)
                    counts[check]["before"] += before
                    counts[check]["after"] += after
                    if before and not after:
                        counts[check]["old_only"] += 1
                        if len(samples[check]["old_only"]) < 20:
                            samples[check]["old_only"].append(f"{site}:{relative}")
                    elif after and not before:
                        counts[check]["new_only"] += 1
                        if len(samples[check]["new_only"]) < 20:
                            samples[check]["new_only"].append(f"{site}:{relative}")
    result = {
        "baseline": "3599a45:scripts/quality/audit_all_content.py",
        "current": "working tree",
        "same_read": True,
        "stats": dict(stats),
        "checks": {key: dict(value) for key, value in counts.items()},
        "samples": samples,
        "elapsed_seconds": round(time.monotonic() - started, 1),
    }
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
