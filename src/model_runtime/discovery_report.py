"""
Discovery run report manager.

Persists evidence from each discovery run as JSON reports.
Exports discovered models to registry YAML for ModelRegistry consumption.
"""

from __future__ import annotations

import json
import logging
import platform
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


@dataclass
class DiscoveryRunReport:
    """Complete report for one discovery run."""

    run_id: str
    timestamp: str
    duration_seconds: float
    scan_roots: list[dict[str, Any]]
    skipped_roots: list[dict[str, Any]]
    models_found: int
    models_new: int
    models_by_format: dict[str, int]
    models_by_backend: dict[str, int]
    duplicates_removed: int
    invalid_candidates: int
    errors: list[dict[str, str]]
    discovered_models: list[dict[str, Any]]
    system_info: dict[str, Any]
    selection_recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": "1.0",
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "duration_seconds": self.duration_seconds,
            "scan_roots": self.scan_roots,
            "skipped_roots": self.skipped_roots,
            "summary": {
                "models_found": self.models_found,
                "models_new": self.models_new,
                "models_by_format": self.models_by_format,
                "models_by_backend": self.models_by_backend,
                "duplicates_removed": self.duplicates_removed,
                "invalid_candidates": self.invalid_candidates,
            },
            "errors": self.errors,
            "models": self.discovered_models,
            "system_info": self.system_info,
            "selection_recommendations": self.selection_recommendations,
        }


class DiscoveryReportManager:
    """Manage discovery run reports and registry export."""

    def __init__(self, reports_dir: Path = Path("data/discovery")):
        self.reports_dir = reports_dir
        self._runs: dict[str, dict[str, Any]] = {}

    def start_run(self, scan_roots: list[Any]) -> str:
        """Start a new discovery run. Returns run_id."""
        run_id = str(uuid.uuid4())[:12]
        self._runs[run_id] = {
            "start_time": datetime.now(UTC),
            "scan_roots": [
                r.to_dict() if hasattr(r, "to_dict") else {"path": str(r)} for r in scan_roots
            ],
            "models": [],
            "errors": [],
        }
        return run_id

    def record_model(self, run_id: str, model_dict: dict[str, Any]) -> None:
        """Record a discovered model in the run."""
        if run_id in self._runs:
            self._runs[run_id]["models"].append(model_dict)

    def record_error(self, run_id: str, path: str, error: str) -> None:
        """Record an error in the run."""
        if run_id in self._runs:
            self._runs[run_id]["errors"].append(
                {
                    "path": path,
                    "error": error,
                }
            )

    def finish_run(
        self,
        run_id: str,
        skipped_roots: list[dict[str, Any]] | None = None,
        errors: list[dict[str, str]] | None = None,
        existing_model_ids: set[str] | None = None,
        total_before_dedup: int = 0,
    ) -> DiscoveryRunReport:
        """Finish a run and produce the report."""
        run_data = self._runs.get(run_id, {})
        start_time = run_data.get("start_time", datetime.now(UTC))
        end_time = datetime.now(UTC)
        duration = (end_time - start_time).total_seconds()

        models = run_data.get("models", [])
        all_errors = (errors or []) + run_data.get("errors", [])

        # Compute aggregates
        by_format: dict[str, int] = {}
        by_backend: dict[str, int] = {}
        models_new = 0
        existing_ids = existing_model_ids or set()

        for m in models:
            fmt = m.get("model_format", "unknown")
            by_format[fmt] = by_format.get(fmt, 0) + 1
            bk = m.get("backend_type", "unknown")
            by_backend[bk] = by_backend.get(bk, 0) + 1
            if m.get("model_id", "") not in existing_ids:
                models_new += 1

        # Selection recommendations
        recommendations = []
        if by_format.get("transformers", 0) > 0:
            recommendations.append("Transformers models available for HuggingFace backend.")
        if by_format.get("ctranslate2", 0) > 0:
            recommendations.append("CTranslate2 models available for fast CPU inference.")
        if by_format.get("ollama", 0) > 0:
            recommendations.append("Ollama models available for LLM backend.")
        if by_format.get("gguf", 0) > 0:
            recommendations.append(
                "GGUF models found. Use with llama.cpp or Ollama for LLM translation."
            )

        system_info = {
            "platform": platform.platform(),
            "hostname": platform.node(),
            "python_version": platform.python_version(),
        }

        # Detect drives on Windows
        if platform.system() == "Windows":
            import string

            drives = []
            for letter in string.ascii_uppercase:
                drive = Path(f"{letter}:/")
                if drive.exists():
                    drives.append(f"{letter}:")
            system_info["drives"] = drives

        report = DiscoveryRunReport(
            run_id=run_id,
            timestamp=end_time.isoformat(),
            duration_seconds=round(duration, 2),
            scan_roots=run_data.get("scan_roots", []),
            skipped_roots=skipped_roots or [],
            models_found=len(models),
            models_new=models_new,
            models_by_format=by_format,
            models_by_backend=by_backend,
            duplicates_removed=max(0, total_before_dedup - len(models)),
            invalid_candidates=0,
            errors=all_errors,
            discovered_models=models,
            system_info=system_info,
            selection_recommendations=recommendations,
        )

        return report

    def save_report(self, report: DiscoveryRunReport) -> Path:
        """Save report to JSON file atomically."""
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        report_path = self.reports_dir / f"run_{report.run_id}.json"
        temp_path = report_path.with_suffix(".json.tmp")

        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)

            if report_path.exists():
                report_path.unlink()
            temp_path.rename(report_path)

            logger.info(f"Discovery report saved: {report_path}")
            return report_path

        except Exception as e:
            if temp_path.exists():
                temp_path.unlink()
            raise OSError(f"Failed to save discovery report: {e}") from e

    def load_report(self, run_id: str) -> DiscoveryRunReport | None:
        """Load report from JSON file."""
        report_path = self.reports_dir / f"run_{run_id}.json"
        if not report_path.exists():
            return None

        try:
            with open(report_path, encoding="utf-8") as f:
                data = json.load(f)

            summary = data.get("summary", {})
            return DiscoveryRunReport(
                run_id=data["run_id"],
                timestamp=data["timestamp"],
                duration_seconds=data["duration_seconds"],
                scan_roots=data.get("scan_roots", []),
                skipped_roots=data.get("skipped_roots", []),
                models_found=summary.get("models_found", 0),
                models_new=summary.get("models_new", 0),
                models_by_format=summary.get("models_by_format", {}),
                models_by_backend=summary.get("models_by_backend", {}),
                duplicates_removed=summary.get("duplicates_removed", 0),
                invalid_candidates=summary.get("invalid_candidates", 0),
                errors=data.get("errors", []),
                discovered_models=data.get("models", []),
                system_info=data.get("system_info", {}),
                selection_recommendations=data.get("selection_recommendations", []),
            )
        except (json.JSONDecodeError, KeyError, OSError) as e:
            logger.error(f"Failed to load report {run_id}: {e}")
            return None

    def list_reports(self) -> list[dict[str, Any]]:
        """List all discovery reports with summary metadata."""
        reports: list[dict[str, Any]] = []

        if not self.reports_dir.exists():
            return reports

        for report_file in sorted(self.reports_dir.glob("run_*.json"), reverse=True):
            try:
                with open(report_file, encoding="utf-8") as f:
                    data = json.load(f)
                summary = data.get("summary", {})
                reports.append(
                    {
                        "run_id": data.get("run_id", ""),
                        "timestamp": data.get("timestamp", ""),
                        "models_found": summary.get("models_found", 0),
                        "errors": len(data.get("errors", [])),
                        "file": str(report_file),
                    }
                )
            except (json.JSONDecodeError, OSError):
                continue

        return reports

    def get_latest_report(self) -> DiscoveryRunReport | None:
        """Get most recent discovery report."""
        reports = self.list_reports()
        if not reports:
            return None
        return self.load_report(reports[0]["run_id"])

    def export_as_registry_yaml(
        self,
        report: DiscoveryRunReport,
        output_path: Path,
        exclude_existing: set[str] | None = None,
    ) -> int:
        """
        Export discovered models as a registry YAML file.

        Args:
            report: Discovery run report
            output_path: Path to write YAML
            exclude_existing: Set of model_ids to exclude (already in curated registry)

        Returns:
            Number of models written
        """

        exclude = exclude_existing or set()
        models_data: list[dict[str, Any]] = []

        for model_dict in report.discovered_models:
            model_id = model_dict.get("model_id", "")
            if model_id in exclude:
                continue

            # Build registry-compatible entry
            backend = model_dict.get("backend_type", "huggingface")
            supported_pairs = model_dict.get("supported_language_pairs", "all")
            size_bytes = model_dict.get("size_bytes", 0)
            size_mb = int(size_bytes / (1024 * 1024)) if size_bytes else 0
            min_ram_gb = max(1.0, (size_mb / 1024) * 2 + 1.0)

            entry: dict[str, Any] = {
                "model_id": model_id,
                "name": model_dict.get("display_name", model_id),
                "backend": backend,
                "supported_pairs": supported_pairs,
                "model_size_mb": size_mb,
                "min_ram_gb": round(min_ram_gb, 1),
                "optimal_device": model_dict.get("device_hint", "cpu"),
                "local_path": model_dict.get("absolute_path", ""),
                "hf_model_id": model_dict.get("hf_model_id"),
                "description": (
                    f"Auto-discovered {model_dict.get('model_family', 'unknown')} model. "
                    f"Confidence: {model_dict.get('confidence', 0):.0%}."
                ),
            }

            # LLM-specific fields for Ollama
            if backend == "local_llm" and model_dict.get("model_format") == "ollama":
                entry["provider"] = "ollama"
                entry["model_name"] = model_dict.get("display_name", "")
                entry["base_url"] = "http://localhost:11434"

            models_data.append(entry)

        # Write YAML
        output_path.parent.mkdir(parents=True, exist_ok=True)
        data = {"models": models_data}

        temp_path = output_path.with_suffix(".yaml.tmp")
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write("# Auto-generated by local model discovery.\n")
                f.write(f"# Run ID: {report.run_id}\n")
                f.write(f"# Generated: {report.timestamp}\n")
                f.write(f"# Models: {len(models_data)}\n")
                f.write("# This file is safe to delete and regenerate.\n\n")
                yaml.dump(data, f, default_flow_style=False, sort_keys=False)

            if output_path.exists():
                output_path.unlink()
            temp_path.rename(output_path)

            logger.info(f"Exported {len(models_data)} models to {output_path}")
            return len(models_data)

        except Exception as e:
            if temp_path.exists():
                temp_path.unlink()
            raise OSError(f"Failed to export registry YAML: {e}") from e
