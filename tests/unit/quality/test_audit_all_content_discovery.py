"""
Golden/regression test for scripts/quality/audit_all_content.py's
registry-driven discovery (durable-fix: stop treating file-suffix-layout
sites as exceptions).

Before this fix, the script hardcoded a `site_root/en/` + locale-subfolder
walk, silently skipping any per_language_folders=False (file-suffix) site
like blog.aspose.org. This test proves, against synthetic fixtures for both
layout schemes, that:
  1. A directory-scheme (per_language_folders=True) site is scanned exactly
     as before -- no behavior change for the sites already covered.
  2. A file-suffix-scheme (per_language_folders=False) site now produces
     real, non-zero findings instead of being silently skipped.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from src.utils.config_loader import ConfigService

_MODULE_PATH = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "quality"
    / "audit_all_content.py"
)


@pytest.fixture
def audit_module():
    """Load audit_all_content.py fresh so each test gets an isolated module
    (its module-level _CONFIG/SITES are monkeypatched per-test below)."""
    spec = importlib.util.spec_from_file_location(
        "audit_all_content_under_test", _MODULE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    del sys.modules[spec.name]


DIRSCHEME_PROFILE_YAML = """
site_id: test-dirscheme.example
display_name: Directory-scheme test site
content_roots:
- {content_root}
default_source_lang: en
target_langs:
- fr
body:
  translate_markdown: true
output_layout:
  per_language_folders: true
  pattern: '{{lang}}/{{path}}'
autonomous_enabled: true
"""

SUFFIXSCHEME_PROFILE_YAML = """
site_id: test-suffixscheme.example
display_name: File-suffix-scheme test site
content_roots:
- {content_root}
default_source_lang: en
target_langs:
- fr
body:
  translate_markdown: true
output_layout:
  per_language_folders: false
  pattern: '{{filename}}.{{lang}}{{ext}}'
autonomous_enabled: true
"""


@pytest.fixture
def fixture_config(tmp_path):
    """Build a temp config/site_profiles dir with one profile per scheme,
    plus matching synthetic content trees, and a ConfigService over it."""
    config_dir = tmp_path / "config"
    profiles_dir = config_dir / "site_profiles"
    profiles_dir.mkdir(parents=True)

    dir_content_root = tmp_path / "content" / "test-dirscheme.example"
    (dir_content_root / "en").mkdir(parents=True)
    en_body = "# Heading\n\n" + ("This is real English body content. " * 5)
    (dir_content_root / "en" / "index.md").write_text(
        "---\ntitle: Test Page\n---\n" + en_body, encoding="utf-8"
    )
    (dir_content_root / "fr").mkdir(parents=True)
    # Body identical to EN -- should trigger body_identical_to_en.
    (dir_content_root / "fr" / "index.md").write_text(
        "---\ntitle: Test Page\n---\n" + en_body, encoding="utf-8"
    )

    suffix_content_root = tmp_path / "content" / "test-suffixscheme.example"
    suffix_content_root.mkdir(parents=True)
    (suffix_content_root / "index.md").write_text(
        "---\ntitle: Test Page\n---\n" + en_body, encoding="utf-8"
    )
    # Body identical to EN -- should trigger body_identical_to_en, same as
    # the dirscheme case above -- proving parity across both schemes.
    (suffix_content_root / "index.fr.md").write_text(
        "---\ntitle: Test Page\n---\n" + en_body, encoding="utf-8"
    )

    (profiles_dir / "test-dirscheme.example.yaml").write_text(
        DIRSCHEME_PROFILE_YAML.format(content_root=str(dir_content_root)),
        encoding="utf-8",
    )
    (profiles_dir / "test-suffixscheme.example.yaml").write_text(
        SUFFIXSCHEME_PROFILE_YAML.format(content_root=str(suffix_content_root)),
        encoding="utf-8",
    )

    return ConfigService(config_dir)


def _run_scan(audit_module, fixture_config, tmp_path, sites):
    audit_module._CONFIG = fixture_config
    output_path = tmp_path / "audit_out.jsonl"
    audit_module.scan(output_path=str(output_path), sites=sites)
    if not output_path.exists():
        return []
    with open(output_path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


class TestAuditAllContentRegistryDriven:
    def test_dirscheme_site_still_scanned_and_flags_body_identical(
        self, audit_module, fixture_config, tmp_path
    ):
        """Directory-scheme (per_language_folders=True) behavior unchanged:
        the site is scanned and the identical-body issue is caught."""
        records = _run_scan(
            audit_module, fixture_config, tmp_path, ["test-dirscheme.example"]
        )
        assert len(records) == 1
        record = records[0]
        assert record["site_id"] == "test-dirscheme.example"
        assert record["locale"] == "fr"
        issue_types = {i["type"] for i in record["issues"]}
        assert "body_identical_to_en" in issue_types

    def test_suffixscheme_site_no_longer_silently_skipped(
        self, audit_module, fixture_config, tmp_path
    ):
        """File-suffix-scheme (per_language_folders=False) site -- e.g. the
        blog.aspose.org/blog.aspose.net/www.aspose.org/www.aspose.net
        layout -- now produces real findings instead of zero rows."""
        records = _run_scan(
            audit_module, fixture_config, tmp_path, ["test-suffixscheme.example"]
        )
        assert len(records) == 1
        record = records[0]
        assert record["site_id"] == "test-suffixscheme.example"
        assert record["locale"] == "fr"
        issue_types = {i["type"] for i in record["issues"]}
        assert "body_identical_to_en" in issue_types

    def test_both_schemes_scanned_together_with_parity(
        self, audit_module, fixture_config, tmp_path
    ):
        """Scanning both site types in one run yields one record per site,
        with the same issue detected in both -- proving the discovery-layer
        swap treats both schemes as first-class, not one as an exception."""
        records = _run_scan(
            audit_module,
            fixture_config,
            tmp_path,
            ["test-dirscheme.example", "test-suffixscheme.example"],
        )
        assert len(records) == 2
        by_site = {r["site_id"]: r for r in records}
        for site_id in ("test-dirscheme.example", "test-suffixscheme.example"):
            issue_types = {i["type"] for i in by_site[site_id]["issues"]}
            assert "body_identical_to_en" in issue_types
