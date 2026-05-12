"""Phase 5: Content root environment readiness analysis."""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
PYTHONPATH_EXTRA = "C:/Users/prora/AppData/Roaming/Python/Python313/site-packages"
if PYTHONPATH_EXTRA not in sys.path:
    sys.path.insert(0, PYTHONPATH_EXTRA)

import yaml

PROJECT_ROOT = Path(__file__).parent.parent
PROFILES_DIR = PROJECT_ROOT / "config" / "site_profiles"
EVIDENCE_DIR = PROJECT_ROOT / "data" / "evidence" / "rbtw"

_ENV_VAR_RE = re.compile(r"\$\{([^}]+)\}|\$([A-Z_][A-Z0-9_]*)")

results = []

for pf in sorted(PROFILES_DIR.glob("*.yaml")):
    with open(pf, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    site_id = data.get("site_id", pf.stem)
    roots_raw = data.get("content_roots", [])
    if isinstance(roots_raw, str):
        roots_raw = [roots_raw]

    profile_result = {
        "profile": pf.name,
        "site_id": site_id,
        "roots": [],
        "env_vars_required": [],
        "can_test_now": False,
        "block_reason": None,
        "block_class": None,
    }

    env_vars_in_profile = set()
    for root in roots_raw:
        root_str = str(root)
        found_vars = [m.group(1) or m.group(2) for m in _ENV_VAR_RE.finditer(root_str)]
        expanded = os.path.expandvars(root_str)
        resolved = Path(expanded)
        exists = resolved.exists()

        profile_result["roots"].append({
            "raw": root_str,
            "expanded": expanded,
            "exists": exists,
            "env_vars": found_vars,
        })
        for v in found_vars:
            env_vars_in_profile.add(v)

    profile_result["env_vars_required"] = sorted(env_vars_in_profile)

    any_root_exists = any(r["exists"] for r in profile_result["roots"])
    if any_root_exists:
        profile_result["can_test_now"] = True
        profile_result["block_reason"] = None
        profile_result["block_class"] = None
    elif env_vars_in_profile:
        unset = [v for v in sorted(env_vars_in_profile) if not os.environ.get(v)]
        profile_result["can_test_now"] = False
        profile_result["block_reason"] = f"env_var_not_set: {unset}"
        profile_result["block_class"] = "environment_missing"
    elif profile_result["roots"]:
        profile_result["can_test_now"] = False
        profile_result["block_reason"] = "path_not_found_locally (no env vars, just missing dir)"
        profile_result["block_class"] = "repo_missing"
    else:
        profile_result["can_test_now"] = False
        profile_result["block_reason"] = "no_content_roots_defined"
        profile_result["block_class"] = "profile_config_error"

    results.append(profile_result)

testable = [r for r in results if r["can_test_now"]]
blocked = [r for r in results if not r["can_test_now"]]

unique_env_vars = set()
for r in blocked:
    for v in r["env_vars_required"]:
        unique_env_vars.add(v)

print(f"Total profiles: {len(results)}")
print(f"Testable now: {len(testable)} -> {[r['site_id'] for r in testable]}")
print(f"Blocked: {len(blocked)}")
print(f"Unique env vars required: {sorted(unique_env_vars)}")
print()
for r in blocked[:3]:
    print(f"  {r['site_id']}: {r['block_reason']}")
    for root in r["roots"]:
        print(f"    raw: {root['raw'][:100]}")

# Check if content repos exist locally at common paths
print("\nSearching for common content repo patterns on D: drive...")
d_content_dirs = []
d_base = Path("D:/")
if d_base.exists():
    for child in d_base.iterdir():
        if child.is_dir() and any(k in child.name.lower() for k in ["aspose", "content", "hugo"]):
            d_content_dirs.append(str(child))
print(f"  D: dirs matching aspose/content/hugo: {d_content_dirs[:5]}")

EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
out_path = EVIDENCE_DIR / "content_root_requirements.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump({
        "total_profiles": len(results),
        "testable_count": len(testable),
        "testable_site_ids": [r["site_id"] for r in testable],
        "blocked_count": len(blocked),
        "block_classes": {
            cls: sum(1 for r in blocked if r.get("block_class") == cls)
            for cls in ["environment_missing", "repo_missing", "profile_config_error"]
        },
        "unique_env_vars_required": sorted(unique_env_vars),
        "env_var_recommendation": (
            "Set ASPOSE_NET_CONTENT and ASPOSE_ORG_CONTENT to local clone paths "
            "to enable production profile testing. "
            "These repos appear to be external and not present on this machine."
        ),
        "d_content_dirs_found": d_content_dirs[:10],
        "profiles": results,
    }, f, indent=2, default=str)
print(f"\nWritten: {out_path}")
