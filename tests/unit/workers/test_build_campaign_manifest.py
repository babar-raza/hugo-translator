"""TC-APT-002: governed full-portfolio discovery and manifest generalization."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import scripts.campaign.build_campaign_manifest as builder
from src.utils.models import BodyRules, OutputLayout, SiteProfile
from src.workers.campaign_manifest import CampaignManifest

KNOWN = ("ar", "bg", "de", "en", "fr")  # bg plays the profile-excluded legacy locale


def _folder_profile(root: Path) -> SiteProfile:
    return SiteProfile(
        site_id="docs.test.org",
        content_roots=[str(root)],
        default_source_lang="en",
        target_langs=["ar", "de", "fr"],
        body=BodyRules(translate_markdown=True),
        output_layout=OutputLayout(per_language_folders=True, pattern="{lang}/{path}"),
        strict_locale_allowlist=True,
    )


def _blog_profile(root: Path) -> SiteProfile:
    return SiteProfile(
        site_id="blog.test.org",
        content_roots=[str(root)],
        default_source_lang="en",
        target_langs=["ar", "de", "fr"],
        body=BodyRules(translate_markdown=True),
        output_layout=OutputLayout(per_language_folders=False, pattern="{filename}.{lang}{ext}"),
        strict_locale_allowlist=True,
    )


def _touch(path: Path, text: str = "---\ntitle: t\n---\nbody\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture()
def content_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "aspose.org"
    docs = repo / "content/docs.test.org"
    _touch(docs / "en/_index.md")
    _touch(docs / "en/cells/_index.md")
    _touch(docs / "en/cells/net/getting-started.md")
    _touch(docs / "en/cells/net/deep/nested/page.md")
    _touch(docs / "en/words/python/intro.md")
    _touch(docs / "de/cells/net/getting-started.md")  # existing target
    _touch(docs / "bg/cells/net/getting-started.md")  # legacy excluded locale (not a source)
    _touch(docs / "bg/cells/net/other.md")
    blog = repo / "content/blog.test.org"
    _touch(blog / "archive.md")
    _touch(blog / "archive.bg.md")  # legacy excluded-locale sibling: NOT a source
    _touch(blog / "archive.de.md")  # existing target
    _touch(blog / "cells/net/_index.md")
    _touch(blog / "cells/net/my-post/index.md")
    _touch(blog / "cells/net/my-post/index.fr.md")
    return repo


def test_family_platform_derivation():
    fp = builder.family_platform
    assert fp(("en", "cells", "net", "a.md"), per_language_folders=True, source_lang="en") == (
        "cells",
        "net",
    )
    assert fp(
        ("en", "cells", "net", "deep", "x", "a.md"), per_language_folders=True, source_lang="en"
    ) == ("cells", "net")
    assert fp(("en", "cells", "_index.md"), per_language_folders=True, source_lang="en") == (
        "cells",
        "",
    )
    assert fp(("en", "_index.md"), per_language_folders=True, source_lang="en") == ("", "")
    assert fp(
        ("cells", "net", "post", "index.md"), per_language_folders=False, source_lang="en"
    ) == ("cells", "net")
    assert fp(("archive.md",), per_language_folders=False, source_lang="en") == ("", "")


def test_folder_site_discovery_is_governed(content_repo):
    profile = _folder_profile(content_repo / "content/docs.test.org")
    sources, facts = builder.discover_sources(content_repo, profile, KNOWN)
    paths = sorted(s["source_path"] for s in sources)
    assert paths == [
        "content/docs.test.org/en/_index.md",
        "content/docs.test.org/en/cells/_index.md",
        "content/docs.test.org/en/cells/net/deep/nested/page.md",
        "content/docs.test.org/en/cells/net/getting-started.md",
        "content/docs.test.org/en/words/python/intro.md",
    ]
    gs = next(s for s in sources if s["source_path"].endswith("getting-started.md"))
    assert (gs["family"], gs["platform"]) == ("cells", "net")
    # outputs come from the engine's own resolver, one per allowlisted locale only
    assert gs["outputs"] == {
        "ar": "content/docs.test.org/ar/cells/net/getting-started.md",
        "de": "content/docs.test.org/de/cells/net/getting-started.md",
        "fr": "content/docs.test.org/fr/cells/net/getting-started.md",
    }
    assert len(gs["source_sha256"]) == 64
    assert facts["layout"] == "per_language_folders"
    assert facts["markdown_files_seen"] == 8
    assert facts["excluded_locale_legacy_files"] == {"bg": 2}


def test_blog_site_discovery_excludes_all_known_language_suffixes(content_repo):
    profile = _blog_profile(content_repo / "content/blog.test.org")
    sources, facts = builder.discover_sources(content_repo, profile, KNOWN)
    paths = sorted(s["source_path"] for s in sources)
    # archive.bg.md (excluded legacy locale) and archive.de.md / index.fr.md (targets) are not sources
    assert paths == [
        "content/blog.test.org/archive.md",
        "content/blog.test.org/cells/net/_index.md",
        "content/blog.test.org/cells/net/my-post/index.md",
    ]
    post = next(s for s in sources if s["source_path"].endswith("my-post/index.md"))
    assert (post["family"], post["platform"]) == ("cells", "net")
    assert post["outputs"]["fr"] == "content/blog.test.org/cells/net/my-post/index.fr.md"
    assert facts["excluded_locale_legacy_files"] == {"bg": 1}


def test_inventory_counts_cells_existing_targets_and_reconciles(
    content_repo, tmp_path, monkeypatch
):
    profiles = {
        "docs.test.org": _folder_profile(content_repo / "content/docs.test.org"),
        "blog.test.org": _blog_profile(content_repo / "content/blog.test.org"),
    }
    monkeypatch.setattr(
        builder, "PLAN_SECTION4_ESTIMATE", {"docs.test.org": 4, "blog.test.org": 10}
    )
    inventory, sources = builder.build_inventory(content_repo, tmp_path, profiles, KNOWN)
    assert inventory["locale_set_consistent_across_sites"] is True
    assert inventory["portfolio_target_langs"] == ["ar", "de", "fr"]
    docs = inventory["sites"]["docs.test.org"]
    assert docs["source_count"] == 5 and docs["cell_count"] == 15
    assert docs["existing_targets_by_lang"] == {"ar": 0, "de": 1, "fr": 0}
    assert docs["missing_target_cells"] == 14
    assert docs["families"]["cells"]["platforms"] == {"": 1, "net": 2}
    assert docs["families"][""]["source_count"] == 1
    # 5 vs estimate 4 = +25% -> investigate; blog 3 vs 10 -> investigate
    assert docs["reconciliation_vs_plan_section4"]["disposition"] == "investigate"
    blog = inventory["sites"]["blog.test.org"]
    assert blog["existing_targets_by_lang"] == {"ar": 0, "de": 1, "fr": 1}
    assert inventory["totals"] == {
        "source_count": 8,
        "cell_count": 24,
        "existing_target_cells": 3,
        "missing_target_cells": 21,
        "plan_section4_source_estimate": 14,
    }
    assert inventory["content_repo_sha"] is None  # not a git checkout: recorded, never fabricated
    assert len(sources) == 8


def test_out_of_scope_site_is_refused(tmp_path):
    with pytest.raises(builder.DiscoveryError):
        builder.load_profiles(tmp_path, tmp_path, ["www.aspose.org"])


def _write_config(root: Path, sites: list[str]) -> None:
    for rel in builder.CONFIG_FINGERPRINT_SHARED:
        _touch(root / rel, f"# {rel}\n")
    _touch(root / "config/site_profiles/default.yaml", "dead: yes\n")
    for site in sites:
        _touch(root / "config/site_profiles" / f"{site}.yaml", f"site_id: {site}\n")


def test_config_fingerprint_excludes_dead_default_yaml_but_binds_profiles(tmp_path):
    _write_config(tmp_path, ["docs.test.org"])
    baseline = builder.config_fingerprint(tmp_path, ["docs.test.org"])
    (tmp_path / "config/site_profiles/default.yaml").write_text("dead: changed\n", encoding="utf-8")
    assert builder.config_fingerprint(tmp_path, ["docs.test.org"]) == baseline  # G-08
    (tmp_path / "config/site_profiles/docs.test.org.yaml").write_text(
        "site_id: docs.test.org\nx: 1\n", encoding="utf-8"
    )
    assert builder.config_fingerprint(tmp_path, ["docs.test.org"]) != baseline
    (tmp_path / "config/terminology/technical_terms.yaml").write_text(
        "terms: [x]\n", encoding="utf-8"
    )
    assert builder.config_fingerprint(tmp_path, ["docs.test.org"]) != baseline


def test_apply_scope_filters_and_orders():
    src = [
        {
            "site_id": "a",
            "family": "cells",
            "platform": "net",
            "source_path": "content/a/en/cells/net/2.md",
            "wave": 1,
            "outputs": {},
        },
        {
            "site_id": "a",
            "family": "cells",
            "platform": "net",
            "source_path": "content/a/en/cells/net/1.md",
            "wave": 0,
            "outputs": {},
        },
        {
            "site_id": "a",
            "family": "words",
            "platform": "net",
            "source_path": "content/a/en/words/net/1.md",
            "wave": 0,
            "outputs": {},
        },
    ]
    out = builder.apply_scope(src, families=["cells"])
    assert [s["source_path"] for s in out] == [
        "content/a/en/cells/net/1.md",
        "content/a/en/cells/net/2.md",
    ]
    assert builder.apply_scope(src, source_prefixes=["content/a/en/words"])[0]["family"] == "words"
    assert len(builder.apply_scope(src, max_sources=1)) == 1
    assert builder.apply_scope(src, source_list=["content/a/en/cells/net/2.md"])[0]["wave"] == 1


def test_manifest_loads_and_validates_as_zero_defect(content_repo, tmp_path, monkeypatch):
    translator = tmp_path / "translator"
    _write_config(translator, ["docs.test.org"])
    _touch(translator / "config/model_registry.yaml", "models: {}\n")
    monkeypatch.setattr(builder, "git_sha", lambda repo: "f" * 40)
    monkeypatch.setattr(builder, "fingerprint_files", lambda *_a, **_k: "c" * 64)
    monkeypatch.setattr(
        builder, "tm_fingerprint_inputs", lambda _repo: ["data/tm/l2.lmdb/data.mdb"]
    )
    profile = _folder_profile(content_repo / "content/docs.test.org")
    sources, _ = builder.discover_sources(content_repo, profile, KNOWN)
    manifest = builder.build_manifest(
        content_repo=content_repo,
        translator_repo=translator,
        campaign_id="unit-canary",
        sources=builder.apply_scope(sources, families=["cells"]),
        target_locales=["ar", "de", "fr"],
        sites=["docs.test.org"],
        locales=["de"],
    )
    assert manifest["target_locales"] == ["de"]
    assert manifest["expected_source_count"] == 3 and manifest["expected_output_count"] == 3
    assert manifest["commit_policy"] == {
        "branch": "main",
        "max_outputs_per_commit": 250,
        "push": False,
        "enabled": False,
    }
    out = tmp_path / "manifest.yaml"
    out.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    loaded = CampaignManifest.load(out)  # runs validate_schema()
    assert loaded.validation_policy == "zero-defect"
    assert loaded.expected_output_count == 3
    with pytest.raises(builder.DiscoveryError):
        builder.build_manifest(
            content_repo=content_repo,
            translator_repo=translator,
            campaign_id="x",
            sources=sources,
            target_locales=["ar", "de", "fr"],
            sites=["docs.test.org"],
            locales=["bg"],
        )


def test_missing_only_manifest_excludes_existing_targets(content_repo, tmp_path, monkeypatch):
    translator = tmp_path / "translator"
    _write_config(translator, ["docs.test.org"])
    _touch(translator / "config/model_registry.yaml", "models: {}\n")
    monkeypatch.setattr(builder, "git_sha", lambda repo: "f" * 40)
    monkeypatch.setattr(builder, "fingerprint_files", lambda *_a, **_k: "c" * 64)
    monkeypatch.setattr(
        builder, "tm_fingerprint_inputs", lambda _repo: ["data/tm/l2.lmdb/data.mdb"]
    )
    profile = _folder_profile(content_repo / "content/docs.test.org")
    sources, _ = builder.discover_sources(content_repo, profile, KNOWN)
    manifest = builder.build_manifest(
        content_repo=content_repo,
        translator_repo=translator,
        campaign_id="missing-only",
        sources=sources,
        target_locales=["ar", "de", "fr"],
        sites=["docs.test.org"],
        missing_only=True,
    )
    assert manifest["expected_source_count"] == 5
    assert manifest["expected_output_count"] == 14
    getting_started = next(
        item for item in manifest["sources"] if item["source_path"].endswith("getting-started.md")
    )
    assert getting_started["outputs"] == {
        "ar": "content/docs.test.org/ar/cells/net/getting-started.md",
        "fr": "content/docs.test.org/fr/cells/net/getting-started.md",
    }
    out = tmp_path / "missing-only.yaml"
    out.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    loaded = CampaignManifest.load(out)
    assert loaded.expected_output_count == 14
    assert sum(
        len(shard["jobs"])
        for shard in loaded.shards(resume_receipts=set(), max_outputs=250)
    ) == 14


def test_build_manifest_primary_model_swaps_escalation(content_repo, tmp_path, monkeypatch):
    """TC-APT-039: primary_model="professionalize_llm" flips the escalation target to
    m2m100_418m, and the resulting manifest still validates as zero-defect."""
    translator = tmp_path / "translator"
    _write_config(translator, ["docs.test.org"])
    _touch(translator / "config/model_registry.yaml", "models: {}\n")
    monkeypatch.setattr(builder, "git_sha", lambda repo: "f" * 40)
    monkeypatch.setattr(builder, "fingerprint_files", lambda *_a, **_k: "c" * 64)
    monkeypatch.setattr(
        builder, "tm_fingerprint_inputs", lambda _repo: ["data/tm/l2.lmdb/data.mdb"]
    )
    profile = _folder_profile(content_repo / "content/docs.test.org")
    sources, _ = builder.discover_sources(content_repo, profile, KNOWN)
    manifest = builder.build_manifest(
        content_repo=content_repo,
        translator_repo=translator,
        campaign_id="unit-llm-primary",
        sources=builder.apply_scope(sources, families=["cells"]),
        target_locales=["ar", "de", "fr"],
        sites=["docs.test.org"],
        locales=["de"],
        primary_model="professionalize_llm",
    )
    assert manifest["retry_policy"]["primary_model"] == "professionalize_llm"
    assert manifest["retry_policy"]["llm_model"] == "m2m100_418m"
    out = tmp_path / "manifest.yaml"
    out.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    loaded = CampaignManifest.load(out)  # runs validate_schema()
    assert loaded.retry_policy["primary_model"] == "professionalize_llm"

    with pytest.raises(builder.DiscoveryError):
        builder.build_manifest(
            content_repo=content_repo,
            translator_repo=translator,
            campaign_id="unit-bad-primary",
            sources=sources,
            target_locales=["ar", "de", "fr"],
            sites=["docs.test.org"],
            locales=["de"],
            primary_model="not_a_real_model",
        )


def test_build_manifest_can_defer_llm_escalation(content_repo, tmp_path, monkeypatch):
    translator = tmp_path / "translator"
    _write_config(translator, ["docs.test.org"])
    _touch(translator / "config/model_registry.yaml", "models: {}\n")
    monkeypatch.setattr(builder, "git_sha", lambda repo: "f" * 40)
    monkeypatch.setattr(builder, "fingerprint_files", lambda *_a, **_k: "c" * 64)
    monkeypatch.setattr(builder, "tm_fingerprint_inputs", lambda _repo: ["data/tm/l2.lmdb/data.mdb"])
    profile = _folder_profile(content_repo / "content/docs.test.org")
    sources, _ = builder.discover_sources(content_repo, profile, KNOWN)
    manifest = builder.build_manifest(
        content_repo=content_repo,
        translator_repo=translator,
        campaign_id="unit-deferred-llm",
        sources=sources,
        target_locales=["ar", "de", "fr"],
        sites=["docs.test.org"],
        llm_escalation_mode="deferred",
    )
    assert manifest["retry_policy"]["llm_escalation_attempts"] == 0
    assert manifest["retry_policy"]["llm_escalation_mode"] == "deferred"


def test_build_manifest_can_use_1_2b_m2m(content_repo, tmp_path, monkeypatch):
    translator = tmp_path / "translator"
    _write_config(translator, ["docs.test.org"])
    _touch(translator / "config/model_registry.yaml", "models: {}\n")
    monkeypatch.setattr(builder, "git_sha", lambda repo: "f" * 40)
    monkeypatch.setattr(builder, "fingerprint_files", lambda *_a, **_k: "c" * 64)
    monkeypatch.setattr(builder, "tm_fingerprint_inputs", lambda _repo: ["data/tm/l2.lmdb/data.mdb"])
    profile = _folder_profile(content_repo / "content/docs.test.org")
    sources, _ = builder.discover_sources(content_repo, profile, KNOWN)
    manifest = builder.build_manifest(
        content_repo=content_repo,
        translator_repo=translator,
        campaign_id="unit-1-2b",
        sources=sources,
        target_locales=["ar", "de", "fr"],
        sites=["docs.test.org"],
        primary_model="m2m100_1.2b",
        llm_escalation_mode="deferred",
    )
    assert manifest["retry_policy"]["primary_model"] == "m2m100_1.2b"


def test_tm_fingerprint_inputs_require_l2_and_include_present_l3(tmp_path):
    with pytest.raises(builder.DiscoveryError):
        builder.tm_fingerprint_inputs(tmp_path)
    _touch(tmp_path / "data/tm/l2.lmdb/data.mdb", "x")
    assert builder.tm_fingerprint_inputs(tmp_path) == ["data/tm/l2.lmdb/data.mdb"]
    _touch(tmp_path / "data/tm/l3_faiss/index.faiss", "y")
    assert builder.tm_fingerprint_inputs(tmp_path) == [
        "data/tm/l2.lmdb/data.mdb",
        "data/tm/l3_faiss/index.faiss",
    ]
