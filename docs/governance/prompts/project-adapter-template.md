# Project Adapter Template

## Purpose
This template adapts the post-sprint autonomy loop to a specific project. Copy this file, fill in the values, and save as `project-adapter.yaml` in the prompt folder or project root.

## Template

```yaml
# Project Adapter Configuration
# Copy and customize for each project using the autonomy loop.

project:
  name: ""                    # e.g., "hugo-translator-gitlab"
  repo_root: ""               # Absolute path to repo root
  branch: "main"              # Default branch

paths:
  evidence_root: ".local/evidences"
  sprint_loop_data: "data/sprint-loop"
  plan_files: "plans/"
  taskcard_files: "data/task_queue.jsonl"
  prompt_folder: "docs/governance/prompts"
  prompt_registry: "docs/governance/prompts/prompt-registry.yaml"
  schemas: "schemas/"
  docs: "docs/"
  skills: []                  # Paths to skill definitions if any
  agent_instructions: []      # Paths to agent instruction files
  protected_paths:            # Files that must not be modified
    - "config/global.yaml"    # Only add sprint_loop section
    - ".github/workflows/"
  allowed_mutation_paths:     # Directories where changes are allowed
    - "src/"
    - "tests/"
    - "scripts/"
    - "docs/"
    - "config/"
    - "schemas/"

commands:
  test: "python -m pytest tests/ -v"
  lint: "ruff check src/ tests/"
  format_check: "black --check src/ tests/"
  security_scan: "bandit -r src/"
  governance_check: "python scripts/ci/check_governance.py"
  manifest_check: "python scripts/ci/check_manifest.py --strict"
  evidence_validate: "python scripts/quality/validate-evidence.py"
  quality_score: "python scripts/ops/sprint_quality_scorer.py --dry-run"
  loop_controller: "python scripts/ops/sprint_loop_controller.py"

gates:
  pre_execution:
    - "git status is clean or changes are classified"
    - "Plan has been through readiness gate"
  post_execution:
    - "All tests pass"
    - "Quality scores >= 4.0 overall"
    - "Evidence bundle exists and validates"
    - "No dimension below 3.0"
  release:
    - "CI pipeline passes"
    - "Governance check passes"
    - "Manifest check passes"

external_blockers: []         # List known external blockers
  # - description: "API key not available"
  #   affects: ["TC-001"]
  #   status: "BLOCKED"

evidence:
  package_format: "directory"  # "directory" or "zip"
  required_artifacts:
    - "evidence-declaration.yaml"
    - "run-log.md"
    - "quality-scores.json"
    - "taskcard-status.yaml"

quality:
  rubric_path: "config/sprint_quality_rubric.yaml"
  overall_minimum: 4.0
  dimension_minimum: 3.0
  critical_dimensions:
    - correctness: 4.0
    - completeness: 4.0
```

## Usage
1. Copy this template to your project
2. Fill in all paths and commands
3. Reference the adapter in loop controller invocations:
   ```bash
   python scripts/ops/sprint_loop_controller.py \
     --run-dir data/sprint-loop/<id> \
     --adapter project-adapter.yaml
   ```
4. The controller reads the adapter to find prompt assets, schemas, and commands
