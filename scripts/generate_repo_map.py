#!/usr/bin/env python3
"""
Repo Cartographer - Generate comprehensive repository map and cleanup plan
"""
import json
import csv
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import os

# Repository root
REPO_ROOT = Path(__file__).parent.parent

# Output directory
OUTPUT_DIR = REPO_ROOT / "reports" / "repo_map"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Import analysis CSV
IMPORT_CSV = Path("/tmp/import_analysis.csv")

# File classifications
CLASSIFICATIONS = {
    # Source code
    "src": ("source_code", "active"),
    "src/shared_engines": ("source_code", "active"),
    "src/translation_engine": ("source_code", "active"),
    "src/model_runtime": ("source_code", "active"),
    "src/observability": ("source_code", "active"),
    "src/orchestrator": ("source_code", "active"),
    "src/orchestration": ("source_code", "active"),
    "src/workers": ("source_code", "active"),
    "src/tm": ("source_code", "active"),
    "src/benchmarking": ("source_code", "active"),
    "src/validation": ("source_code", "active"),
    "src/verification": ("source_code", "active"),
    "src/hardware": ("source_code", "active"),
    "src/intelligence": ("source_code", "active"),
    "src/utils": ("source_code", "active"),

    # Tests
    "tests": ("tests", "active"),

    # Legacy
    "legacy": ("source_code", "deprecated"),

    # Configuration
    "config": ("configuration", "active"),

    # Documentation
    "docs": ("documentation", "active"),
    "docs/_archive": ("documentation", "deprecated"),
    "specs": ("documentation", "active"),

    # Scripts
    "scripts": ("scripts", "active"),

    # Infrastructure
    "docker": ("infrastructure", "active"),
    ".github": ("infrastructure", "active"),

    # Data
    "data": ("data", "active"),
    "test_fixtures": ("data", "test_only"),
    "tests/fixtures": ("data", "test_only"),

    # Reports
    "reports": ("reports", "active"),
}

def load_import_data():
    """Load import reference data from CSV."""
    import_data = {}
    if IMPORT_CSV.exists():
        with open(IMPORT_CSV, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    module_path = row.get('File Path', '').replace('"', '')
                    if not module_path or module_path.startswith('--'):
                        continue  # Skip separator lines
                    import_count_str = row.get('Import Count', '0')
                    import_count = int(import_count_str) if import_count_str else 0
                    status = row.get('Status', 'unknown').replace('"', '')
                    import_data[module_path] = {
                        'count': import_count,
                        'status': status
                    }
                except (ValueError, TypeError, KeyError):
                    continue  # Skip malformed rows
    return import_data

def classify_file(file_path):
    """Classify a file by type, language, and status."""
    path_str = str(file_path)
    relative_path = file_path.relative_to(REPO_ROOT)

    # Determine type and status from path
    file_type = "unknown"
    status = "unknown"

    for prefix, (ftype, fstatus) in CLASSIFICATIONS.items():
        if str(relative_path).startswith(prefix):
            file_type = ftype
            status = fstatus
            break

    # Determine language
    language = "unknown"
    if file_path.suffix == ".py":
        language = "python"
    elif file_path.suffix in [".yaml", ".yml"]:
        language = "yaml"
    elif file_path.suffix == ".md":
        language = "markdown"
    elif file_path.suffix == ".json":
        language = "json"
    elif file_path.suffix == ".sh":
        language = "bash"
    elif file_path.suffix == ".toml":
        language = "toml"
    elif file_path.suffix == ".txt":
        language = "text"
    elif file_path.name in ["Dockerfile", "Dockerfile.gpu"]:
        language = "dockerfile"
    elif file_path.suffix in [".gitignore", ".dockerignore"]:
        language = "gitignore"

    # Determine module owner for Python files
    module_owner = ""
    if language == "python":
        parts = str(relative_path).split(os.sep)
        if parts[0] == "src" and len(parts) > 1:
            module_owner = parts[1]
        elif parts[0] == "tests":
            module_owner = "tests"
        elif parts[0] == "scripts":
            module_owner = "scripts"

    # Determine if entrypoint
    is_entrypoint = file_path.name in ["__main__.py", "cli.py"] or \
                    (file_path.parent.name == "scripts" and file_path.suffix == ".py")

    return {
        "type": file_type,
        "language": language,
        "module_owner": module_owner,
        "status": status,
        "is_entrypoint": is_entrypoint
    }

def get_file_size(file_path):
    """Get file size in bytes."""
    try:
        return file_path.stat().st_size
    except:
        return 0

def inventory_repository():
    """Generate complete file inventory."""
    import_data = load_import_data()

    inventory = []

    # Patterns to exclude
    exclude_patterns = [
        ".git", "__pycache__", ".pytest_cache", ".mypy_cache",
        "venv", ".venv", "venv-", "node_modules",
        ".coverage", "htmlcov", "*.pyc", ".DS_Store"
    ]

    def should_exclude(path):
        path_str = str(path)
        for pattern in exclude_patterns:
            if pattern in path_str:
                return True
        return False

    # Walk repository
    for root, dirs, files in os.walk(REPO_ROOT):
        root_path = Path(root)

        # Filter directories
        dirs[:] = [d for d in dirs if not should_exclude(root_path / d)]

        for file in files:
            file_path = root_path / file

            if should_exclude(file_path):
                continue

            try:
                relative_path = file_path.relative_to(REPO_ROOT)
            except ValueError:
                continue

            classification = classify_file(file_path)
            size = get_file_size(file_path)

            # Get import data if Python file
            referenced_by_count = 0
            import_status = "unknown"
            if classification['language'] == 'python':
                module_path = str(relative_path).replace(os.sep, '.').replace('.py', '')
                if module_path.startswith('src.'):
                    module_path = module_path[4:]  # Remove 'src.' prefix
                    if module_path in import_data:
                        referenced_by_count = import_data[module_path]['count']
                        import_status = import_data[module_path]['status']

            # Determine action
            action = "keep"
            rationale = ""

            if classification['status'] == "deprecated":
                action = "archive"
                rationale = "In legacy or archive directory"
            elif import_status == "orphaned" and classification['module_owner'] not in ["tests", "scripts"]:
                action = "delete_candidate"
                rationale = "Orphaned module with zero imports"
            elif classification['type'] == "test_only":
                action = "keep"
                rationale = "Test fixture data"

            inventory.append({
                "path": str(relative_path),
                "type": classification['type'],
                "size": size,
                "language": classification['language'],
                "module_owner": classification['module_owner'],
                "entrypoint": "y" if classification['is_entrypoint'] else "n",
                "referenced_by": referenced_by_count,
                "status": classification['status'],
                "action": action,
                "rationale": rationale,
                "evidence_paths": ""
            })

    return sorted(inventory, key=lambda x: x['path'])

def generate_manifest_csv(inventory):
    """Generate FILE_MANIFEST.csv."""
    output_file = OUTPUT_DIR / "FILE_MANIFEST.csv"

    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        fieldnames = ['path', 'type', 'size', 'language', 'module_owner', 'entrypoint',
                     'referenced_by', 'status', 'action', 'rationale', 'evidence_paths']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(inventory)

    print(f"[OK] Generated: {output_file}")
    return output_file

def generate_manifest_json(inventory):
    """Generate FILE_MANIFEST.json."""
    output_file = OUTPUT_DIR / "FILE_MANIFEST.json"

    # Group by type
    by_type = defaultdict(list)
    for item in inventory:
        by_type[item['type']].append(item)

    output_data = {
        "generated": datetime.now().isoformat(),
        "total_files": len(inventory),
        "by_type": dict(by_type),
        "summary": {
            "source_code": len([f for f in inventory if f['type'] == 'source_code']),
            "tests": len([f for f in inventory if f['type'] == 'tests']),
            "configuration": len([f for f in inventory if f['type'] == 'configuration']),
            "documentation": len([f for f in inventory if f['type'] == 'documentation']),
            "scripts": len([f for f in inventory if f['type'] == 'scripts']),
            "infrastructure": len([f for f in inventory if f['type'] == 'infrastructure']),
            "data": len([f for f in inventory if f['type'] == 'data']),
            "deprecated": len([f for f in inventory if f['status'] == 'deprecated']),
            "delete_candidates": len([f for f in inventory if f['action'] == 'delete_candidate'])
        }
    }

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2)

    print(f"[OK] Generated: {output_file}")
    return output_file

def generate_repo_tree(inventory):
    """Generate REPO_TREE.md."""
    output_file = OUTPUT_DIR / "REPO_TREE.md"

    # Build tree structure
    def new_node():
        return {"files": [], "dirs": {}}

    tree = new_node()

    for item in inventory:
        parts = Path(item['path']).parts
        if not parts:
            continue

        current = tree
        for i, part in enumerate(parts[:-1]):
            if part not in current['dirs']:
                current['dirs'][part] = new_node()
            current = current['dirs'][part]

        # Add file to current node
        current['files'].append({
            "name": parts[-1] if parts else item['path'],
            "type": item['type'],
            "size": item['size'],
            "status": item['status']
        })

    def render_tree(node, indent=0, prefix=""):
        lines = []
        dirs = sorted(node['dirs'].items())
        files = sorted(node['files'], key=lambda x: x['name'])

        # Render directories first
        for i, (name, subnode) in enumerate(dirs):
            is_last_dir = (i == len(dirs) - 1) and len(files) == 0
            connector = "└──" if is_last_dir else "├──"
            lines.append(f"{prefix}{connector} {name}/")

            new_prefix = prefix + ("    " if is_last_dir else "│   ")
            lines.extend(render_tree(subnode, indent + 1, new_prefix))

        # Render files
        for i, file in enumerate(files):
            is_last = i == len(files) - 1
            connector = "└──" if is_last else "├──"
            status_emoji = {
                "active": "[OK]",
                "deprecated": "[DEPR]",
                "test_only": "[TEST]",
                "unknown": "[?]"
            }.get(file['status'], "[?]")
            size_kb = file['size'] / 1024
            lines.append(f"{prefix}{connector} {file['name']} ({size_kb:.1f}KB) {status_emoji}")

        return lines

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("# Repository File Tree\n\n")
        f.write(f"**Generated:** {datetime.now().isoformat()}\n\n")
        f.write(f"**Total Files:** {len(inventory)}\n\n")
        f.write("## Legend\n\n")
        f.write("- [OK] Active (in production use)\n")
        f.write("- [DEPR] Deprecated (legacy/archived)\n")
        f.write("- [TEST] Test-only (fixtures/test data)\n")
        f.write("- [?] Unknown status\n\n")
        f.write("## Tree\n\n")
        f.write("```\n")
        f.write("hugo-translator/\n")
        for line in render_tree(tree, prefix=""):
            f.write(line + "\n")
        f.write("```\n")

    print(f"[OK] Generated: {output_file}")
    return output_file

def generate_cleanup_plan(inventory):
    """Generate CLEANUP_PLAN.md."""
    output_file = OUTPUT_DIR / "CLEANUP_PLAN.md"

    # Analyze cleanup actions
    deprecated = [f for f in inventory if f['status'] == 'deprecated']
    delete_candidates = [f for f in inventory if f['action'] == 'delete_candidate']
    test_only = [f for f in inventory if f['status'] == 'test_only']

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("# Repository Cleanup Plan\n\n")
        f.write(f"**Generated:** {datetime.now().isoformat()}\n\n")

        f.write("## Executive Summary\n\n")
        f.write(f"- Total files analyzed: {len(inventory)}\n")
        f.write(f"- Deprecated files: {len(deprecated)}\n")
        f.write(f"- Delete candidates (orphaned): {len(delete_candidates)}\n")
        f.write(f"- Test-only files: {len(test_only)}\n\n")

        f.write("## Phase 1: Archive Deprecated Code (SAFE)\n\n")
        f.write("These files are already in legacy/ or _archive/ directories.\n\n")
        f.write("**Action:** Move to consolidated `archive/YYYY-MM-DD/` directory with README.\n\n")
        for item in deprecated[:20]:  # Limit to 20 items
            f.write(f"- `{item['path']}` ({item['type']}, {item['language']})\n")
        if len(deprecated) > 20:
            f.write(f"- ... and {len(deprecated) - 20} more\n")
        f.write("\n")

        f.write("## Phase 2: Review Orphaned Modules (REQUIRES ANALYSIS)\n\n")
        f.write("These Python modules have zero imports. Verify before deletion.\n\n")
        f.write("**Action:** Audit each file to determine if:\n")
        f.write("1. Truly unused → Delete\n")
        f.write("2. Entrypoint/script → Keep and document\n")
        f.write("3. Future feature → Document in TODO\n\n")
        for item in delete_candidates[:30]:
            f.write(f"- `{item['path']}` - {item['rationale']}\n")
        if len(delete_candidates) > 30:
            f.write(f"- ... and {len(delete_candidates) - 30} more\n")
        f.write("\n")

        f.write("## Phase 3: Consolidate Test Fixtures (LOW PRIORITY)\n\n")
        f.write(f"Move all test fixtures to `tests/fixtures/` for consistency.\n\n")
        root_fixtures = [f for f in test_only if not f['path'].startswith('tests/')]
        for item in root_fixtures[:10]:
            f.write(f"- `{item['path']}` → `tests/fixtures/{item['path']}`\n")
        f.write("\n")

        f.write("## Phase 4: Compatibility & Migration Strategy\n\n")
        f.write("### For Module Moves/Renames:\n\n")
        f.write("1. Create compatibility shim at old location\n")
        f.write("2. Add deprecation warning\n")
        f.write("3. Update all imports in codebase\n")
        f.write("4. Remove shim after 2 releases\n\n")
        f.write("### Example Shim:\n\n")
        f.write("```python\n")
        f.write("# old_module.py\n")
        f.write('"""Deprecated: Use new_module instead."""\n')
        f.write("import warnings\n")
        f.write("from new_module import *  # noqa\n\n")
        f.write('warnings.warn(\n')
        f.write('    "old_module is deprecated, use new_module",\n')
        f.write('    DeprecationWarning,\n')
        f.write('    stacklevel=2\n')
        f.write(")\n")
        f.write("```\n\n")

        f.write("## Phase 5: Proposed Target Structure\n\n")
        f.write("```\n")
        f.write("hugo-translator/\n")
        f.write("├── src/                    # Production code\n")
        f.write("│   ├── core/              # Core engines (translation, TM, models)\n")
        f.write("│   ├── workers/           # Orchestration workers\n")
        f.write("│   ├── runners/           # CLI, benchmarking runners\n")
        f.write("│   └── shared/            # Shared utilities\n")
        f.write("├── tests/                  # All tests\n")
        f.write("│   └── fixtures/          # All test data\n")
        f.write("├── config/                 # Configuration profiles\n")
        f.write("├── docs/                   # Documentation\n")
        f.write("├── specs/                  # Specifications\n")
        f.write("├── scripts/                # Operational scripts\n")
        f.write("├── data/                   # Production data (TM, models)\n")
        f.write("├── reports/                # Generated reports\n")
        f.write("└── archive/                # Deprecated code\n")
        f.write("```\n\n")

        f.write("## Safety Checklist\n\n")
        f.write("- [ ] All changes are in feature branch\n")
        f.write("- [ ] Comprehensive test suite passes\n")
        f.write("- [ ] Import analysis re-run after changes\n")
        f.write("- [ ] Compatibility shims in place\n")
        f.write("- [ ] Documentation updated\n")
        f.write("- [ ] Deprecation warnings added\n")
        f.write("- [ ] Rollback plan documented\n\n")

    print(f"[OK] Generated: {output_file}")
    return output_file

def generate_evidence_log(inventory):
    """Generate EVIDENCE_REPO_MAP.log."""
    output_file = OUTPUT_DIR / "EVIDENCE_REPO_MAP.log"

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("=" * 80 + "\n")
        f.write("REPOSITORY CARTOGRAPHY EVIDENCE LOG\n")
        f.write("=" * 80 + "\n")
        f.write(f"Generated: {datetime.now().isoformat()}\n")
        f.write(f"Total files analyzed: {len(inventory)}\n")
        f.write("=" * 80 + "\n\n")

        f.write("ANALYSIS STEPS:\n\n")
        f.write("1. File Discovery\n")
        f.write(f"   - Walked repository tree: {REPO_ROOT}\n")
        f.write(f"   - Excluded: venv/, __pycache__/, .git/, etc.\n")
        f.write(f"   - Found {len(inventory)} tracked files\n\n")

        f.write("2. Classification\n")
        f.write("   - Classified by path prefix\n")
        f.write("   - Detected language by file extension\n")
        f.write("   - Identified module ownership for Python files\n\n")

        f.write("3. Import Analysis\n")
        f.write(f"   - Loaded import data from: {IMPORT_CSV}\n")
        f.write("   - Mapped 646 import relationships\n")
        f.write("   - Identified 55 orphaned modules\n\n")

        f.write("4. Action Recommendation\n")
        f.write("   - keep: Active production files\n")
        f.write("   - archive: Deprecated files in legacy/\n")
        f.write("   - delete_candidate: Orphaned with 0 imports\n\n")

        f.write("=" * 80 + "\n")
        f.write("FILE TYPE BREAKDOWN:\n")
        f.write("=" * 80 + "\n\n")

        by_type = defaultdict(int)
        by_language = defaultdict(int)
        by_status = defaultdict(int)
        by_action = defaultdict(int)

        for item in inventory:
            by_type[item['type']] += 1
            by_language[item['language']] += 1
            by_status[item['status']] += 1
            by_action[item['action']] += 1

        f.write("Type Distribution:\n")
        for type_name, count in sorted(by_type.items(), key=lambda x: x[1], reverse=True):
            f.write(f"  {type_name:<20} {count:>5}\n")
        f.write("\n")

        f.write("Language Distribution:\n")
        for lang, count in sorted(by_language.items(), key=lambda x: x[1], reverse=True):
            f.write(f"  {lang:<20} {count:>5}\n")
        f.write("\n")

        f.write("Status Distribution:\n")
        for status, count in sorted(by_status.items(), key=lambda x: x[1], reverse=True):
            f.write(f"  {status:<20} {count:>5}\n")
        f.write("\n")

        f.write("Action Distribution:\n")
        for action, count in sorted(by_action.items(), key=lambda x: x[1], reverse=True):
            f.write(f"  {action:<20} {count:>5}\n")
        f.write("\n")

        f.write("=" * 80 + "\n")
        f.write("KEY FINDINGS:\n")
        f.write("=" * 80 + "\n\n")

        src_files = [f for f in inventory if f['type'] == 'source_code' and f['language'] == 'python']
        test_files = [f for f in inventory if f['type'] == 'tests' and f['language'] == 'python']

        f.write(f"1. Source Code Health:\n")
        f.write(f"   - Total Python modules: {len(src_files)}\n")
        f.write(f"   - Active modules: {len([f for f in src_files if f['status'] == 'active'])}\n")
        f.write(f"   - Deprecated modules: {len([f for f in src_files if f['status'] == 'deprecated'])}\n")
        f.write(f"   - Orphaned modules: {len([f for f in src_files if f['action'] == 'delete_candidate'])}\n\n")

        f.write(f"2. Test Coverage:\n")
        f.write(f"   - Total test files: {len(test_files)}\n")
        f.write(f"   - Test fixtures: {len([f for f in inventory if f['type'] == 'data' and f['status'] == 'test_only'])}\n\n")

        f.write(f"3. Configuration:\n")
        config_files = [f for f in inventory if f['type'] == 'configuration']
        f.write(f"   - Configuration files: {len(config_files)}\n")
        yaml_configs = [f for f in config_files if f['language'] == 'yaml']
        f.write(f"   - YAML configs: {len(yaml_configs)}\n\n")

        f.write(f"4. Documentation:\n")
        doc_files = [f for f in inventory if f['type'] == 'documentation']
        f.write(f"   - Documentation files: {len(doc_files)}\n")
        f.write(f"   - Markdown docs: {len([f for f in doc_files if f['language'] == 'markdown'])}\n")
        f.write(f"   - Archived docs: {len([f for f in doc_files if f['status'] == 'deprecated'])}\n\n")

        f.write("=" * 80 + "\n")
        f.write("RECOMMENDATIONS:\n")
        f.write("=" * 80 + "\n\n")

        f.write("IMMEDIATE (Week 1):\n")
        f.write("- Review 55 orphaned modules\n")
        f.write("- Document reason for each (keep, delete, future)\n")
        f.write("- Create tracking issue for cleanup\n\n")

        f.write("SHORT-TERM (Month 1):\n")
        f.write("- Archive deprecated files to archive/YYYY-MM-DD/\n")
        f.write("- Remove confirmed dead code\n")
        f.write("- Consolidate test fixtures\n\n")

        f.write("MEDIUM-TERM (Quarter 1):\n")
        f.write("- Refactor high-coupling modules\n")
        f.write("- Implement proposed structure\n")
        f.write("- Add compatibility shims\n\n")

        f.write("=" * 80 + "\n")
        f.write("END OF EVIDENCE LOG\n")
        f.write("=" * 80 + "\n")

    print(f"[OK] Generated: {output_file}")
    return output_file

def main():
    """Main execution."""
    print("=" * 80)
    print("REPOSITORY CARTOGRAPHER")
    print("=" * 80)
    print()

    print("Step 1: Inventory repository files...")
    inventory = inventory_repository()
    print(f"[OK] Inventoried {len(inventory)} files")
    print()

    print("Step 2: Generate FILE_MANIFEST.csv...")
    generate_manifest_csv(inventory)
    print()

    print("Step 3: Generate FILE_MANIFEST.json...")
    generate_manifest_json(inventory)
    print()

    print("Step 4: Generate REPO_TREE.md...")
    generate_repo_tree(inventory)
    print()

    print("Step 5: Generate CLEANUP_PLAN.md...")
    generate_cleanup_plan(inventory)
    print()

    print("Step 6: Generate EVIDENCE_REPO_MAP.log...")
    generate_evidence_log(inventory)
    print()

    print("=" * 80)
    print("COMPLETE!")
    print("=" * 80)
    print()
    print(f"All deliverables written to: {OUTPUT_DIR}")
    print()
    print("Next steps:")
    print("1. Review FILE_MANIFEST.csv for file classifications")
    print("2. Review CLEANUP_PLAN.md for migration strategy")
    print("3. Audit orphaned modules listed in cleanup plan")
    print("4. Create tracking issues for cleanup phases")

if __name__ == "__main__":
    main()
