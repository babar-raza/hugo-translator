# Configuration Directory

Production configuration, validation schemas, and site-specific profiles are all tracked here. Keeping them alongside code guarantees that a commit contains both the implementation and the knobs that affect it.

## Layout

| Item | Description | Operational impact |
| --- | --- | --- |
| `global.yaml` | Master configuration toggles (paths, feature flags, resource sizing). | Defines the shape of every deployment; CI enforces that this file stays in sync with runtime defaults. |
| `model_registry.yaml` | Supported translation models plus metadata (size, hardware requirements). | Drives the automatic model-selection logic so workers only load vetted checkpoints. |
| `claims.yaml` | Statements of capability used in verification reports. | Provides traceability when auditors ask which claims were validated in each release. |
| `quality_gates.yaml` | Definitions for release gates and pass/fail criteria. | Ensures the promotion pipeline blocks builds that miss contractual requirements. |
| `terminology.yaml` | Domain-specific glossary overrides. | Keeps translations on-brand and consistent for every customer. |
| `validation.yaml` | Cross-check rules for configs and input data. | Controls the validators that prevent operators from shipping risky changes. |
| `site_profiles/` | One YAML per Hugo site (credentials, paths, TM overrides). | Allows multi-tenant deployments without recompiling or editing source code. |
| `schemas/` | JSON/YAML schemas that back validation tooling. | Lets tooling (and CI) guarantee every config change respects the contract before merge. |

Never edit generated credentials or secrets directly in this folder—use the provided templates (`.env.example`, `.env.production`) at the repository root.
