# Scripts Directory

Utility scripts for the Hugo Translation System.

## validate-evidence.py

Validates evidence citations in specifications to detect stale references.

### Usage

```bash
# Validate all specs
python scripts/validate-evidence.py --all

# Validate specific file
python scripts/validate-evidence.py specs/features/cli-001-main-translate.md

# Generate report
python scripts/validate-evidence.py --all --report reports/driftless/evidence_validation_report.md
```

### Checks Performed

- File exists at cited path
- Line numbers are within file bounds
- Line ranges are valid (end >= start)

### Exit Codes

- `0` - All citations valid
- `1` - Invalid citations found
- `2` - Error (file not found, invalid arguments)

## lint-specs.py

Automated spec-lint checker for specification quality.

### Usage

```bash
# Check all specs
python scripts/lint-specs.py --all

# Check specific file
python scripts/lint-specs.py specs/features/cli-001-main-translate.md

# Auto-fix violations (when supported)
python scripts/lint-specs.py --fix --all
```

### Checks Implemented

- **RULE-S1:** File naming (must match {category}-{number}-{slug}.md)
- **RULE-S2:** Required frontmatter fields
- **RULE-T1:** spec_id exists in inventory
- **RULE-ST1:** Valid status values

### Exit Codes

- `0` - All checks passed
- `1` - Violations found
- `2` - Error (file not found, invalid YAML)
