"""VA-02 (TC-APT-105 audit): scripts/audit/detect_duplicate_link_content.py
is a read-only diagnostic -- it must never write to a scanned file, must
never default to a full-repo scan, and must flag the confirmed live defect
shape (an identical link/bold-link construct repeated within one paragraph)
without false-flagging a legitimately-repeated short link in a different
section.
"""

from __future__ import annotations

import json

from scripts.audit.detect_duplicate_link_content import (
    detect_locale,
    find_duplicate_link_matches,
    main,
    scan,
    scan_file,
)

# The confirmed live shape, content/docs.aspose.org/en/cells/go/getting-started/
# quickstart.md (TC-APT-105 original finding).
_GENUINE_DUPLICATE = (
    "See the **[API Reference](https://reference.aspose.org/cells/go)**:"
    "**[API Reference](https://reference.aspose.org/cells/go)**: Full class "
    "and method documentation."
)

_NOT_ADJACENT_DIFFERENT_SECTIONS = """\
## Installation

See the [Installation](https://docs.aspose.org/cells/go/installation/) guide
for setup steps.

## Troubleshooting

If setup fails, revisit the [Installation](https://docs.aspose.org/cells/go/installation/)
guide's prerequisites section.
"""

_ZERO_DUPLICATES = """\
## Overview

This page documents the Cells API for Go. See the
[API Reference](https://reference.aspose.org/cells/go) for full details.

## Installation

Run `go get` to install the package.
"""


class TestFindDuplicateLinkMatches:
    def test_genuine_duplicate_within_one_paragraph_is_flagged(self):
        matches = find_duplicate_link_matches(_GENUINE_DUPLICATE)

        assert matches == ["**[API Reference](https://reference.aspose.org/cells/go)**"]

    def test_legitimate_repeat_in_different_sections_is_not_flagged(self):
        matches = find_duplicate_link_matches(_NOT_ADJACENT_DIFFERENT_SECTIONS)

        assert matches == []

    def test_zero_duplicates_returns_empty(self):
        matches = find_duplicate_link_matches(_ZERO_DUPLICATES)

        assert matches == []

    def test_plain_link_duplicated_twice_in_one_paragraph_is_flagged(self):
        text = (
            "Refer to [Setup](https://docs.aspose.org/x/setup) now. "
            "Also see [Setup](https://docs.aspose.org/x/setup) again."
        )

        matches = find_duplicate_link_matches(text)

        assert matches == ["[Setup](https://docs.aspose.org/x/setup)"]

    def test_two_different_adjacent_links_are_not_flagged(self):
        text = "[Setup](https://docs.aspose.org/x/setup) and [Usage](https://docs.aspose.org/x/usage)"

        matches = find_duplicate_link_matches(text)

        assert matches == []


class TestScanFile:
    def test_scan_file_reports_file_locale_and_match(self, tmp_path):
        target = tmp_path / "quickstart.md"
        target.write_text(_GENUINE_DUPLICATE, encoding="utf-8")

        findings = scan_file(target, None)

        assert len(findings) == 1
        assert findings[0]["file"] == str(target)
        assert findings[0]["match"] == "**[API Reference](https://reference.aspose.org/cells/go)**"

    def test_scan_file_never_writes_to_the_target(self, tmp_path):
        target = tmp_path / "quickstart.md"
        target.write_text(_GENUINE_DUPLICATE, encoding="utf-8")
        before_mtime = target.stat().st_mtime_ns
        before_content = target.read_bytes()

        scan_file(target, None)

        assert target.stat().st_mtime_ns == before_mtime
        assert target.read_bytes() == before_content

    def test_clean_file_produces_no_findings(self, tmp_path):
        target = tmp_path / "clean.md"
        target.write_text(_ZERO_DUPLICATES, encoding="utf-8")

        assert scan_file(target, None) == []


class TestDetectLocale:
    def test_filename_suffix_convention(self, tmp_path):
        path = tmp_path / "index.de.md"

        assert detect_locale(path, None) == "de"

    def test_directory_segment_convention(self, tmp_path):
        root = tmp_path / "content" / "docs.aspose.org"
        page = root / "de" / "cells" / "go" / "getting-started" / "quickstart.md"
        page.parent.mkdir(parents=True)
        page.write_text("x", encoding="utf-8")

        assert detect_locale(page, root) == "de"

    def test_platform_segment_is_not_mistaken_for_a_locale(self, tmp_path):
        """A path segment like "go" (a platform, not a locale) must not be
        misreported -- only the FIRST segment under root is checked."""
        root = tmp_path / "content" / "docs.aspose.org"
        page = root / "cells" / "go" / "getting-started" / "quickstart.md"
        page.parent.mkdir(parents=True)
        page.write_text("x", encoding="utf-8")

        assert detect_locale(page, root) == "unknown"

    def test_no_recognizable_locale_returns_unknown(self, tmp_path):
        path = tmp_path / "quickstart.md"

        assert detect_locale(path, None) == "unknown"


class TestScan:
    def test_scan_with_neither_root_nor_files_returns_empty(self):
        assert scan(root=None, files=[]) == []

    def test_scan_root_recursively_finds_markdown_files(self, tmp_path):
        (tmp_path / "sub").mkdir()
        dup_file = tmp_path / "sub" / "dup.md"
        dup_file.write_text(_GENUINE_DUPLICATE, encoding="utf-8")
        clean_file = tmp_path / "clean.md"
        clean_file.write_text(_ZERO_DUPLICATES, encoding="utf-8")

        findings = scan(root=tmp_path, files=[])

        assert len(findings) == 1
        assert findings[0]["file"] == str(dup_file)

    def test_scan_explicit_files_without_root(self, tmp_path):
        dup_file = tmp_path / "dup.md"
        dup_file.write_text(_GENUINE_DUPLICATE, encoding="utf-8")

        findings = scan(root=None, files=[dup_file])

        assert len(findings) == 1


class TestCli:
    def test_main_with_no_root_or_file_errors_without_scanning(self, capsys):
        exit_code = main([])

        assert exit_code == 1
        assert "nothing to scan" in capsys.readouterr().err

    def test_main_writes_json_report(self, tmp_path):
        dup_file = tmp_path / "dup.md"
        dup_file.write_text(_GENUINE_DUPLICATE, encoding="utf-8")
        report_path = tmp_path / "out.json"

        exit_code = main(["--file", str(dup_file), "--report", str(report_path)])

        assert exit_code == 0
        findings = json.loads(report_path.read_text(encoding="utf-8"))
        assert len(findings) == 1
        assert findings[0]["file"] == str(dup_file)

    def test_main_prints_json_to_stdout_without_report_flag(self, tmp_path, capsys):
        dup_file = tmp_path / "dup.md"
        dup_file.write_text(_GENUINE_DUPLICATE, encoding="utf-8")

        exit_code = main(["--file", str(dup_file)])

        assert exit_code == 0
        findings = json.loads(capsys.readouterr().out)
        assert len(findings) == 1

    def test_main_with_root_scans_recursively(self, tmp_path):
        dup_file = tmp_path / "dup.md"
        dup_file.write_text(_GENUINE_DUPLICATE, encoding="utf-8")
        report_path = tmp_path / "out.json"

        exit_code = main(["--root", str(tmp_path), "--report", str(report_path)])

        assert exit_code == 0
        findings = json.loads(report_path.read_text(encoding="utf-8"))
        assert len(findings) == 1

    def test_main_never_modifies_the_scanned_file(self, tmp_path):
        dup_file = tmp_path / "dup.md"
        dup_file.write_text(_GENUINE_DUPLICATE, encoding="utf-8")
        before = dup_file.read_bytes()

        main(["--file", str(dup_file)])

        assert dup_file.read_bytes() == before
