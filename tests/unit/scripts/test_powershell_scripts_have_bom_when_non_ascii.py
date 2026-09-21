"""TC-APT-086: a BOM-less UTF-8 .ps1 file containing non-ASCII characters can
silently fail to parse under Windows PowerShell 5.1.

Found 2026-09-06 investigating a stale-path bug in
tests/unit/scripts/test_check_worker_health_status.ps1: fixing the path
revealed the TARGET script itself, scripts/ops/check_worker_health.ps1,
could not be parsed at all -- confirmed directly with
[System.Management.Automation.Language.Parser]::ParseFile, and confirmed the
mechanism by writing a UTF-8-BOM copy of the identical content, which parsed
cleanly. Without a BOM, Windows PowerShell 5.1 falls back to the system
codepage to decode the file; the byte sequence for an em dash (U+2014,
E2 80 94 in UTF-8) decodes under a Windows-125x codepage into characters
that corrupt the tokenizer -- unpredictably, since it depends on exactly
where the corrupted bytes land, which is why 5 of 8 non-ASCII .ps1 files in
this tree happened to still parse and 3 did not
(check_reference_sample.ps1, check_worker_health.ps1, verify_workers.ps1,
all fixed alongside this test).

This is a static, portable check (no PowerShell invocation needed): every
tracked .ps1 file containing a byte with the high bit set must start with
the UTF-8 BOM (EF BB BF). A file with no non-ASCII bytes at all is exempt --
plain ASCII decodes identically under every codepage.
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent.parent
UTF8_BOM = b"\xef\xbb\xbf"


def _tracked_ps1_files() -> list[Path]:
    return sorted((REPO_ROOT / "scripts").rglob("*.ps1"))


@pytest.mark.parametrize("path", _tracked_ps1_files(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_non_ascii_ps1_file_has_a_utf8_bom(path: Path):
    raw = path.read_bytes()
    has_non_ascii = any(byte > 0x7F for byte in raw)
    if not has_non_ascii:
        pytest.skip("pure ASCII -- codepage-independent, no BOM needed")
    assert raw.startswith(UTF8_BOM), (
        f"{path.relative_to(REPO_ROOT)} contains non-ASCII bytes but has no UTF-8 BOM -- "
        "Windows PowerShell 5.1 may misdecode it under the system codepage and fail to "
        "parse (TC-APT-086). Add a BOM: read as UTF-8, rewrite with codecs.BOM_UTF8 prefixed."
    )
