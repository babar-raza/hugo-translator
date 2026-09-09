"""TC-APT-005 (plan G-02): NLLB-200 is permanent non-use -- no manifest or routing rule can select it."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

from src.utils import model_licensing as ml
from src.utils.config_loader import ConfigLoadError, ConfigService

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def raw_global() -> dict:
    return yaml.safe_load((REPO_ROOT / "config/global.yaml").read_text(encoding="utf-8"))


def test_global_yaml_records_permanent_non_use(raw_global):
    assert raw_global["model_licensing"]["nllb_200"]["production_approved"] is False
    assert ml.nllb_production_approved(raw_global) is False


def test_global_yaml_has_no_nllb_routing_rule(raw_global):
    assert ml.routing_violations(raw_global) == []
    te = raw_global["translation_engine"]
    assert not any(ml.is_nllb(v) for v in (te.get("language_routing_overrides") or {}).values())
    dumped = yaml.safe_dump(te.get("zero_defect_frontmatter_retry_models") or {})
    assert "nllb" not in dumped.lower()
    assert not ml.is_nllb(te.get("llm_escalation_model"))


def test_config_service_refuses_nllb_routing(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "site_profiles").mkdir()
    (cfg / "global.yaml").write_text(
        yaml.safe_dump(
            {"translation_engine": {"language_routing_overrides": {"ko": "nllb_200_1.3b"}}}
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigLoadError, match="nllb_200_1.3b"):
        ConfigService(cfg)
    # explicit approval flips the gate (the only sanctioned way back in)
    (cfg / "global.yaml").write_text(
        yaml.safe_dump(
            {
                "model_licensing": {"nllb_200": {"production_approved": True}},
                "translation_engine": {"language_routing_overrides": {"ko": "nllb_200_1.3b"}},
            }
        ),
        encoding="utf-8",
    )
    ConfigService(cfg)  # loads


def test_model_loader_refuses_nllb_when_unapproved():
    from src.model_runtime.loader import ModelLoader

    registry = Mock()
    loader = ModelLoader(registry, config={})
    with pytest.raises(ml.ModelLicensingError):
        loader.load_model("nllb_200_600m")
    registry.get_model.assert_not_called()


def test_model_loader_allows_nllb_only_with_explicit_approval(monkeypatch):
    from src.model_runtime.loader import ModelLoader

    registry = Mock()
    loader = ModelLoader(
        registry, config={"model_licensing": {"nllb_200": {"production_approved": True}}}
    )
    backend = Mock()
    monkeypatch.setattr(loader, "_create_backend", lambda info, device: backend)
    assert loader.load_model("nllb_200_600m") is backend


def test_campaign_manifest_rejects_nllb_primary(tmp_path):
    from src.workers.campaign_manifest import CampaignManifest, CampaignManifestError

    manifest = {
        "schema_version": 1,
        "campaign_id": "x",
        "validation_policy": "zero-defect",
        "content_repo": str(tmp_path),
        "content_repo_sha": "a" * 40,
        "translator_repo_sha": "b" * 40,
        "config_fingerprint": "c" * 64,
        "model_fingerprints": {"model_registry": "d" * 64},
        "tm_fingerprint": "e" * 64,
        "knowledge_fingerprints": {},
        "target_locales": ["de"],
        "expected_source_count": 0,
        "expected_output_count": 0,
        "retry_policy": {
            "primary_model": "nllb_200_1.3b",
            "primary_attempts": 3,
            "llm_escalation_attempts": 2,
            "llm_model": "professionalize_llm",
        },
        "commit_policy": {
            "branch": "main",
            "max_outputs_per_commit": 250,
            "push": False,
            "enabled": False,
        },
        "execution_policy": {"max_parallel_jobs": 1, "model_sharing": "single_shared_instance"},
        "sources": [],
    }
    path = tmp_path / "m.yaml"
    path.write_text(yaml.safe_dump(manifest), encoding="utf-8")
    with pytest.raises(CampaignManifestError, match="M2M100 primary"):
        CampaignManifest.load(path)


def test_routing_violation_scanner_covers_nested_retry_models():
    cfg = {
        "translation_engine": {
            "zero_defect_frontmatter_retry_models": {
                "blog.aspose.org": {"de": {"title": "nllb_200_1.3b"}}
            }
        }
    }
    found = ml.routing_violations(cfg)
    assert len(found) == 1 and "blog.aspose.org.de.title" in found[0]
