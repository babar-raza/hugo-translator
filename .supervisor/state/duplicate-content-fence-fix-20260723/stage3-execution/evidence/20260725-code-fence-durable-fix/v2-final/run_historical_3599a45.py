"""Read-only full-corpus audit runner for the v2 comparison baseline."""
from __future__ import annotations

import subprocess
from pathlib import Path


source = subprocess.check_output(
    ["git", "show", "3599a45:scripts/quality/audit_all_content.py"],
    text=True,
    encoding="utf-8",
)
audit_path = Path("scripts/quality/audit_all_content.py").resolve()
namespace = {"__name__": "historical_audit_all_content", "__file__": str(audit_path)}
exec(compile(source, str(audit_path), "exec"), namespace)
namespace["scan"](output_path=None)
