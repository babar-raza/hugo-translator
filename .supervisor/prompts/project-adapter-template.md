# Project Adapter Template
# Fill in this template to adapt the Post-Sprint Autonomy Loop to a new project
# Contract: .supervisor/schemas/project-adapter-contract.schema.json

---

## Project Identity

```yaml
project_name: "<YOUR_PROJECT_NAME>"
repo_root: "<ABSOLUTE_PATH_TO_REPO>"
```

## Evidence Configuration

```yaml
evidence_root_pattern: ".local/evidences/*"
final_package_format: "zip"  # zip | tar.gz | directory
```

## Plan and Taskcard Paths

```yaml
plan_paths:
  - "plans/master-plan.md"
taskcard_paths:
  - "taskcards/"
```

## Prompt Infrastructure

```yaml
prompt_folder_path: ".supervisor/prompts/"
prompt_registry_path: ".supervisor/prompts/prompt-registry.yaml"
```

## Test and Validation Commands

```yaml
test_commands:
  - "pytest -q"
validator_commands:
  - "python tools/supervisor/governance_validators.py"
build_commands: []
governance_commands:
  - "python tools/supervisor/supervisor_loop.py autonomous-cycle --declaration <declaration_path>"
```

## Path Governance

```yaml
protected_paths:
  - "AGENTS.md"
  - "GOVERNANCE.md"
  - "registry/format-registry.yaml"
  - "plans/master-plan.md"
allowed_mutation_paths:
  - ".supervisor/prompts/"
  - ".supervisor/schemas/"
  - "tools/supervisor/"
  - "tests/"
  - ".local/"
  - "reports/"
```

## Documentation and Skills

```yaml
docs_paths:
  - "docs/"
skills_paths:
  - ".claude/commands/"
agent_instruction_paths:
  - "AGENTS.md"
  - "CLAUDE.md"
```

## Schema and Policy

```yaml
declaration_schema_path: ".supervisor/schemas/evidence-declaration.schema.json"
policies_path: ".supervisor/policies.yaml"
```

## Project-Specific Configuration

```yaml
project_specific_gates: []
external_blockers: []
max_loop_iterations: 3
quality_threshold: 4  # minimum score per dimension (1-5)
```

---

## Adaptation Instructions

1. Copy this template to your project's `.supervisor/prompts/` directory
2. Fill in all `<PLACEHOLDER>` values
3. Adjust `test_commands` and `validator_commands` to match your project's tooling
4. Set `protected_paths` to files that must not be modified by the loop
5. Set `allowed_mutation_paths` to directories where the loop can write
6. Adjust `max_loop_iterations` based on project complexity
7. Save as `project-adapter.yaml` in your project root or `.supervisor/`
