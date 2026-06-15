"""TC-AGT-02: Evidence declaration schema and writer.

Provides a Pydantic model for evidence-declaration.yaml files and a writer
utility that produces validated, machine-readable evidence declarations.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class EvidenceDeclaration(BaseModel):
    """Schema for evidence-declaration.yaml files.

    Captures run metadata, inspected artifacts, findings summary,
    and final verdict for any sprint or investigation run.
    """

    run_id: str = Field(..., description="Unique run identifier")
    repo_path: str = Field(..., description="Absolute path to repository root")
    branch: str = Field(default="main", description="Git branch")
    base_commit: str = Field(default="", description="Git HEAD SHA at run start")
    date: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        description="Run date (YYYY-MM-DD)",
    )

    # Optional context
    reviewer_app_path: str | None = Field(default=None)
    reviewer_app_exists: bool = Field(default=False)
    started_at: str | None = Field(default=None)
    completed_at: str | None = Field(default=None)

    # Inspected artifacts
    files_inspected: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Category -> list of inspected file paths",
    )
    workflows_inspected: list[str] = Field(default_factory=list)
    commands_inspected: list[str] = Field(default_factory=list)
    state_queue_files_inspected: list[str] = Field(default_factory=list)
    supervisor_reviewer_files_inspected: list[str] = Field(default_factory=list)
    llm_professionalize_configs_inspected: list[str] = Field(default_factory=list)

    # Findings summary
    reviewer_facing_artifacts_found: str | None = Field(default=None)
    maturity_levels_assigned: dict[str, Any] = Field(default_factory=dict)
    autonomy_gaps_found: int = Field(default=0)
    opportunities_identified: int = Field(default=0)
    taskcards_proposed: int = Field(default=0)
    risks_identified: int = Field(default=0)

    # Roadmap
    recommended_roadmap: dict[str, Any] = Field(default_factory=dict)

    # Verdict
    final_verdict: str = Field(default="PENDING")

    # Extensible metadata
    extra: dict[str, Any] = Field(default_factory=dict)


def write_evidence_declaration(
    declaration: EvidenceDeclaration,
    output_dir: Path,
    filename: str = "evidence-declaration.yaml",
) -> Path:
    """Write an evidence declaration to a YAML file.

    Args:
        declaration: Validated EvidenceDeclaration model.
        output_dir: Directory to write the file to.
        filename: Output filename (default: evidence-declaration.yaml).

    Returns:
        Path to the written file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / filename

    # Use JSON-compatible dict, then write as YAML-like format
    data = declaration.model_dump(exclude_none=True, exclude={"extra"})
    if declaration.extra:
        data.update(declaration.extra)

    # Write as YAML (simple key-value format for compatibility)
    lines: list[str] = []
    _dict_to_yaml_lines(data, lines, indent=0)

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("Evidence declaration written: %s", output_path)
    return output_path


def _dict_to_yaml_lines(data: Any, lines: list[str], indent: int = 0) -> None:
    """Convert a dict/list structure to simple YAML lines."""
    prefix = "  " * indent
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, dict):
                lines.append(f"{prefix}{key}:")
                _dict_to_yaml_lines(value, lines, indent + 1)
            elif isinstance(value, list):
                lines.append(f"{prefix}{key}:")
                for item in value:
                    if isinstance(item, dict):
                        lines.append(f"{prefix}  -")
                        _dict_to_yaml_lines(item, lines, indent + 2)
                    else:
                        lines.append(f"{prefix}  - {_yaml_scalar(item)}")
            else:
                lines.append(f"{prefix}{key}: {_yaml_scalar(value)}")
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                lines.append(f"{prefix}-")
                _dict_to_yaml_lines(item, lines, indent + 1)
            else:
                lines.append(f"{prefix}- {_yaml_scalar(item)}")


def _yaml_scalar(value: Any) -> str:
    """Format a scalar value for YAML output."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    s = str(value)
    # Quote strings that could be misinterpreted
    if s in ("true", "false", "null", "yes", "no", "on", "off") or ":" in s or "#" in s:
        return f'"{s}"'
    return s


def export_json_schema(output_path: Path) -> Path:
    """Export the evidence declaration JSON schema.

    Args:
        output_path: Path to write the JSON schema file.

    Returns:
        Path to the written schema file.
    """
    schema = EvidenceDeclaration.model_json_schema()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(schema, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    logger.info("JSON schema exported: %s", output_path)
    return output_path
