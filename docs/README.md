# Hugo Translation System - Documentation

**Version:** 1.0.0
**Last Updated:** 2025-11-21

---

## Documentation Overview

This directory contains comprehensive production documentation for the Hugo Translation System. The documentation is organized into five main guides, each serving a specific purpose.

## Directory Layout

| Subfolder | Description | Impact on operations |
| --- | --- | --- |
| `api/` | Worker/MCP API references and payload examples. | Keeps integration partners in sync with the transport contract so tool changes do not break clients. |
| `phase-0/`, `phase-1/`, `phase-2/` | Phase-specific design notes captured during the early roadmap. | Preserve the architectural intent from each phase so new contributors understand why guardrails exist. |
| `runbooks/` | Operational runbooks (backup, rollback, health checks). | Fuel day-2 reliability work by giving on-call engineers curated procedures. |
| `validators/` | Validator specifications and acceptance criteria. | Document the release gates enforced by CI, preventing unverified claims from shipping. |
| `supplemental/` | Quick references such as telemetry integrations, resume guides, and TRM tips. | Provide lightweight context for emergency debugging without digging through long-form guides. |

---

## Quick Navigation

### For New Users

1. Start with [USER_GUIDE.md](USER_GUIDE.md) - Learn how to use the system
2. Review [CONFIGURATION.md](CONFIGURATION.md) - Understand configuration options
3. Follow [DEPLOYMENT.md](DEPLOYMENT.md) - Deploy the system

### For Operators

1. Review [OPERATIONS.md](OPERATIONS.md) - Daily operations and maintenance
2. Keep [TROUBLESHOOTING.md](TROUBLESHOOTING.md) handy - Problem resolution

### For Developers

1. Review source code in `src/` - Well-documented Python modules
2. Check `tests/` for test examples and patterns
3. See `config/` for configuration schema and examples

---

## Document Summaries

### 1. USER_GUIDE.md

**Purpose:** Complete user guide for translating Hugo content

**Contents:**
- Installation and setup (Docker and local)
- Configuration (site profiles, models, TM)
- Basic usage (single file, directory translation)
- Advanced features (parallel processing, semantic TM)
- Translation Memory management
- Best practices and troubleshooting

**Target Audience:** End users, content managers, developers

**Key Sections:**
- [Installation](#installation-and-setup) - Get started quickly
- [Basic Usage](#basic-usage) - Translate your first file
- [Advanced Features](#advanced-features) - Optimize performance
- [TM Management](#translation-memory-management) - Maximize efficiency

---

### 2. DEPLOYMENT.md

**Purpose:** Production deployment guide

**Contents:**
- System requirements (hardware, software)
- Pre-deployment checklist
- Docker deployment steps
- Environment configuration
- Starting/stopping services
- Health checks and verification
- Scaling considerations
- Security hardening
- Monitoring setup
- Rollback procedures

**Target Audience:** DevOps engineers, system administrators

**Key Sections:**
- [System Requirements](#system-requirements) - Ensure compatibility
- [Docker Deployment](#docker-deployment) - Step-by-step deployment
- [Health Checks](#health-checks-and-verification) - Verify installation
- [Scaling](#scaling-considerations) - Handle growing workloads

---

### 3. CONFIGURATION.md

**Purpose:** Complete configuration reference

**Contents:**
- Global configuration schema (`config/global.yaml`)
- Site profile schema and examples (`config/site_profiles/*.yaml`)
- Model registry configuration (`config/model_registry.yaml`)
- Environment variables reference
- Translation Memory configuration options
- Frontmatter mode reference
- Configuration examples for different use cases
- Validation and best practices

**Target Audience:** System administrators, advanced users

**Key Sections:**
- [Global Configuration](#global-configuration) - System-wide settings
- [Site Profiles](#site-profiles) - Per-site translation rules
- [Model Registry](#model-registry) - Available models
- [Environment Variables](#environment-variables) - Runtime configuration

---

### 4. OPERATIONS.md

**Purpose:** Daily operations and maintenance manual

**Contents:**
- Daily operations (health checks, metrics review)
- Health monitoring procedures
- Maintenance tasks (weekly, monthly, quarterly)
- Backup and restore procedures
- Common operational tasks
- Emergency procedures
- Performance tuning
- Capacity planning

**Target Audience:** Operations teams, site reliability engineers

**Key Sections:**
- [Daily Operations](#daily-operations) - Routine checks
- [Maintenance Tasks](#maintenance-tasks) - Keep system healthy
- [Backup and Restore](#backup-and-restore) - Protect your data
- [Emergency Procedures](#emergency-procedures) - Handle incidents

---

### 5. TROUBLESHOOTING.md

**Purpose:** Problem identification and resolution guide

**Contents:**
- Common issues and solutions
- Error messages reference
- Performance problems
- Docker issues
- Model loading issues
- Translation Memory issues
- Configuration issues
- Debugging techniques
- Getting help

**Target Audience:** All users, support teams

**Key Sections:**
- [Common Issues](#common-issues-and-solutions) - Quick fixes
- [Error Messages](#error-messages-reference) - Understand errors
- [Performance Problems](#performance-problems) - Optimize speed
- [Debugging Techniques](#debugging-techniques) - Deep diagnostics

---

## Documentation Usage Guide

### Getting Started Workflow

**For first-time users:**

```
1. Read USER_GUIDE.md (Introduction, Installation)
   ↓
2. Follow DEPLOYMENT.md (Deploy system)
   ↓
3. Configure using CONFIGURATION.md (Set up site profiles)
   ↓
4. Test translation using USER_GUIDE.md (Basic Usage)
   ↓
5. Review OPERATIONS.md (Understand maintenance)
```

**For troubleshooting:**

```
1. Identify problem symptoms
   ↓
2. Search TROUBLESHOOTING.md for issue
   ↓
3. Apply suggested solutions
   ↓
4. If unresolved, enable debug logging (TROUBLESHOOTING.md)
   ↓
5. Gather diagnostics and seek help
```

**For optimization:**

```
1. Review current performance (OPERATIONS.md)
   ↓
2. Identify bottlenecks
   ↓
3. Check CONFIGURATION.md for tuning options
   ↓
4. Apply changes incrementally
   ↓
5. Monitor results (OPERATIONS.md)
```

---

## Quick Reference

### Essential Commands

```bash
# Start system
docker-compose up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f orchestrator

# Health check
docker-compose exec orchestrator python -c "from src.utils.config_loader import ConfigService; print('OK')"

# Backup
./scripts/backup.sh

# Stop system
docker-compose down
```

### Essential Files

| File | Purpose | Location |
|------|---------|----------|
| Global config | System settings | `config/global.yaml` |
| Site profile | Site translation rules | `config/site_profiles/<site>.yaml` |
| Model registry | Available models | `config/model_registry.yaml` |
| Environment | Runtime config | `.env.production` |
| Docker compose | Container orchestration | `docker-compose.yml` |

### Essential Paths

| Path | Contains | Purpose |
|------|----------|---------|
| `/data/tm` | Translation Memory | Persistent storage |
| `/data/models` | Model cache | Downloaded models |
| `/data/artifacts` | Flow artifacts | Debug information |
| `/data/logs` | System logs | Troubleshooting |
| `/backups` | Backups | Disaster recovery |

---

## Additional Resources

### Code Documentation

- Source Code - Well-documented Python modules in `src/`
- Configuration schemas in `config/schemas/`
- Test examples in `tests/`

### API Reference

API documentation can be generated from docstrings:
```bash
pip install sphinx sphinx-autodoc-typehints
sphinx-build -b html docs/ docs/_build/
```

---

## Documentation Standards

This documentation follows these standards:

1. **Practical and Actionable**
   - Every section includes executable examples
   - Commands are copy-paste ready
   - Examples use realistic scenarios

2. **Production-Ready**
   - Covers real-world operations
   - Includes error handling
   - Provides emergency procedures

3. **Comprehensive**
   - Installation to operation to troubleshooting
   - Multiple deployment scenarios
   - Various use cases covered

4. **Well-Organized**
   - Logical flow within documents
   - Cross-references between documents
   - Table of contents for navigation

5. **Maintained**
   - Version numbers on all documents
   - Last updated dates
   - Clear ownership

---

## Contributing to Documentation

### Reporting Issues

If you find issues in the documentation:

1. **For errors or inaccuracies:**
   - Note document name and section
   - Describe what's incorrect
   - Suggest correction if possible

2. **For missing content:**
   - Identify gap
   - Explain use case
   - Suggest where it should be added

3. **For unclear sections:**
   - Point out confusing part
   - Explain what's unclear
   - Suggest clarification

### Updating Documentation

When updating documentation:

1. **Maintain consistency:**
   - Use same terminology
   - Follow same formatting
   - Keep same structure

2. **Test examples:**
   - Verify all commands work
   - Test all code snippets
   - Validate all configurations

3. **Update metadata:**
   - Increment version if significant changes
   - Update "Last Updated" date
   - Note changes in commit message

4. **Cross-reference:**
   - Update related documents
   - Fix broken links
   - Add new cross-references

---

## Documentation Versions

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2025-11-21 | Initial production documentation |

---

## Contact and Support

### Documentation Questions

For questions about this documentation:
- Check [TROUBLESHOOTING.md](TROUBLESHOOTING.md) first
- Review related sections in other guides
- Gather diagnostic information (see TROUBLESHOOTING.md)

### System Support

For system issues:
- Follow [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
- Check logs and metrics
- Gather diagnostics before contacting support

---

## License

This documentation is part of the Hugo Translation System.
[Specify license information]

---

## Acknowledgments

Based on:
- Living Architecture Plan v0.2
- Implementation Verification Report
- Production Readiness Plan
- Actual system implementation

---

**End of Documentation Overview**

For detailed information, see the individual guide documents listed above.
