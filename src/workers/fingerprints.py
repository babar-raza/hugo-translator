"""Profile and protection fingerprints (plan section 7.3; landed with TC-APT-003, reused by TC-APT-007).

Mission ``aspose-org-full-portfolio-translation-20260901``.

Two fingerprints at *different granularities* than the monolithic campaign
``config_fingerprint``:

* ``profile_fingerprint`` -- routing/scope signal, per site: sha256 of the fully resolved
  ``SiteProfile.model_dump()`` (post env-expansion).  Any change (languages, layout,
  validation mode) invalidates every existing target for that site.
* ``protection_fingerprint`` -- masking-rule signal, narrower, per site: sha256 over, in
  order, the frontmatter mode map, the body preserve/placeholder rule lists actually passed
  to ``PlaceholderManager.protect()``, the AST reconstruction switches, the profile's
  terminology block, and the bytes of the four shared terminology artifacts.  A change here
  means the *set of spans masked during original translation* is provably different from
  today's, independent of whether the English text changed.

DECIDED (plan G-08): the dead ``config/site_profiles/default.yaml`` is never an input.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

#: The four shared terminology artifacts hashed into the protection fingerprint.
#: ``protected_terms.yaml`` is confirmed dead code (plan G-11) but is still hashed for
#: completeness so a future revival is detected.
TERMINOLOGY_ARTIFACTS: tuple[str, ...] = (
    "config/terminology.yaml",
    "config/terminology/technical_terms.yaml",
    "config/terminology/protected_terms.yaml",
    "config/terminology/aspose_terms.txt",
)


def _canonical(obj: Any) -> bytes:
    return json.dumps(
        obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str
    ).encode("utf-8")


def _dump(model: Any) -> Any:
    if model is None:
        return None
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    if isinstance(model, dict):
        return model
    return str(model)


def profile_fingerprint(profile: Any) -> str:
    """sha256 of the whole resolved profile (``SiteProfile.model_dump``)."""
    return hashlib.sha256(_canonical(_dump(profile))).hexdigest()


def protection_inputs(profile: Any, translator_repo: Path) -> dict[str, Any]:
    """The exact, ordered inputs to :func:`protection_fingerprint` (inspectable in evidence)."""
    body = getattr(profile, "body", None)
    frontmatter = getattr(profile, "frontmatter", {}) or {}
    artifacts: dict[str, str | None] = {}
    for rel in TERMINOLOGY_ARTIFACTS:
        path = translator_repo / rel
        artifacts[rel] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    return {
        "frontmatter_modes": {
            str(field): {
                "mode": getattr(rule, "mode", None),
                "strategy": getattr(rule, "strategy", None),
            }
            for field, rule in sorted(frontmatter.items())
        },
        "preserve_blocks": list(getattr(body, "preserve_blocks", []) or []),
        "preserve_patterns": list(getattr(body, "preserve_patterns", []) or []),
        "placeholder_syntax": list(getattr(body, "placeholder_syntax", []) or []),
        "use_ast_body_reconstruction": getattr(body, "use_ast_body_reconstruction", None),
        "ast_segmentation_strategy": getattr(body, "ast_segmentation_strategy", None),
        "terminology": _dump(getattr(profile, "terminology", None)),
        "terminology_artifacts_sha256": artifacts,
    }


def protection_fingerprint(profile: Any, translator_repo: Path) -> str:
    """sha256 over the ordered masking-rule inputs (plan section 7.3)."""
    return hashlib.sha256(_canonical(protection_inputs(profile, translator_repo))).hexdigest()


def site_fingerprints(profile: Any, translator_repo: Path) -> dict[str, str]:
    return {
        "profile_fingerprint": profile_fingerprint(profile),
        "protection_fingerprint": protection_fingerprint(profile, translator_repo),
    }
