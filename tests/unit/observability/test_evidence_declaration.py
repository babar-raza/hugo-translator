"""Tests for TC-AGT-02: Evidence declaration schema and writer."""

import json
import tempfile
from pathlib import Path

import pytest

from src.observability.evidence_declaration import (
    EvidenceDeclaration,
    export_json_schema,
    write_evidence_declaration,
)


class TestEvidenceDeclarationSchema:
    """Test the Pydantic schema for evidence declarations."""

    def test_minimal_declaration(self):
        """Minimal valid declaration with required fields only."""
        decl = EvidenceDeclaration(
            run_id="test-run-001",
            repo_path="/tmp/test-repo",
        )
        assert decl.run_id == "test-run-001"
        assert decl.branch == "main"
        assert decl.final_verdict == "PENDING"

    def test_full_declaration(self):
        """Full declaration with all fields populated."""
        decl = EvidenceDeclaration(
            run_id="full-run-002",
            repo_path="/tmp/test-repo",
            branch="feature/test",
            base_commit="abc123def456",
            date="2026-06-13",
            reviewer_app_path="/tmp/reviewer",
            reviewer_app_exists=True,
            files_inspected={"config": ["global.yaml"], "source": ["engine.py"]},
            workflows_inspected=[".gitlab-ci.yml"],
            commands_inspected=["pytest"],
            maturity_levels_assigned={"translation": 4, "overall": 2.5},
            autonomy_gaps_found=10,
            opportunities_identified=12,
            taskcards_proposed=12,
            risks_identified=5,
            recommended_roadmap={"horizon_1": "5 taskcards"},
            final_verdict="INVESTIGATION_COMPLETE",
        )
        assert decl.reviewer_app_exists is True
        assert decl.autonomy_gaps_found == 10
        assert decl.maturity_levels_assigned["overall"] == 2.5

    def test_model_dump_excludes_none(self):
        """model_dump(exclude_none=True) skips unset optional fields."""
        decl = EvidenceDeclaration(
            run_id="test-run-003",
            repo_path="/tmp/test",
        )
        data = decl.model_dump(exclude_none=True)
        assert "reviewer_app_path" not in data
        assert "started_at" not in data


class TestEvidenceDeclarationWriter:
    """Test writing evidence declarations to YAML files."""

    def test_write_creates_file(self):
        """Writer creates a valid YAML file."""
        decl = EvidenceDeclaration(
            run_id="write-test-001",
            repo_path="/tmp/test-repo",
            final_verdict="COMPLETE",
        )
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            path = write_evidence_declaration(decl, Path(tmpdir))
            assert path.exists()
            content = path.read_text(encoding="utf-8")
            assert "run_id: write-test-001" in content
            assert "final_verdict: COMPLETE" in content

    def test_write_nested_dict(self):
        """Writer handles nested dictionaries."""
        decl = EvidenceDeclaration(
            run_id="nested-test",
            repo_path="/tmp/test",
            files_inspected={"config": ["a.yaml", "b.yaml"]},
        )
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            path = write_evidence_declaration(decl, Path(tmpdir))
            content = path.read_text(encoding="utf-8")
            assert "files_inspected:" in content
            assert "config:" in content
            assert "- a.yaml" in content

    def test_write_creates_parent_dirs(self):
        """Writer creates parent directories if needed."""
        decl = EvidenceDeclaration(
            run_id="dir-test",
            repo_path="/tmp/test",
        )
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            nested = Path(tmpdir) / "deep" / "nested" / "dir"
            path = write_evidence_declaration(decl, nested)
            assert path.exists()


class TestJsonSchemaExport:
    """Test JSON schema export."""

    def test_export_creates_valid_json(self):
        """Exported schema is valid JSON with expected structure."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            path = export_json_schema(Path(tmpdir) / "schema.json")
            assert path.exists()
            schema = json.loads(path.read_text(encoding="utf-8"))
            assert "properties" in schema
            assert "run_id" in schema["properties"]
            assert "final_verdict" in schema["properties"]

    def test_schema_requires_run_id_and_repo_path(self):
        """Schema marks run_id and repo_path as required."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            path = export_json_schema(Path(tmpdir) / "schema.json")
            schema = json.loads(path.read_text(encoding="utf-8"))
            assert "run_id" in schema.get("required", [])
            assert "repo_path" in schema.get("required", [])
