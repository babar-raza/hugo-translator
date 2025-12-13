# Source Layout

This directory contains all production code for the Hugo Translation System. Changes here directly impact runtime behavior, so understanding the submodules is required before touching anything.

## Submodules

| Folder | Responsibilities | Operational impact |
| --- | --- | --- |
| `hardware/` | Hardware detection, capability probing, and scheduler hints. | Keeps GPU/CPU feature detection accurate so the orchestrator never schedules incompatible jobs. |
| `intelligence/` | Heuristics, decision engines, and experimentation logic. | Governs how the system adapts translation strategies in response to telemetry. |
| `model_runtime/` | Model loaders, quantization helpers, and runtime adapters. | Determines which models are available at runtime and how they are tuned for latency. |
| `observability/` | Logging, metrics, tracing, and structured event emission. | Powers the dashboards and alerting that SRE relies on for production health. |
| `orchestration/` | Queue configuration, routing policies, and scheduling rules shared across services. | Ensures multi-stage workflows stay in sync when new job types are added. |
| `orchestrator/` | The orchestrator service entry point and task processors. | Executes the work graph; bugs here directly halt production pipelines. |
| `tm/` | Translation Memory layers (L1 cache, L2 LMDB, L3 FAISS). | Preserves linguistic consistency and gives us the 5-10x throughput boost. |
| `translation_engine/` | Parsers, segment extractors, reconstructor, and validator glue. | Owns the Hugo-specific translation workflow and is where most business logic lives. |
| `utils/` | Shared helpers (config loaders, file utilities, retry logic). | Reduces duplication across services and keeps failure handling consistent. |
| `validation/` | Schema validation, input sanitizers, and guard rails. | Blocks malformed configs/content from reaching translators. |
| `workers/` | MCP tool implementations and worker bootstrap code. | Exposes the translation capabilities to external systems through the worker interface. |

## Root Modules

- `cli.py` provides the command-line interface used by operators and tests.
- `__init__.py` wires the package so submodules can be imported cleanly.

Python cache folders (`__pycache__/`) are generated artifacts and should not be edited.
