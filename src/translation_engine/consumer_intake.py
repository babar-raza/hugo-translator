"""Cross-repo intake handshake (TC-HT-007).

Vendored, with minimal adaptation, from aspose.org @ commit 07a3e9716d
("fix(ci): gates must validate staged blobs; add fence-strip regression
rule"):
  - check_text()  <- scripts/ci/checks/check_frontmatter_yaml.py::check_text
  - check_pair()  <- scripts/ci/checks/check_translation_regression.py::check_pair

These are the consumer repo's own pre-commit gates, copied here so the
producer refuses to degrade a good EXISTING translation in the consuming
repo even if its own write_gate.py gates are ever misconfigured or
bypassed — defense-in-depth, not a replacement for the in-repo gates.

Vendored (not imported live) deliberately: the sibling checkout's path is
host-specific and importing across repos would create an unwanted runtime
coupling. Update by re-copying from aspose.org if its checks evolve.
"""
from __future__ import annotations

import re

import yaml

# --- from check_frontmatter_yaml.py -----------------------------------

_TOP_LEVEL_KEY_RE = re.compile(r"^[A-Za-z_][\w.-]*:")


def _find_unterminated_quote_line(fm_text: str) -> int | None:
    """Best-effort detector for the wave-3 signature: an unclosed
    single-quoted scalar that swallows a later top-level key."""
    lines = fm_text.splitlines()
    for i, line in enumerate(lines):
        m = _TOP_LEVEL_KEY_RE.match(line)
        if not m:
            continue
        value = line[m.end():].strip()
        if not value.startswith("'"):
            continue
        if value.count("'") % 2 == 0:
            continue
        for later in lines[i + 1:]:
            if _TOP_LEVEL_KEY_RE.match(later):
                return i + 1
            if "'" in later:
                break
    return None


def _check_frontmatter(text: str, label: str) -> list[str]:
    end = text.find("\n---", 3)
    if end == -1:
        return [f"F3 FAIL {label}: frontmatter has no closing '---' delimiter"]
    fm_text = text[3:end]
    try:
        parsed = yaml.safe_load(fm_text)
    except yaml.YAMLError as exc:
        msg = str(exc).replace("\n", " ")[:200]
        failures = [f"F1 FAIL {label}: frontmatter does not parse: {msg}"]
        bad_line = _find_unterminated_quote_line(fm_text)
        if bad_line is not None:
            failures.append(
                f"        hint: unterminated single-quoted scalar opened at "
                f"frontmatter line {bad_line} swallows later keys "
                f"(wave-3 truncated-description signature)"
            )
        return failures
    if not isinstance(parsed, dict):
        return [
            f"F2 FAIL {label}: frontmatter parses but is "
            f"{type(parsed).__name__}, not a mapping"
        ]
    return []


def check_text(text: str, label: str) -> list[str]:
    """F1/F2/F3 frontmatter-YAML-parse checks. Empty list = pass."""
    if not text.startswith("---"):
        return []
    return _check_frontmatter(text, label)


# --- from check_translation_regression.py -------------------------------

NONLATIN_LOCALES = frozenset({
    "ar", "bg", "el", "fa", "he", "hi", "ja", "ko", "ru", "sr", "th", "uk", "zh",
})
_EN_STOPWORDS = [
    " the ", " and ", " with ", " for ", " how to ", " using ", " from ",
    " your ", " all ",
]
# NOTE (TC-HT-007 known limitation): fixed EN/ES phrase list only — will not
# catch a prompt-leak translated into German/Russian/Arabic etc. TC-HT-003's
# structural (language-agnostic) LLM-side validation is the real backstop
# for other locales; this is narrower defense-in-depth, not a general
# solution.
LEAK_RE = re.compile(
    r"SÓLO la traducción|ONLY the translation|Preservar todo el formato|"
    r"Preserve all formatting|shortcodes de Hugo exactamente|Hugo shortcodes exactly|"
    r"No explicaciones, notas ni comentarios|Do not add, remove, or reorder content"
)


def _split_fm(text: str) -> str | None:
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    return text[3:end] if end != -1 else None


def _description(text: str | None) -> str | None:
    if text is None:
        return None
    fm = _split_fm(text)
    if fm is None:
        return None
    try:
        data = yaml.safe_load(fm)
    except yaml.YAMLError:
        return None  # unparseable frontmatter is check_text's job
    if isinstance(data, dict):
        value = data.get("description")
        return value if isinstance(value, str) else None
    return None


def _ascii_alpha_frac(s: str) -> float:
    alpha = [c for c in s if c.isalpha()]
    if len(alpha) < 20:
        return 0.0
    return sum(1 for c in alpha if c.isascii()) / len(alpha)


def looks_english(text: str | None, locale: str) -> bool:
    """Heuristic: does this description read as English for the given locale?"""
    if not text or locale == "en":
        return False
    if locale in NONLATIN_LOCALES:
        return _ascii_alpha_frac(text) > 0.7
    low = f" {text.lower()} "
    return sum(1 for w in _EN_STOPWORDS if w in low) >= 4


def _fence_count(text: str) -> int:
    return sum(1 for ln in text.splitlines() if ln.lstrip().startswith("```"))


def check_pair(cur_text: str, old_text: str | None, locale: str) -> list[str]:
    """R1 (english regression) / R2 (prompt leak) / R3 (fence-count drop).

    Compares the CURRENT candidate against the EXISTING (old) target text.
    Empty list = pass.
    """
    failures = []
    if LEAK_RE.search(cur_text):
        failures.append("R2")
    cur_desc = _description(cur_text)
    if looks_english(cur_desc, locale):
        old_desc = _description(old_text) if old_text else None
        # Only a REGRESSION blocks: previous version had a non-English desc.
        if old_desc and not looks_english(old_desc, locale):
            failures.append("R1")
    if old_text and _fence_count(cur_text) < _fence_count(old_text):
        failures.append("R3")
    return failures
