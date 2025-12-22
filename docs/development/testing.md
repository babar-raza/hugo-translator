# Test Suite Overview

All automated tests for the Hugo Translation System live in this directory. Test artifacts were consolidated here so every gate (unit, integration, performance, production validation, etc.) can be executed from one place before a release is promoted.

## Subfolders and Operational Impact

| Folder | Focus | Operational impact |
| --- | --- | --- |
| `docs/` | Living notes for test charters, acceptance criteria, and manual checklists. | Keeps the engineering team aligned on what must pass before sign-off. |
| `fixtures/` | YAML/JSON fixtures plus reusable helper modules. | Provides deterministic data so regressions surface immediately. |
| `golden_corpus/` | Canonical translation samples and baseline outputs. | Detects semantic drift in TM/model behavior by diffing against expected text. |
| `hardware/` | GPU/CPU capability probes and failover tests. | Prevents deploying to hardware that cannot run the configured model set. |
| `integration/` | Cross-component scenarios that stitch together config, TM, workers, and orchestration. | Validates that critical workflows stay green after code or config changes. |
| `load/` | Stress tests for queue depth, worker pools, and throughput. | Protects SLOs by catching performance regressions before they hit production. |
| `logs/` | Captured raw pytest logs such as `live_test_cuda_output.log`. | Supplies evidence when auditing flaky behavior in CI. |
| `migration/` | Verification for migration utilities and data backfills. | Ensures TM upgrades or schema migrations do not corrupt historical data. |
| `models/` | Model selection, download, and runtime validation tests. | Guarantees the orchestrator always selects a working model/hardware pair. |
| `observability/` | Metrics/log compliance tests. | Confirms Prometheus/Grafana views stay accurate so operators can trust alerts. |
| `operations/` | Day-2-ops validation (backup/restore, housekeeping). | Verifies runbooks remain executable before the on-call rotation picks them up. |
| `orchestration/` | Scheduler, queue routing, and worker lifecycle tests. | Prevents job starvation or stuck translations in production queues. |
| `performance/` | Micro-benchmarks around TM lookups, parser speed, and batching. | Provides hard data for capacity planning and tuning thresholds. |
| `production/` | Production readiness suites executed before cutovers. | Acts as the final block on promoting a build to customers. |
| `regression/` | Targeted tests for previously fixed bugs (nested arrays, YAML fixes, etc.). | Keeps known failure modes from resurfacing silently. |
| `results/` | Aggregated outputs such as `test_results.txt`. | Gives auditors a single artifact showing what ran during the current cycle. |
| `smoke/` | Lightweight sanity checks. | Offers a fast “go/no-go” signal for quick local changes. |
| `tm/` | Translation Memory (L1/L2/L3) correctness tests. | Maintains TM integrity so repeated translations remain accurate. |
| `unit/` | Core code-level tests split by implementation phase. | Catches low-level regressions before they amplify in larger suites. |
| `validation/` | Input validation and schema guardrails. | Protects the translators from malformed content or configs. |
| `verification/` | Cross-system evidence gathering and checklist automation. | Supplies documentation required by compliance and release managers. |

Generated Python cache folders (`__pycache__/`) are ignored and carry no operational meaning.
