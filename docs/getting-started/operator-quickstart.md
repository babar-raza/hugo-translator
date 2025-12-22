# Operator Quickstart

Applies to SRE/Ops running the system in production-like environments.

## Prerequisites
- Access to `config/` and content directories.
- TM storage paths provisioned (see [Config Reference](../reference/config.md) for `tm_data_dir` and index locations).
- Monitoring stack reachable if enabled (Prometheus/Grafana).

## Steps
1) Review global settings in `config/global.yaml` (or overridden config root).
2) Ensure validation/terminology configs exist: `config/validation.yaml`, `config/terminology.yaml`.
3) Run the CLI or orchestrator with explicit config root:
   ```bash
   translate-hugo --site <site-id> --config-root ./config --log-level INFO
   ```
4) Verify outputs land under the expected target-language folders (see [File Contracts](../reference/file-contracts.md)).
5) Check observability:
   - Telemetry: enable via `HUGO_TRANSLATOR_TELEMETRY_ENABLED` and confirm TEL-03 connectivity (src/observability/telemetry_integration.py).
   - Metrics: scrape/push as configured in `config/global.yaml` or collector defaults (src/observability/metrics.py).

## Next Steps
- Deployment flow: [Deployment](../operations/deployment.md)
- Troubleshooting: [Troubleshooting](../operations/troubleshooting.md)
- Telemetry/Metrics: [Telemetry](../operations/telemetry.md), [Metrics](../operations/metrics.md)
