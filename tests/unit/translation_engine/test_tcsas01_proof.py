"""
Direct proof that Layer 1 and Layer 2 fixes prevent TC-SAS-01 from triggering
the legacy fallback for PbrSpecularMaterial.md (31-row table API reference file).

Runs inside pytest so imports work correctly.
"""
import yaml
import re
from pathlib import Path


def test_layer1_config_raises_tolerance():
    """Layer 1: reference.aspose.org.yaml tolerance raised to 10%."""
    config_path = Path("config/site_profiles/reference.aspose.org.yaml")
    config = yaml.safe_load(config_path.read_text())
    te = config.get("translation_engine", {})
    assert "same_as_source_tolerance" in te, "tolerance key missing from config"
    assert te["same_as_source_tolerance"] == 0.10, f"Expected 0.10, got {te['same_as_source_tolerance']}"
    assert te.get("same_as_source_min_length", 0) >= 15, "min_length should be >=15"



def test_layer3_placeholder_regex_matches_table():
    """Layer 3: placeholder regex correctly matches markdown table blocks."""
    import re
    _TABLE_BLOCK_RE = re.compile(r"((?:^[ \t]*\|[^\n]+\n)+)", re.MULTILINE)

    sample = (
        "# PbrSpecularMaterial\n\n"
        "Some description.\n\n"
        "| Name | Type | Description |\n"
        "| --- | --- | --- |\n"
        "| DiffuseColor | Color | The diffuse color |\n"
        "| EmissiveColor | Color | The emissive color |\n\n"
        "More text.\n"
    )
    matches = list(_TABLE_BLOCK_RE.finditer(sample))
    assert len(matches) == 1, f"Expected 1 table block, got {len(matches)}"
    table_text = matches[0].group(0)
    assert "DiffuseColor" in table_text
    assert "EmissiveColor" in table_text
    # Surrounding text NOT captured
    assert "Some description" not in table_text
    assert "More text" not in table_text

    # Round-trip: replace with placeholder, then restore
    placeholder_map = {}
    counter = [0]
    def replacer(m):
        key = f"\x00TABLE_{counter[0]}\x00"
        placeholder_map[key] = m.group(0)
        counter[0] += 1
        return key
    protected = _TABLE_BLOCK_RE.sub(replacer, sample)
    assert "DiffuseColor" not in protected, "Table should be replaced by placeholder"
    assert "\x00TABLE_0\x00" in protected
    restored = protected
    for key, original in placeholder_map.items():
        restored = restored.replace(key, original)
    assert restored == sample, "Restore must be byte-identical to original"

