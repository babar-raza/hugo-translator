"""Safe-write choke point for all scripts/quality content repairs (TC-HT-002).

Every script in scripts/quality/ that repairs and rewrites a translated
content file must go through ``save()`` here instead of calling
``Path.write_text()`` directly. ``save()`` always runs the file through the
same ``WriteGateEvaluator`` gates the production translation pipeline uses
(``src/translation_engine/write_gate.py``) before writing anything to disk;
on failure the candidate content is quarantined instead of written.

This closes the class of bug where an ad-hoc quality script produced
malformed output (truncated YAML scalars, dropped code fences, stray
placeholder text) and wrote it straight to the content repo with no gate
in the path at all.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

_SCRIPT_DIR = str(Path(__file__).resolve().parent)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

_PROJ_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from ruamel.yaml.comments import CommentedMap  # noqa: E402

from src.translation_engine import consumer_intake  # noqa: E402
from src.translation_engine.parser.hugo_parser import HugoParser  # noqa: E402
from src.translation_engine.reconstructor.yaml_formatter import YAMLFormatter  # noqa: E402
from src.translation_engine.write_gate import WriteGateEvaluator  # noqa: E402

_parser = HugoParser()

QUARANTINE_ROOT = Path("workspace/quarantine")


def parse_content(raw: str) -> tuple[CommentedMap | dict, str]:
    """Split an in-memory Hugo document string into (frontmatter, body).

    ``frontmatter`` is ``{}`` if the content has no parseable frontmatter.
    """
    split = _parser._split_frontmatter(raw)
    if split is None:
        return {}, raw
    yaml_text, body = split
    data = _parser._parse_yaml_content(yaml_text)
    if not isinstance(data, dict):
        return {}, body
    return data, body


def load(path: Path) -> tuple[CommentedMap | dict, str, str]:
    """Load a Hugo content file. Returns (frontmatter, body, raw_content).

    ``frontmatter`` is ``{}`` if the file has no parseable frontmatter.
    """
    raw = path.read_text(encoding="utf-8", errors="replace")
    split = _parser._split_frontmatter(raw)
    if split is None:
        return {}, raw, raw
    yaml_text, body = split
    data = _parser._parse_yaml_content(yaml_text)
    if not isinstance(data, dict):
        return {}, body, raw
    return data, body, raw


@dataclass
class SaveResult:
    written: bool
    output_path: Path
    quarantined: bool = False
    quarantine_path: Path | None = None
    reasons: list[str] = field(default_factory=list)
    cleaned: bool = False


def _quarantine(candidate: str, output_path: Path, reasons: list[str]) -> Path | None:
    try:
        qdir = QUARANTINE_ROOT / output_path.parent.name
        qdir.mkdir(parents=True, exist_ok=True)
        qfile = qdir / f"{output_path.name}.quarantine.md"
        qfile.write_text(candidate, encoding="utf-8")
        (qdir / f"{output_path.name}.error.json").write_text(
            json.dumps(
                {"file": str(output_path), "reasons": reasons},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return qfile
    except OSError:
        return None


def save(
    src_path: Path,
    out_path: Path,
    frontmatter: CommentedMap | dict,
    body: str,
    *,
    source_content: str,
    target_lang: str,
    source_doc: object | None = None,
    existing_target_check: bool = True,
) -> SaveResult:
    """Serialize, gate-check, and write a repaired content file.

    Writes ``out_path`` ONLY if the rendered candidate passes
    ``WriteGateEvaluator`` AND, when ``out_path`` already exists and
    ``existing_target_check`` is True, the vendored consumer-repo checks
    (TC-HT-007) run against the EXISTING target as the "old" side. On any
    failure the candidate is quarantined under ``workspace/quarantine/``
    instead, and nothing is written to ``out_path``.
    """
    if frontmatter:
        try:
            fm_yaml = YAMLFormatter.format_frontmatter(frontmatter)
        except ValueError as exc:
            reasons = [f"yaml_serialization_failed: {exc}"]
            qpath = _quarantine(body, out_path, reasons)
            return SaveResult(
                written=False, output_path=out_path, quarantined=qpath is not None,
                quarantine_path=qpath, reasons=reasons,
            )
        rendered = fm_yaml + body
    else:
        rendered = body

    if existing_target_check and out_path.exists():
        old_text = out_path.read_text(encoding="utf-8", errors="replace")
        intake_reasons = [
            f"consumer_intake:{code}"
            for code in consumer_intake.check_text(rendered, str(out_path))
        ] + [
            f"consumer_intake:{code}"
            for code in consumer_intake.check_pair(rendered, old_text, target_lang)
        ]
        if intake_reasons:
            qpath = _quarantine(rendered, out_path, intake_reasons)
            return SaveResult(
                written=False, output_path=out_path, quarantined=qpath is not None,
                quarantine_path=qpath, reasons=intake_reasons,
            )

    evaluator = WriteGateEvaluator(
        detector=None, similarity_tracker=None, config=None, force_accept=False,
    )
    result = evaluator.evaluate(
        translated_content=rendered,
        source_content=source_content,
        target_lang=target_lang,
        output_path=out_path,
        source_doc=source_doc,
    )

    if not result.passed:
        reasons = [result.error] if result.error else ["write_gate_failed"]
        qpath = _quarantine(rendered, out_path, reasons)
        return SaveResult(
            written=False, output_path=out_path, quarantined=qpath is not None,
            quarantine_path=qpath, reasons=reasons,
        )

    final_content = result.cleaned_content if result.cleaned_content is not None else rendered
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(final_content, encoding="utf-8")
    return SaveResult(
        written=True, output_path=out_path,
        cleaned=result.cleaned_content is not None,
    )
