# Runtime Units

## Overview

This document describes the runtime units discovered in the Hugo Translation System. Runtime units are executable components that can be started independently and perform specific functions within the system.

## Runtime Units by Category

### Core Services

#### Orchestrator
- **ID**: `orchestrator`
- **Description**: Coordinates translation operations and manages job queues
- **Start Method**: `docker-compose up orchestrator`
- **Ports**: 8000
- **Dependencies**: redis, config
- **Config Knobs**: MODE, SWEEP_INTERVAL_HOURS, CONFIG_PATH

#### Redis
- **ID**: `redis`
- **Description**: Job queue backend for translation jobs
- **Start Method**: `docker-compose up redis`
- **Ports**: 6379
- **Dependencies**: None
- **Config Knobs**: REDIS_PORT

### Translation Workers

#### CPU Translation Worker
- **ID**: `worker-cpu`
- **Description**: CPU-based translation worker for processing translation jobs
- **Start Method**: `docker-compose up worker-cpu`
- **Ports**: None
- **Dependencies**: orchestrator, redis, config
- **Config Knobs**: WORKER_ID, WORKER_MODE, DEVICE, REDIS_HOST, REDIS_PORT, REDIS_DB, POLL_INTERVAL, MAX_RETRIES

#### GPU Translation Worker
- **ID**: `worker-gpu`
- **Description**: GPU-based translation worker for processing translation jobs
- **Start Method**: `docker-compose up worker-gpu`
- **Ports**: None
- **Dependencies**: orchestrator, redis, config
- **Config Knobs**: WORKER_ID, WORKER_MODE, DEVICE, CUDA_VISIBLE_DEVICES, REDIS_HOST, REDIS_PORT, REDIS_DB, POLL_INTERVAL, MAX_RETRIES

### Monitoring and Observability

#### Prometheus
- **ID**: `prometheus`
- **Description**: Metrics collection and alerting server
- **Start Method**: `docker-compose up prometheus`
- **Ports**: 9190
- **Dependencies**: None
- **Config Knobs**: prometheus.yml, alert_rules.yml

#### Pushgateway
- **ID**: `pushgateway`
- **Description**: Metrics push gateway for batch job metrics
- **Start Method**: `docker-compose up pushgateway`
- **Ports**: 9191
- **Dependencies**: None
- **Config Knobs**: None

#### Grafana
- **ID**: `grafana`
- **Description**: Metrics visualization dashboard
- **Start Method**: `docker-compose up grafana`
- **Ports**: 3100
- **Dependencies**: prometheus
- **Config Knobs**: GF_SECURITY_ADMIN_PASSWORD, GF_USERS_ALLOW_SIGN_UP, GF_PATHS_PROVISIONING

### CLI Tools

#### CLI Translation Tool
- **ID**: `cli`
- **Description**: Command-line interface for translating Hugo sites
- **Start Method**: `translate-hugo --site <site_id> --input <path> --target-langs <lang1> <lang2>`
- **Ports**: None
- **Dependencies**: config
- **Config Knobs**: --validation-mode, --disable-validation, --force-accept, --strict-reject, --validation-config, --max-retries, --model, --max-tokens, --batch-size, --sort-segments-by-length, --device, --load-mode, --verify, --fix, --verification-report, --enable-terminology, --disable-terminology, --terminology-mode, --terminology-config, --dry-run, --save-rejected, --output, --log-level, --log-file, --metrics-file, --metrics-interval, --metrics-only, --no-progress, --resume, --no-resume, --force-restart, --progress-dir, --force-retranslate, --cache-write-mode, --disable-content-hash, --rebuild-content-hashes, --validate-output-integrity, --parallel-languages, --global-lang-rounds, --global-lang-sort, --fail-fast, --no-fail-fast, --enable-production-metrics, --config-root, --auto-commit, --no-commit, --commit-message

### Python Modules

#### Translation Worker Module
- **ID**: `translation-worker`
- **Description**: Translation worker module for distributed processing
- **Start Method**: `python -m src.workers.translation_worker`
- **Ports**: None
- **Dependencies**: config, tm
- **Config Knobs**: CONFIG_PATH, SITE_PROFILES_DIR, TM_PATH, WORKER_ID

#### Job Processor
- **ID**: `job-processor`
- **Description**: Job processor for translation jobs
- **Start Method**: `python -m src.workers.job_processor`
- **Ports**: None
- **Dependencies**: config, tm
- **Config Knobs**: None

#### Model Recommender
- **ID**: `model-recommender`
- **Description**: Model recommendation tool
- **Start Method**: `python -m src.model_runtime.recommender`
- **Ports**: None
- **Dependencies**: config
- **Config Knobs**: None

#### CT2 Converter
- **ID**: `ct2-converter`
- **Description**: CT2 model conversion tool
- **Start Method**: `python -m src.model_runtime.ct2_converter`
- **Ports**: None
- **Dependencies**: config
- **Config Knobs**: None

#### Benchmarking CLI
- **ID**: `benchmarking-cli`
- **Description**: Benchmarking command-line tools
- **Start Method**: `python -m src.benchmarking.cli`
- **Ports**: None
- **Dependencies**: config
- **Config Knobs**: None

#### System Info
- **ID**: `system-info`
- **Description**: System information tool
- **Start Method**: `python -m src.benchmarking.system_info`
- **Ports**: None
- **Dependencies**: config
- **Config Knobs**: None

#### Benchmarking Runner
- **ID**: `benchmarking-runner`
- **Description**: Benchmarking runner tool
- **Start Method**: `python -m src.benchmarking.runner`
- **Ports**: None
- **Dependencies**: config
- **Config Knobs**: None

#### GPU Manager
- **ID**: `gpu-manager`
- **Description**: GPU management tool
- **Start Method**: `python -m src.hardware.gpu_manager`
- **Ports**: None
- **Dependencies**: config
- **Config Knobs**: None

#### Metrics Tail
- **ID**: `metrics-tail`
- **Description**: Metrics tail utility
- **Start Method**: `python -m src.observability.metrics_tail`
- **Ports**: None
- **Dependencies**: config
- **Config Knobs**: None

#### Graceful Shutdown
- **ID**: `graceful-shutdown`
- **Description**: Graceful shutdown example
- **Start Method**: `python -m src.observability.graceful_shutdown`
- **Ports**: None
- **Dependencies**: config
- **Config Knobs**: None
