"""Remaining audit consumers must ignore canonical Markdown code regions."""
from __future__ import annotations

from scripts.quality import audit_all_content as aac


def _code(text: str) -> str:
    return f"```text\n{text}\n```\n"


def test_artifact_is_ignored_in_code_but_detected_in_prose():
    assert aac.check_artifact_corruption(_code("[Previous] 0")) is None
    assert aac.check_artifact_corruption("[Previous] 0") == "[Previous] 0"


def test_shortcode_is_ignored_in_code_but_detected_in_prose():
    token = "{{< figure src=\"x\" >}}"
    assert aac.check_shortcode_leak("", _code(token)) is False
    assert aac.check_shortcode_leak("", token) is True


def test_eu_phrase_is_ignored_in_code_but_detected_in_prose():
    assert aac.check_eu_hallucination("", _code("cookie policy")) is None
    assert aac.check_eu_hallucination("", "cookie policy") == "cookie"


def test_relative_link_is_ignored_in_code_but_detected_in_prose():
    source = "[source](../source)"
    altered = "[target](../target)"
    assert aac.check_link_path_corrupted(source, _code(altered)) == set()
    assert aac.check_link_path_corrupted(source, altered) == {"../target"}
