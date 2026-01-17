# Configuration

## Overview

The Hugo Translation System uses a hierarchical configuration approach with multiple configuration files and environment variables. This document describes the configuration structure and key configuration options.

## Configuration Files

### Global Configuration
- **File**: `config/global.yaml`
- **Description**: Main configuration file containing global settings
- **Key Sections**:
  - `observability`: Logging and metrics configuration
  - `hardware`: Hardware-specific settings
  - `benchmarking`: Benchmarking configuration
  - `translation`: Default translation settings

### Site Profiles
- **Directory**: `config/site_profiles/`
- **Description**: Site-specific configuration files
- **Files**:
  - `about.aspose.net.yaml`
  - `blog.aspose.net.yaml`
  - `docs.aspose.net.yaml`
  - `kb.aspose.net.yaml`
  - `products.aspose.net.yaml`
  - `reference.aspose.net.yaml`
  - `websites.aspose.net.yaml`
  - `www.aspose.net.yaml`
  - `default.yaml`
  - `example.yaml`

### Model Registry
- **File**: `config/model_registry.yaml`
- **Description**: Registry of available translation models
- **Key Information**:
  - Model IDs
  - Model paths
  - Model capabilities
  - Performance characteristics

### Validation Configuration
- **File**: `config/validation.yaml`
- **Description**: Validation rules and settings
- **Key Sections**:
  - `validators`: List of validation rules
  - `severity_levels`: Severity levels for validation issues
  - `default_mode`: Default validation mode

### Terminology Configuration
- **File**: `config/terminology.yaml`
- **Description**: Terminology preservation rules
- **Key Sections**:
  - `protected_terms`: Terms that must be preserved
  - `technical_terms`: Technical terms with specific translations
  - `terminology_mode`: Default terminology mode

### Benchmarking Configuration
- **File**: `config/benchmarking.yaml`
- **Description**: Benchmarking and performance testing configuration
- **Key Sections**:
  - `production`: Production metrics recording settings
  - `database`: Database paths for benchmarking data
  - `scheduler`: Benchmarking schedule

## Environment Variables

### Core System
- `CONFIG_PATH`: Configuration directory path (default: `./config`)
- `MODE`: Orchestrator mode (`auto` or `manual`)
- `SWEEP_INTERVAL_HOURS`: Hours between automatic content sweeps
- `LOG_LEVEL`: Logging level

### Redis
- `REDIS_HOST`: Redis host (default: `localhost`)
- `REDIS_PORT`: Redis port (default: `6379`)
- `REDIS_DB`: Redis database (default: `0`)
- `REDIS_PASSWORD`: Redis password

### Workers
- `WORKER_ID`: Worker identifier
- `WORKER_MODE`: Worker mode (`processor`)
- `DEVICE`: Device for model inference (`cpu`, `cuda`)
- `CUDA_VISIBLE_DEVICES`: CUDA devices to use
- `POLL_INTERVAL`: Polling interval for job queue
- `MAX_RETRIES`: Maximum retry attempts

### Monitoring
- `GF_SECURITY_ADMIN_PASSWORD`: Grafana admin password
- `GF_USERS_ALLOW_SIGN_UP`: Allow user sign-up in Grafana
- `GF_PATHS_PROVISIONING`: Grafana provisioning path

## Configuration Overrides

The system supports configuration overrides through:

1. **Environment Variables**: Override configuration settings via environment variables
2. **CLI Flags**: Command-line flags override configuration file settings
3. **Site Profiles**: Site-specific profiles override global settings

## Configuration Loading

The `ConfigService` class handles configuration loading and merging:

```python
from src.utils.config_loader import ConfigService

config_service = ConfigService(config_root="config")
global_config = config_service.global_config
site_profile = config_service.get_site_profile("products.aspose.net")
```

## Configuration Validation

Configuration files are validated using JSON schemas:

- `config/schemas/language.schema.json`: Language configuration schema
- `config/schemas/site_profile.schema.json`: Site profile schema

## Best Practices

1. **Use Environment Variables**: For sensitive or environment-specific settings
2. **Site-Specific Profiles**: Create site-specific profiles for different sites
3. **Validation**: Always validate configuration before starting services
4. **Documentation**: Document configuration changes and their impact
