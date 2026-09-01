"""
CLI-level enforcement of the strict_locale_allowlist mechanism (scenario:
manual locale requests must reject every unsupported locale via
`--target-langs`, for sites that opt in).

Uses isolated, synthetic, non-Aspose site profiles under a temporary
--config-root so these tests never touch real production content,
progress state, or the shared TM database — only the CLI's locale-policy
guard (added immediately after args.target_langs resolution in
translate_site()) is under test here. Using a from-scratch site name
(not Aspose-anything) directly proves the mechanism is generic: any site
gets the same enforcement purely by setting strict_locale_allowlist: true
and target_langs in its own profile YAML.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_STRICT_SITE_ID = "unit-test-strict-fixture.example.org"
_LENIENT_SITE_ID = "unit-test-lenient-fixture.example.org"

_STRICT_PROFILE_YAML = """\
site_id: {site_id}
content_roots:
- {content_root}
default_source_lang: en
target_langs:
- de
- fr
- ja
body:
  translate_markdown: true
autonomous_enabled: false
strict_locale_allowlist: true
"""

_LENIENT_PROFILE_YAML = """\
site_id: {site_id}
content_roots:
- {content_root}
default_source_lang: en
target_langs:
- de
- fr
- ja
body:
  translate_markdown: true
autonomous_enabled: false
"""


def _write_profile(config_root: Path, site_id: str, content_root: Path, template: str) -> None:
    (config_root / "site_profiles").mkdir(parents=True, exist_ok=True)
    (config_root / "site_profiles" / f"{site_id}.yaml").write_text(
        template.format(
            site_id=site_id,
            content_root=str(content_root).replace("\\", "/"),
        ),
        encoding="utf-8",
    )


@pytest.fixture
def strict_config_root(tmp_path: Path) -> Path:
    content_root = tmp_path / "strict_content"
    content_root.mkdir()
    config_root = tmp_path / "strict_config"
    _write_profile(config_root, _STRICT_SITE_ID, content_root, _STRICT_PROFILE_YAML)
    return config_root


@pytest.fixture
def lenient_config_root(tmp_path: Path) -> Path:
    content_root = tmp_path / "lenient_content"
    content_root.mkdir()
    config_root = tmp_path / "lenient_config"
    _write_profile(config_root, _LENIENT_SITE_ID, content_root, _LENIENT_PROFILE_YAML)
    return config_root


def _run_cli(
    config_root: Path, site_id: str, *extra_args: str, timeout: int = 60
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable, "-m", "src.cli",
            "--site", site_id,
            "--config-root", str(config_root),
            *extra_args,
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(Path(__file__).resolve().parents[2]),
    )


def test_strict_site_rejects_unsupported_locale_with_nonzero_exit(strict_config_root):
    result = _run_cli(strict_config_root, _STRICT_SITE_ID, "--target-langs", "bg")
    assert result.returncode != 0
    assert "not in the allowed locale set" in result.stderr
    assert "bg" in result.stderr


def test_strict_site_reports_only_the_unsupported_locale_among_several(strict_config_root):
    result = _run_cli(strict_config_root, _STRICT_SITE_ID, "--target-langs", "de", "bg", "fr")
    assert result.returncode != 0
    assert "bg" in result.stderr
    assert "not in the allowed locale set" in result.stderr


def test_strict_site_approved_locale_passes_the_policy_check(strict_config_root):
    # May still fail downstream for unrelated reasons (no real content,
    # no models loaded in this test environment) — what matters is that
    # it never fails on the locale-policy check itself.
    result = _run_cli(strict_config_root, _STRICT_SITE_ID, "--target-langs", "de", "--dry-run")
    assert "not in the allowed locale set" not in result.stderr
    assert "not in the allowed locale set" not in result.stdout


def test_lenient_site_does_not_reject_unsupported_locale(lenient_config_root):
    # strict_locale_allowlist is unset (defaults False) for this fixture --
    # the same locale ("bg") that a strict site would reject must NOT be
    # rejected here, proving the mechanism is opt-in, not universal.
    result = _run_cli(lenient_config_root, _LENIENT_SITE_ID, "--target-langs", "bg", "--dry-run")
    assert "not in the allowed locale set" not in result.stderr
    assert "not in the allowed locale set" not in result.stdout
