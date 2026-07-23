"""
Registry consistency lint: every site profile's output_layout.pattern must
be structurally consistent with its output_layout.per_language_folders
value. `pattern` is free-text and nothing generically parses/validates it
against the boolean (confirmed during the durable-fix investigation:
golden-test.yaml and ws5-test.yaml both had per_language_folders=false
paired with a per_language_folders=true-shaped pattern string, undetected
until a human happened to notice). This test is the regression control
that would have caught that drift, and prevents it recurring silently for
any future profile edit.
"""
from pathlib import Path

import pytest
import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_SITE_PROFILES_DIR = _PROJECT_ROOT / "config" / "site_profiles"

# Placeholder tokens that only make sense for a directory-per-language
# layout (per_language_folders=True) vs. a file-suffix layout
# (per_language_folders=False). A pattern using the "wrong" family's tokens
# for its declared per_language_folders value is stale/inconsistent.
_DIRSCHEME_TOKENS = ("{path}", "{relative_path}")
_FILESCHEME_TOKENS = ("{filename}", "{path_stem}", "{ext}")


def _all_profile_paths() -> list[Path]:
    return sorted(_SITE_PROFILES_DIR.glob("*.yaml"))


@pytest.mark.parametrize(
    "profile_path", _all_profile_paths(), ids=lambda p: p.stem
)
def test_pattern_consistent_with_per_language_folders(profile_path):
    with open(profile_path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    output_layout = data.get("output_layout")
    if not output_layout:
        pytest.skip(f"{profile_path.name}: no output_layout section")

    per_language_folders = output_layout.get("per_language_folders", False)
    pattern = output_layout.get("pattern")
    if not pattern:
        pytest.skip(f"{profile_path.name}: no pattern set")

    has_dirscheme_token = any(tok in pattern for tok in _DIRSCHEME_TOKENS)
    has_filescheme_token = any(tok in pattern for tok in _FILESCHEME_TOKENS)

    if per_language_folders:
        assert not has_filescheme_token, (
            f"{profile_path.name}: per_language_folders=true but pattern "
            f"{pattern!r} uses file-suffix-only tokens {_FILESCHEME_TOKENS}"
        )
    else:
        assert not has_dirscheme_token, (
            f"{profile_path.name}: per_language_folders=false but pattern "
            f"{pattern!r} uses directory-layout-only tokens {_DIRSCHEME_TOKENS}"
        )
