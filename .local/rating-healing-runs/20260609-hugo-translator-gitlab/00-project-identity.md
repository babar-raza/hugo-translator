# Phase 0 - Project Identity

## Basic Identity
- **Project Name**: Hugo Translation System
- **Project Slug**: hugo-translator-gitlab
- **Path**: C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator-gitlab
- **Git Repository**: Yes
- **Current Branch**: main
- **Uncommitted Changes**: 2 files (config/site_profiles/docs.aspose.org.yaml, config/site_profiles/reference.aspose.org.yaml)

## Recent Commits (top 10)
- 2bba845 docs(deployment): rewrite windows-native-deployment and WORKER_DEPLOYMENT for orchestrator
- a8ce748 fix(orchestrator+mt): load env vars from .env, harden daemon loop, revert max_new_tokens to 512
- 94eaae3 fix(orchestrator): add --log-file, fix pid_file_name in status, add 5-min auto-restart task
- aeea5f6 fix(tests+engine): resolve all 22 pre-existing test failures and runtime bugs
- c390d4a fix(content-worker): set content repo env vars and remap stale queue paths
- 378aecf fix(orchestrator): resolve relative exe path for Windows Popen launch
- fe2344a fix(orchestrator): anchor CWD and harden worker launch gates
- 7790cae fix(orchestrator): resolve 6 root causes behind silent no-work cycles
- e7de521 test(scope): prove real worker-path chain and strengthen forwarding tests
- f946975 fix(scope): prove and complete family-aware translator metrics pipeline

## Language / Runtime
- **Primary Language**: Python 3.10+
- **Package Manager**: pip / setuptools (pyproject.toml)
- **Requirements**: requirements/base.txt, cpu.txt, dev.txt, gpu.txt
- **Entry Point**: `translate-hugo` CLI (src.cli:main), also `python -m src`

## Source Structure (238 .py files under src/)
- src/cli.py - Main CLI interface
- src/validation/ - Quality validator (quality_validator.py)
- src/translation_engine/ - Core translation engine with AST, language detection
- src/orchestration/ - Batch optimizer, health monitor
- src/orchestrator/ - MCP-based orchestrator (scheduler, watcher, queue, redis)
- src/workers/ - Autonomous workers (content, verification, TM improvement)
- src/tm/ - Translation Memory (L1/L2/L3 cache layers)
- src/shared_engines/ - Shared translation backends
- src/queues/ - Queue management
- src/model_runtime/ - Model loading and runtime
- src/observability/ - Metrics, telemetry, git commit helper
- src/benchmarking/ - Benchmarking subsystem
- src/hardware/ - Hardware detection (GPU/CPU)
- src/intelligence/ - Intelligence subsystem
- src/utils/ - Config loader, utilities
- src/verification/ - Verification subsystem
- src/feature_flags.py - Feature flags

## Tests (472 test files)
- tests/unit/ - Unit tests (phased: phase-0 through phase-8, plus module-specific)
- tests/integration/ - Integration tests
- tests/contract/ - Contract tests (invariant verification)
- tests/regression/ - Regression tests
- tests/e2e/ - End-to-end tests
- tests/smoke/ - Smoke tests
- tests/golden/ - Golden file tests
- tests/performance/ - Performance tests
- tests/load/ - Load tests
- tests/validation/ - Validation-specific tests
- tests/verification/ - Verification tests
- tests/observability/ - Observability tests
- tests/conftest.py - Shared fixtures

## CI/Workflow Files
- .github/workflows/cli_tests.yml - CLI static analysis + execution + runtime tests
- .github/workflows/release_gate.yml - Unit tests, regression tests, quality gate (lint + audit)
- .github/workflows/telemetry_health_check.yml
- .github/workflows/worker_health_check.yml
- .github/workflows/content_structure_scan.yml

## Key Scripts
- scripts/quality_gates.py - Automated quality gate runner
- scripts/check_invariants.py - Invariant checker for translations
- scripts/production_readiness_check.py - Production readiness checker
- scripts/validate-evidence.py - Evidence validation
- scripts/audit_translation_quality.py - Translation quality audit
- scripts/shipcheck_robust.py - Ship check

## Configuration
- config/quality_gates.yaml - Quality gate thresholds
- config/validation.yaml - Validation engine config (11 validators)
- config/global.yaml - Global settings
- config/workers.yaml - Worker configuration
- config/model_registry.yaml - Model registry
- config/site_profiles/ - Per-site translation profiles
- config/terminology/ - Terminology glossaries

## Documentation
- README.md - Main readme
- docs/ - Extensive docs (architecture, deployment, guides, operations, etc.)
- CHANGELOG.md, CONTRIBUTING.md, AGENTS.md, TASK_BACKLOG.md
- Dockerfile, Dockerfile.gpu, docker-compose.yml

## Publication/Deployment
- Docker-based deployment (Dockerfile, Dockerfile.gpu, docker-compose.yml)
- Windows worker deployment scripts (scripts/deploy_windows_worker.ps1, START_WORKERS.bat)
- Orchestrator-based worker management
- No live publish/release automation detected (no PyPI publish workflow)

## Agentic Workflow
- AGENTS.md present (agent guardrails)
- Autonomous workers (content translation, verification, TM improvement)
- Orchestrator with scheduler, watcher, queue
- No explicit taskcard state machine detected
