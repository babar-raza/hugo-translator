"""Model licensing gate: NLLB-200 permanent non-use (TC-APT-005, plan G-02 / section 6).

Mission ``aspose-org-full-portfolio-translation-20260901``.

Meta's NLLB-200 checkpoints are CC-BY-NC-4.0.  The operator's model strategy (plan
section 6: ``professionalize_llm`` primary, ``m2m100_418m`` automatic fallback) has no role
for them, so the licensing question is closed as **permanent non-use**, not left open.

This module makes that deterministic instead of conventional:

* ``config/global.yaml`` carries ``model_licensing.nllb_200.production_approved: false``;
  :func:`nllb_production_approved` reads it (default: NOT approved).
* :func:`routing_violations` scans every routing surface in the raw global config
  (``language_routing_overrides``, ``zero_defect_frontmatter_retry_models``,
  ``llm_escalation_model``, ``model_defaults``) and reports any NLLB reference while
  unapproved -- ``ConfigService`` refuses to load such a config.
* :func:`assert_model_selectable` is called by ``ModelLoader.load_model`` so an NLLB
  checkpoint can never be instantiated while unapproved, whatever selected it.
* ``CampaignManifest.validate_schema`` already pins the campaign models; the regression
  suite asserts an NLLB primary is rejected there too.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

NLLB_PREFIX = "nllb"
KNOWN_NLLB_MODEL_IDS: frozenset[str] = frozenset({"nllb_200_600m", "nllb_200_1.3b"})
LICENSE_TAG = "CC-BY-NC-4.0"


class ModelLicensingError(RuntimeError):
    """A licensing-blocked model was selected or configured."""


def is_nllb(model_id: Any) -> bool:
    return str(model_id or "").strip().lower().startswith(NLLB_PREFIX)


def nllb_production_approved(raw_config: Mapping[str, Any] | None) -> bool:
    """True only if the config explicitly approves NLLB for production (default False)."""
    if not raw_config:
        return False
    licensing = raw_config.get("model_licensing") or {}
    nllb = licensing.get("nllb_200") or {}
    return nllb.get("production_approved") is True


def _walk_model_refs(node: Any, path: str, out: list[tuple[str, str]]) -> None:
    if isinstance(node, Mapping):
        for key, value in node.items():
            _walk_model_refs(value, f"{path}.{key}" if path else str(key), out)
    elif isinstance(node, (list, tuple)):
        for idx, value in enumerate(node):
            _walk_model_refs(value, f"{path}[{idx}]", out)
    elif isinstance(node, str) and is_nllb(node):
        out.append((path, node))


#: Config paths whose values are model selections (routing surfaces).
ROUTING_SURFACES: tuple[tuple[str, ...], ...] = (
    ("translation_engine", "language_routing_overrides"),
    ("translation_engine", "zero_defect_frontmatter_retry_models"),
    ("translation_engine", "llm_escalation_model"),
    ("model_defaults",),
)


def routing_violations(raw_config: Mapping[str, Any] | None) -> list[str]:
    """Return human-readable violations: NLLB referenced on a routing surface while unapproved."""
    if not raw_config or nllb_production_approved(raw_config):
        return []
    violations: list[str] = []
    for surface in ROUTING_SURFACES:
        node: Any = raw_config
        for key in surface:
            node = node.get(key) if isinstance(node, Mapping) else None
            if node is None:
                break
        if node is None:
            continue
        refs: list[tuple[str, str]] = []
        _walk_model_refs(node, ".".join(surface), refs)
        for path, model_id in refs:
            violations.append(
                f"{path} selects {model_id!r} ({LICENSE_TAG}) but "
                "model_licensing.nllb_200.production_approved is not true (TC-APT-005)"
            )
    return violations


def assert_model_selectable(model_id: str, raw_config: Mapping[str, Any] | None) -> None:
    """Raise :class:`ModelLicensingError` if ``model_id`` is an NLLB checkpoint while unapproved."""
    if is_nllb(model_id) and not nllb_production_approved(raw_config):
        raise ModelLicensingError(
            f"model {model_id!r} is licensing-blocked ({LICENSE_TAG}; plan G-02 closed as "
            "permanent non-use, TC-APT-005). It cannot be loaded unless "
            "model_licensing.nllb_200.production_approved is explicitly true."
        )
