from pathlib import Path

from scripts.campaign.build_aspose_foss_pilot_manifest import (
    FOLDER_SURFACES,
    _config_fingerprint,
)


def _write_required_config(root: Path) -> None:
    paths = [
        Path("config/global.yaml"),
        Path("config/validation.yaml"),
        Path("config/terminology.yaml"),
        Path("config/terminology/technical_terms.yaml"),
        Path("config/site_profiles/default.yaml"),
        Path("config/site_profiles/blog.aspose.org.yaml"),
        *[
            Path("config/site_profiles") / f"{site}.yaml"
            for site, _ in FOLDER_SURFACES
        ],
    ]
    for index, relative in enumerate(paths):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"value: {index}\n", encoding="utf-8")


def test_config_fingerprint_binds_validation_and_terminology(tmp_path):
    _write_required_config(tmp_path)
    baseline = _config_fingerprint(tmp_path)

    validation = tmp_path / "config/validation.yaml"
    validation.write_text("value: changed\n", encoding="utf-8")
    after_validation = _config_fingerprint(tmp_path)

    terminology = tmp_path / "config/terminology/technical_terms.yaml"
    terminology.write_text("terms: [changed]\n", encoding="utf-8")
    after_terminology = _config_fingerprint(tmp_path)

    assert after_validation != baseline
    assert after_terminology != after_validation


def test_config_fingerprint_binds_default_profile(tmp_path):
    _write_required_config(tmp_path)
    baseline = _config_fingerprint(tmp_path)

    default_profile = tmp_path / "config/site_profiles/default.yaml"
    default_profile.write_text("value: changed\n", encoding="utf-8")

    assert _config_fingerprint(tmp_path) != baseline
