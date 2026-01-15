# Entrypoints

## CLI Entrypoints

### translate-hugo
- **Description**: Main CLI for translating Hugo sites
- **Evidence**: [`evidence-001`](specs/_evidence_index.yml:evidence-001), [`evidence-008`](specs/_evidence_index.yml:evidence-008)
- **Command**: `translate-hugo --site <site_id> --input <path> --target-langs <lang1> <lang2>`

## Docker Services

### orchestrator
- **Description**: Translation orchestrator service
- **Evidence**: [`evidence-002`](specs/_evidence_index.yml:evidence-002), [`evidence-020`](specs/_evidence_index.yml:evidence-020)
- **Command**: `docker-compose up orchestrator`

### worker-cpu
- **Description**: CPU-based translation worker
- **Evidence**: [`evidence-003`](specs/_evidence_index.yml:evidence-003)
- **Command**: `docker-compose up worker-cpu`

### worker-gpu
- **Description**: GPU-based translation worker
- **Evidence**: [`evidence-004`](specs/_evidence_index.yml:evidence-004), [`evidence-021`](specs/_evidence_index.yml:evidence-021)
- **Command**: `docker-compose up worker-gpu`

### prometheus
- **Description**: Metrics collection and alerting
- **Evidence**: [`evidence-005`](specs/_evidence_index.yml:evidence-005)
- **Command**: `docker-compose up prometheus`

### pushgateway
- **Description**: Metrics push gateway for batch jobs
- **Evidence**: [`evidence-006`](specs/_evidence_index.yml:evidence-006)
- **Command**: `docker-compose up pushgateway`

### grafana
- **Description**: Metrics visualization dashboard
- **Evidence**: [`evidence-007`](specs/_evidence_index.yml:evidence-007)
- **Command**: `docker-compose up grafana`

## Python Module Entrypoints

### src.orchestrator
- **Description**: Orchestrator module entrypoint
- **Evidence**: [`evidence-009`](specs/_evidence_index.yml:evidence-009)
- **Command**: `python -m src.orchestrator`

### src.workers.translation_worker
- **Description**: Translation worker entrypoint
- **Evidence**: [`evidence-010`](specs/_evidence_index.yml:evidence-010)
- **Command**: `python -m src.workers.translation_worker`

### src.workers.job_processor
- **Description**: Job processor entrypoint
- **Evidence**: [`evidence-011`](specs/_evidence_index.yml:evidence-011)
- **Command**: `python -m src.workers.job_processor`

### src.model_runtime.recommender
- **Description**: Model recommender CLI
- **Evidence**: [`evidence-012`](specs/_evidence_index.yml:evidence-012)
- **Command**: `python -m src.model_runtime.recommender`

### src.model_runtime.ct2_converter
- **Description**: CT2 model converter
- **Evidence**: [`evidence-013`](specs/_evidence_index.yml:evidence-013)
- **Command**: `python -m src.model_runtime.ct2_converter`

### src.benchmarking.cli
- **Description**: Benchmarking CLI tools
- **Evidence**: [`evidence-014`](specs/_evidence_index.yml:evidence-014)
- **Command**: `python -m src.benchmarking.cli`

### src.benchmarking.system_info
- **Description**: System information tool
- **Evidence**: [`evidence-015`](specs/_evidence_index.yml:evidence-015)
- **Command**: `python -m src.benchmarking.system_info`

### src.benchmarking.runner
- **Description**: Benchmarking runner
- **Evidence**: [`evidence-016`](specs/_evidence_index.yml:evidence-016)
- **Command**: `python -m src.benchmarking.runner`

### src.hardware.gpu_manager
- **Description**: GPU management tool
- **Evidence**: [`evidence-017`](specs/_evidence_index.yml:evidence-017)
- **Command**: `python -m src.hardware.gpu_manager`

### src.observability.metrics_tail
- **Description**: Metrics tail utility
- **Evidence**: [`evidence-018`](specs/_evidence_index.yml:evidence-018)
- **Command**: `python -m src.observability.metrics_tail`
