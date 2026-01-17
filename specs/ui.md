# User Interface

## Overview

The Hugo Translation System primarily provides a command-line interface (CLI) and API-based interactions. This document describes the available user interfaces and interaction patterns.

## Command-Line Interface (CLI)

### Main CLI

- **Command**: `translate-hugo`
- **Description**: Main CLI for translating Hugo sites
- **Evidence**: [`evidence-001`](specs/_evidence_index.yml:evidence-001), [`evidence-008`](specs/_evidence_index.yml:evidence-008)
- **Features**:
  - Site translation
  - File translation
  - Directory translation
  - Validation control
  - Terminology control
  - Progress tracking
  - Resume capabilities

### Usage Examples

```bash
# Translate a site
translate-hugo --site products.aspose.net --target-langs fr de

# Translate a single file
translate-hugo --site products.aspose.net --input content/en/docs.md --target-langs fr

# Translate with strict validation
translate-hugo --site products.aspose.net --validation-mode strict

# Disable validation for quick testing
translate-hugo --site products.aspose.net --disable-validation

# Dry run (preview without writing files)
translate-hugo --site products.aspose.net --dry-run
```

## API Interfaces

### MCP Server

- **Description**: MCP (Machine Communication Protocol) server for distributed translation
- **Evidence**: [`src/workers/translation_worker.py`](src/workers/translation_worker.py)
- **Tools**:
  - `translate_hugo_file`: Translate a single file
  - `translate_directory`: Translate a directory
  - `tm_exact_lookup`: Lookup exact translation
  - `tm_semantic_lookup`: Semantic translation search
  - `health_check`: Worker health check
  - `get_stats`: Worker statistics

### REST API

- **Description**: REST API for translation operations
- **Evidence**: [`src/orchestrator/orchestrator.py`](src/orchestrator/orchestrator.py)
- **Endpoints**:
  - `POST /api/translate`: Submit translation job
  - `GET /api/status`: Get job status
  - `GET /api/health`: Health check
  - `GET /api/stats`: Statistics

## Web Dashboard

### Grafana Dashboard

- **Description**: Metrics visualization dashboard
- **Evidence**: [`evidence-007`](specs/_evidence_index.yml:evidence-007)
- **Features**:
  - Translation metrics
  - Performance monitoring
  - Error tracking
  - Historical data

### Access

- **URL**: `http://localhost:3100`
- **Credentials**: Configured via environment variables
- **Dashboards**:
  - Translation Overview
  - Performance Metrics
  - Error Tracking
  - Content Hash Tracking

## Configuration UI

### Configuration Files

- **Description**: YAML-based configuration files
- **Evidence**: [`config/global.yaml`](config/global.yaml)
- **Features**:
  - Global settings
  - Site profiles
  - Model registry
  - Validation rules
  - Terminology settings

### Environment Variables

- **Description**: Environment variable configuration
- **Evidence**: [`.env.production`](.env.production)
- **Features**:
  - Runtime configuration
  - Sensitive data management
  - Environment-specific settings

## Interaction Patterns

### CLI Workflow

1. **Configure**: Set up configuration files and environment variables
2. **Run**: Execute translation commands
3. **Monitor**: View progress and logs
4. **Review**: Check translation results
5. **Commit**: Commit changes to version control

### API Workflow

1. **Submit**: Submit translation job via API
2. **Monitor**: Track job status via API
3. **Retrieve**: Get translation results
4. **Review**: Check quality and validation results
5. **Approve**: Approve and commit translations

### Dashboard Workflow

1. **Access**: Open Grafana dashboard
2. **Monitor**: View real-time metrics
3. **Analyze**: Review historical data
4. **Alert**: Set up alerts for issues
5. **Report**: Generate reports

## Best Practices

1. **CLI Usage**: Use CLI for direct translation operations
2. **API Usage**: Use API for integration with other systems
3. **Dashboard Usage**: Use dashboard for monitoring and analysis
4. **Configuration**: Use configuration files for persistent settings
5. **Environment Variables**: Use environment variables for sensitive data
