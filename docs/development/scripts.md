# Operational Scripts

All helper scripts used by engineers, operators, and CI live here. Centralizing these entry points means we can audit automation changes independently from the core runtime.

## Script Families

- **Environment + Dependency Management** (`check_*`, `clone_conda_env.py`, `install_*.py`, `list_conda_envs.py`): keep local environments aligned with the production toolchain so reproducing issues is trivial.
- **Execution Harnesses** (`run_*`, `verify_*`, `validate_*`): wrap complex pytest invocations, GPU translations, or telemetry probes and guarantee every test suite runs with the same flags CI expects.
- **Migration + Data Integrity** (`migrate_*`, `populate_l3_index.py`, `build_l3_index.py`, `compare_systems.py`): manage Translation Memory population and safe transitions between schema versions.
- **Observability + Evidence Gathering** (`generate_*_report.py`, `collect_gpu_evidence.py`, `verify_implementation.py`): capture structured artifacts that flow into `reports/` so audits have raw inputs.
- **Operations + Safety** (`backup.sh`, `restore.sh`, `rollback.*`, `health_check.py`, `production_readiness_check.py`): enforce the runbooks that keep production stable.

When introducing a new automation entry point, drop it here and update this README so operators immediately know how it affects day-to-day system health.
