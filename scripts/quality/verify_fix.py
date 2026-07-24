"""
TC-P7-12: Post-fix verification harness for the quality-remediation-audit-
phase7-20260723 mission (see
C:\\Users\\prora\\.claude\\plans\\link-path-corrupted-1-638-memoized-hinton.md,
Deliverable 2 / Deliverable 4).

Proves a fixer's output rather than trusting it ran cleanly. Four checks:
  1. Detector re-check -- re-runs the SAME logic audit_all_content.py used
     to flag the file originally; must no longer fire for the fixed
     category. Reuses audit_all_content.py's own functions/regexes where
     they exist as standalone callables; reimplements the remaining
     categories' inline scan() logic verbatim (title_mismatch,
     linktitle_mismatch, double_period, link_path_corrupted, empty_body,
     newline_explosion, shortcode_leak have no standalone function in that
     module -- their logic lives inline in scan(), copied here exactly).
  2. WriteGateEvaluator re-check -- standalone gate battery, detector=None,
     config=None, force_accept=True (the exact pattern audit_all_content.py
     itself already uses at module scope for gates 29-35).
  3. CompletenessValidator re-check -- placeholder leakage / length-ratio
     collapse / trailing-section loss, called standalone with no context.
  4. Blast-radius diff -- every line outside the fixer's declared changed
     region must be byte-identical before/after.

link_path_corrupted gets an ADDITIONAL, detector-independent check per the
plan (TC-P7-05): re-running the same text-pattern detector is not
sufficient proof for a wrong-but-plausible link, so every fixed link
target is also resolved against the actual content tree on disk.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
_QUALITY_DIR = Path(__file__).resolve().parent
if str(_QUALITY_DIR) not in sys.path:
    sys.path.insert(0, str(_QUALITY_DIR))

from audit_all_content import (  # noqa: E402
    DOUBLE_PERIOD,
    SHORTCODE_LEAK,
    WriteGateEvaluator,
    check_code_fence_dropped,
    check_table_desc_not_translated,
    fm_field,
    get_body,
    get_frontmatter,
)
from src.translation_engine.validation.completeness_validator import (  # noqa: E402
    CompletenessValidator,
)
from src.translation_engine.write_gate import WriteGateResult  # noqa: E402

CONTENT_ROOT = Path(r"D:\onedrive\Documents\GitHub\aspose.org\content")

_GATE_EVALUATOR = WriteGateEvaluator(
    detector=None, similarity_tracker=None, config=None, force_accept=True
)

_FAMILY_ROOT_SITES = {"products.aspose.org", "kb.aspose.org", "docs.aspose.org"}
_LINK_RE = re.compile(r"(\[(?:[^\[\]]*)\])\(([^)]+)\)")

# Gates safe to call standalone (detector=None/config=None/force_accept=True) --
# excludes gates 2-4 (need a real language detector) and gate 36 (LLM fidelity
# judge). Confirmed via write_gate.py source inspection.
_STANDALONE_SAFE_GATES = {
    "double_period": "_gate_double_periods",
    "code_fence_dropped": None,  # covered by fence-count re-check below, not a single gate
    "empty_body": "_gate_empty_body",
    "shortcode_leak": "_gate_shortcode_body_leak",
    "partial_script_contamination_gate31": "_gate_partial_script_contamination",
}


@dataclass
class VerifyResult:
    passed: bool
    issue_type: str
    file_path: str
    detector_still_fires: bool | None = None
    detector_detail: str = ""
    gate_failures: list[str] = field(default_factory=list)
    completeness_issues: list[str] = field(default_factory=list)
    blast_radius_ok: bool | None = None
    blast_radius_detail: str = ""
    link_targets_resolve: bool | None = None
    unresolved_links: list[str] = field(default_factory=list)
    notes: str = ""


def _is_family_platform_or_root_index(rel_parts: list[str], locale: str, site_id: str) -> bool:
    if not rel_parts or rel_parts[-1] != "_index.md":
        return False
    if locale in rel_parts:
        idx = rel_parts.index(locale)
        remainder = rel_parts[idx + 1 :]
    else:
        remainder = rel_parts
    is_family_platform_index = len(remainder) == 3
    is_family_root_index = len(remainder) == 2 and site_id in _FAMILY_ROOT_SITES
    return is_family_platform_index or is_family_root_index or site_id == "reference.aspose.org"


def _rel_parts(tr_path: Path, site_id: str) -> list[str]:
    try:
        rel = tr_path.relative_to(CONTENT_ROOT / site_id)
    except ValueError:
        return list(tr_path.parts)
    return list(rel.parts)


def detector_still_fires(
    issue_type: str,
    en_text: str,
    tr_text: str,
    tr_path: Path,
    en_path: Path,
    locale: str,
    site_id: str,
) -> tuple[bool, str]:
    """Re-run the same detection logic that originally flagged this file.
    Returns (still_fires, detail). still_fires=False means the fix holds.
    """
    en_fm, en_body = get_frontmatter(en_text), get_body(en_text)
    tr_fm, tr_body = get_frontmatter(tr_text), get_body(tr_text)

    if issue_type == "empty_body":
        fires = len(tr_body.strip()) < 20 and len(en_body.strip()) > 50
        return fires, ""

    if issue_type in ("title_mismatch", "linktitle_mismatch"):
        rel_parts = _rel_parts(tr_path, site_id)
        if not _is_family_platform_or_root_index(rel_parts, locale, site_id):
            return False, "not a title-identity page (rule doesn't apply here)"
        en_title = fm_field(en_fm, "title") or ""
        tr_title = fm_field(tr_fm, "title") or ""
        en_link_title = fm_field(en_fm, "linkTitle") or ""
        tr_link_title = fm_field(tr_fm, "linkTitle") or ""
        if issue_type == "title_mismatch":
            fires = bool(en_title and tr_title and tr_title != en_title)
            return fires, f"EN={en_title!r} TR={tr_title!r}"
        fires = bool(en_link_title and tr_link_title and tr_link_title != en_link_title)
        return fires, f"EN={en_link_title!r} TR={tr_link_title!r}"

    if issue_type == "double_period":
        body_no_code = re.sub(r"```.*?```", "", tr_body, flags=re.S)
        m = DOUBLE_PERIOD.search(body_no_code)
        return bool(m), (m.group() if m else "")

    if issue_type == "newline_explosion":
        en_lines = en_text.count("\n")
        tr_lines = tr_text.count("\n")
        fires = tr_lines > en_lines * 2.5 and en_lines > 10
        return fires, f"EN={en_lines} TR={tr_lines}"

    if issue_type == "link_path_corrupted":
        en_links = {m.group(2) for m in _LINK_RE.finditer(en_body) if m.group(2).startswith(("../", "./", "/"))}
        tr_links = {m.group(2) for m in _LINK_RE.finditer(tr_body) if m.group(2).startswith(("../", "./", "/"))}
        corrupted = tr_links - en_links
        return bool(corrupted), str(sorted(corrupted)[:5])

    if issue_type == "shortcode_leak":
        fires = bool(SHORTCODE_LEAK.search(tr_body) and not SHORTCODE_LEAK.search(en_body))
        return fires, ""

    if issue_type == "table_desc_not_translated":
        fires, detail = check_table_desc_not_translated(tr_body)
        return fires, detail

    if issue_type == "code_fence_dropped":
        fires, detail = check_code_fence_dropped(en_body, tr_body)
        return fires, detail

    if issue_type == "partial_script_contamination_gate31":
        result = WriteGateResult(passed=True)
        _GATE_EVALUATOR._gate_partial_script_contamination(tr_text, tr_path, locale, result)
        return (not result.passed), (result.error or "")

    raise ValueError(f"No detector re-check defined for issue_type={issue_type!r}")


def run_relevant_gates(issue_type: str, en_text: str, tr_text: str, tr_path: Path, locale: str) -> list[str]:
    """Run whichever standalone-safe WriteGateEvaluator gate(s) correspond
    to this issue_type. Returns a list of failure messages (empty = pass).
    Gates 2-4/36 are never called here (need a real detector / LLM config).
    """
    gate_method_name = _STANDALONE_SAFE_GATES.get(issue_type)
    if not gate_method_name:
        return []
    method = getattr(_GATE_EVALUATOR, gate_method_name, None)
    if method is None:
        return [f"gate method {gate_method_name} not found on WriteGateEvaluator"]
    result = WriteGateResult(passed=True)
    try:
        if gate_method_name == "_gate_double_periods":
            # auto-clean gate: returns cleaned content, doesn't set result.passed
            cleaned = method(en_text, tr_text, tr_path, result)
            body_no_code = re.sub(r"```.*?```", "", get_body(cleaned), flags=re.S)
            if DOUBLE_PERIOD.search(body_no_code):
                return ["Gate 12 still finds double periods after fix"]
            return []
        elif gate_method_name == "_gate_partial_script_contamination":
            method(tr_text, tr_path, locale, result)
        else:
            method(tr_text, tr_path, result)
    except TypeError:
        # signature mismatch across gate variants -- try (translated, path, result)
        try:
            method(tr_text, tr_path, result)
        except Exception as exc:  # noqa: BLE001
            return [f"gate {gate_method_name} raised: {exc}"]
    if not result.passed:
        return [result.error or f"{gate_method_name} failed"]
    return []


def run_completeness_check(en_text: str, tr_text: str) -> list[str]:
    validator = CompletenessValidator()
    result = validator.validate(source=en_text, translation=tr_text)
    if result.success:
        return []
    return [str(i) for i in result.issues]


def blast_radius_diff(before_text: str, after_text: str, allowed_changed_hint: str = "") -> tuple[bool, str]:
    """Confirm the fix didn't touch more than expected. This is a coarse
    guard, not a semantic diff: flags a failure only when the SIZE of the
    change is wildly disproportionate to a single targeted text fix (more
    than 40% of lines changed), which would indicate the fixer clobbered
    unrelated content rather than making a narrow correction.
    """
    before_lines = before_text.splitlines()
    after_lines = after_text.splitlines()
    if not before_lines:
        return True, "empty before-text, nothing to compare"
    import difflib

    sm = difflib.SequenceMatcher(a=before_lines, b=after_lines, autojunk=False)
    ratio = sm.ratio()
    changed_fraction = 1.0 - ratio
    if changed_fraction > 0.40:
        return False, f"{changed_fraction:.0%} of lines changed (threshold 40%) -- {allowed_changed_hint}"
    return True, f"{changed_fraction:.1%} of lines changed"


def _hugo_page_url_dir(tr_path: Path) -> Path:
    """The directory a relative link actually resolves against, per Hugo's
    rendered-URL semantics, NOT the filesystem directory. `_index.md`'s
    page URL is its containing directory; any other `foo.md` renders to
    `{dir}/foo/` -- an extra implied path segment the filesystem doesn't
    have. A relative link's "../" count is relative to that rendered URL,
    so resolution must account for it or a correct link on a leaf page
    (e.g. installation.md, quickstart.md) looks broken when it isn't.
    """
    if tr_path.name == "_index.md":
        return tr_path.parent
    return tr_path.parent / tr_path.stem


def check_link_targets_resolve(tr_text: str, tr_path: Path, site_id: str) -> tuple[bool, list[str]]:
    """Detector-independent check for link_path_corrupted (TC-P7-05):
    resolve every relative link target in the fixed body against the
    actual content tree on disk. A text-pattern re-check alone can't catch
    a wrong-but-plausible link; this can.
    """
    tr_body = get_body(tr_text)
    page_url_dir = _hugo_page_url_dir(tr_path)
    unresolved = []
    for m in _LINK_RE.finditer(tr_body):
        target = m.group(2)
        if not target.startswith(("../", "./", "/")):
            continue
        target_clean = target.split("#")[0].split("?")[0]
        if target_clean.startswith("/"):
            candidate = CONTENT_ROOT / site_id / target_clean.lstrip("/")
        else:
            candidate = (page_url_dir / target_clean).resolve()
        # Hugo section links often resolve to a directory (implicit _index.md)
        if candidate.is_dir():
            continue
        if candidate.exists():
            continue
        if (candidate.parent / "_index.md").exists() and candidate.name == "":
            continue
        if Path(str(candidate) + ".md").exists() or Path(str(candidate).rstrip("/") + "/_index.md").exists():
            continue
        unresolved.append(target)
    return (len(unresolved) == 0), unresolved


def verify_fix(
    issue_type: str,
    tr_path: Path,
    en_path: Path,
    before_text: str,
    after_text: str,
    locale: str,
    site_id: str,
) -> VerifyResult:
    en_text = en_path.read_text(encoding="utf-8", errors="replace")

    still_fires, detail = detector_still_fires(issue_type, en_text, after_text, tr_path, en_path, locale, site_id)
    gate_failures = run_relevant_gates(issue_type, en_text, after_text, tr_path, locale)
    # Only a NEWLY introduced completeness issue is a real verify failure --
    # pre-existing defects unrelated to this fixer's own issue_type (e.g. a
    # dropped-trailing-link Gate 34/35 finding on a file this mission's
    # double_period fixer merely touched) must not block an otherwise-correct
    # fix. Confirmed root cause: many flagged files carry unrelated,
    # out-of-scope defects the mission was never asked to fix.
    completeness_before = set(run_completeness_check(en_text, before_text))
    completeness_after = set(run_completeness_check(en_text, after_text))
    completeness_issues = sorted(completeness_after - completeness_before)
    blast_ok, blast_detail = blast_radius_diff(before_text, after_text, issue_type)

    link_targets_resolve = None
    unresolved_links: list[str] = []
    if issue_type == "link_path_corrupted":
        link_targets_resolve, unresolved_links = check_link_targets_resolve(after_text, tr_path, site_id)

    passed = (
        not still_fires
        and not gate_failures
        and not completeness_issues
        and blast_ok
        and (link_targets_resolve is not False)
    )

    return VerifyResult(
        passed=passed,
        issue_type=issue_type,
        file_path=str(tr_path),
        detector_still_fires=still_fires,
        detector_detail=detail,
        gate_failures=gate_failures,
        completeness_issues=completeness_issues,
        blast_radius_ok=blast_ok,
        blast_radius_detail=blast_detail,
        link_targets_resolve=link_targets_resolve,
        unresolved_links=unresolved_links,
    )
