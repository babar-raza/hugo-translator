# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

If you discover a security vulnerability in the Hugo Translation System, please report it responsibly.

### How to Report

1. **Do not** open a public issue for security vulnerabilities.
2. Email the maintainers at the address listed in the repository contacts, or use GitLab's confidential issue feature.
3. Include:
   - A description of the vulnerability
   - Steps to reproduce the issue
   - The potential impact
   - Any suggested fixes (optional)

### What to Expect

- **Acknowledgement**: Within 48 hours of your report.
- **Assessment**: We will evaluate the severity and impact within 5 business days.
- **Resolution**: Critical vulnerabilities will be patched within 14 days. Lower-severity issues will be addressed in the next release cycle.
- **Disclosure**: We will coordinate disclosure timing with you. We follow a 90-day disclosure window.

## Security Practices

### Secrets Management

- All secrets (API keys, credentials) are stored in environment variables, never in source code.
- `.env` files are gitignored. Only `.env.example` (with placeholder values) is committed.
- Pre-commit hooks detect and block hardcoded personal paths and credential patterns.

### Dependency Security

- Dependencies are scanned with `pip-audit` and `bandit` in CI (see `.gitlab-ci.yml`).
- HIGH severity findings in `bandit` block the release gate.
- Dependency updates are tracked via Dependabot/Renovate configuration.

### CI/CD Security

- CI pipelines run in isolated environments with no access to production credentials.
- Security scan results are published as job artifacts for review.
- The release gate requires all quality and security checks to pass before merge.

### Data Handling

- The system processes Hugo markdown content only. No PII is collected or stored.
- Translation Memory (TM) databases are local-only and gitignored.
- Agent metrics reporting is disabled by default (`enabled: false`, `dry_run: true`).
- When enabled, metrics contain only aggregate counts (word counts, file counts), not content.

### Runtime Safety

- Workers run with least-privilege (no admin/root required).
- File writes use atomic operations to prevent partial/corrupt output.
- GPU memory is explicitly released between worker runs to prevent resource exhaustion.
- PID file locking prevents concurrent worker instances.
