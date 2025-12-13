# Rollback Procedure

## Overview

This document provides comprehensive procedures for rolling back failed deployments of the Hugo Translation System. Rollbacks are critical safety mechanisms that restore the system to a known working state when deployments fail or introduce critical issues.

**Purpose:** Restore system to previous working state safely and quickly
**Audience:** Operations team, DevOps engineers, Site reliability engineers
**Maintenance:** Review and update after each major deployment

---

## Table of Contents

1. [When to Rollback](#when-to-rollback)
2. [Rollback Decision Tree](#rollback-decision-tree)
3. [Pre-Rollback Checklist](#pre-rollback-checklist)
4. [Rollback Procedures](#rollback-procedures)
5. [Rollback Verification](#rollback-verification)
6. [Communication Template](#communication-template)
7. [Post-Rollback Analysis](#post-rollback-analysis)
8. [Automation](#automation)

---

## When to Rollback

### Critical Issues (Immediate Rollback Required)

Rollback immediately if any of these occur:

- **System Downtime:** Service is completely unavailable
- **Data Corruption:** Translation memory or configuration data is corrupted
- **Critical Bug:** Severe functional regression affecting core features
- **Security Issue:** Deployment introduces security vulnerability
- **Performance Degradation:** >50% performance drop affecting users
- **Cascading Failures:** Deployment causes failures in dependent systems

**Timeline:** Rollback decision within 15 minutes, execution within 30 minutes

### Serious Issues (Rollback Recommended)

Consider rollback for:

- **Partial Functionality Loss:** Some features broken but system operational
- **Quality Degradation:** Translation quality significantly worse
- **Memory Leaks:** Gradual performance degradation over time
- **Integration Failures:** External service integrations broken
- **Moderate Performance Issues:** 20-50% performance degradation

**Timeline:** Assess within 1 hour, decide within 2 hours

### Minor Issues (Fix Forward Preferred)

Fix forward instead of rollback:

- **UI Glitches:** Cosmetic issues not affecting functionality
- **Minor Performance Issues:** <20% performance change
- **Documentation Issues:** Incorrect or missing documentation
- **Logging Problems:** Logging format changes or missing logs
- **Non-Critical Warnings:** Warning messages that don't affect operation

**Timeline:** Plan fix within 24 hours

---

## Rollback Decision Tree

```
Deployment Completed
        |
        v
Is system functioning?
        |
        +-- NO --> CRITICAL ISSUE --> Rollback immediately
        |
        +-- YES --> Any critical bugs?
                    |
                    +-- YES --> SERIOUS ISSUE --> Assess severity
                    |                              |
                    |                              +-- High --> Rollback
                    |                              +-- Medium --> Fix forward vs rollback
                    |
                    +-- NO --> Performance OK?
                               |
                               +-- NO --> Degradation >50%? --> YES --> Rollback
                               |                            --> NO  --> Fix forward
                               |
                               +-- YES --> Monitor and fix forward
```

### Decision Criteria

**Rollback if:**
- Impact affects >50% of users
- No quick fix available (<2 hours)
- Issue severity: Critical or High
- Data integrity at risk
- Security vulnerability present

**Fix forward if:**
- Impact limited to <10% of users
- Quick fix available and tested
- Issue severity: Low or Medium
- Rollback more risky than fix
- Issue doesn't affect core functionality

---

## Pre-Rollback Checklist

Before initiating rollback, complete this checklist:

### 1. Verification
- [ ] Confirm issue is caused by recent deployment
- [ ] Verify previous version is available
- [ ] Check previous version was stable
- [ ] Identify exact commit/tag to rollback to
- [ ] Verify backup exists and is recent

### 2. Impact Assessment
- [ ] Document current issue symptoms
- [ ] Assess user impact (number of users, severity)
- [ ] Identify affected components
- [ ] Check for data changes since deployment
- [ ] Estimate rollback time and impact

### 3. Communication
- [ ] Notify stakeholders of impending rollback
- [ ] Inform users if necessary (downtime expected)
- [ ] Assign rollback coordinator
- [ ] Establish communication channel (Slack, etc.)

### 4. Preparation
- [ ] Review rollback procedure
- [ ] Gather necessary credentials/access
- [ ] Prepare rollback command
- [ ] Ready monitoring tools
- [ ] Identify rollback verification tests

### 5. Approval
- [ ] Technical lead approval obtained
- [ ] Operations manager approval (if required)
- [ ] Document approval in ticket/incident

---

## Rollback Procedures

### Automated Rollback (Recommended)

#### Quick Rollback (Last Deployment)

```bash
# 1. Navigate to project root
cd /path/to/hugo-translator

# 2. Run automated rollback to previous version
python scripts/rollback.py --to-previous

# 3. Verify rollback
python scripts/run_smoke_tests.py --quick
```

#### Targeted Rollback (Specific Commit)

```bash
# 1. Identify target commit
git log --oneline -10

# 2. Dry-run to preview changes
python scripts/rollback.py --dry-run --to-commit abc123

# 3. Review dry-run output carefully

# 4. Execute rollback
python scripts/rollback.py --to-commit abc123

# 5. Verify rollback
python scripts/run_smoke_tests.py --full
python scripts/validate_production_readiness.py --strict
```

#### Tagged Version Rollback

```bash
# 1. List available tags
git tag -l

# 2. Dry-run rollback to tag
python scripts/rollback.py --dry-run --to-tag v1.2.0

# 3. Execute rollback
python scripts/rollback.py --to-tag v1.2.0

# 4. Verify
python scripts/run_smoke_tests.py --full
```

### Manual Rollback (If Automation Fails)

#### Step 1: Create Backup

```bash
# Backup current state before rollback
timestamp=$(date +%Y%m%d_%H%M%S)
backup_dir="backups/pre_rollback_$timestamp"

mkdir -p "$backup_dir"
cp -r config/ "$backup_dir/"
cp -r data/tm/ "$backup_dir/tm/"
git rev-parse HEAD > "$backup_dir/commit.txt"
```

#### Step 2: Stop Services

```bash
# Stop all running services
# (Adjust based on your deployment)

# If using systemd:
sudo systemctl stop hugo-translator

# If using Docker:
docker-compose down

# If running directly:
pkill -f "python.*translation"
```

#### Step 3: Rollback Code

```bash
# Get target commit hash
TARGET_COMMIT="abc123"  # Replace with actual commit

# Create rollback branch
git checkout -b rollback-$timestamp

# Reset to target commit
git reset --hard $TARGET_COMMIT

# Or checkout specific tag
git checkout tags/v1.2.0
```

#### Step 4: Rollback Configuration

```bash
# If config changed in failed deployment
cd config/

# Restore from backup if needed
cp -r ../backups/config_backup_YYYYMMDD/* .

# Or revert specific config files
git checkout $TARGET_COMMIT -- config/model_registry.yaml
```

#### Step 5: Rollback Translation Memory (If Needed)

**CAUTION:** Only rollback TM if corrupted by deployment

```bash
# Stop all TM access first

# Restore L2 (LMDB) from backup
cd data/tm/
cp -r ../../backups/tm_backup_YYYYMMDD/l2/ ./l2/

# Restore L3 (FAISS index) from backup
cp -r ../../backups/tm_backup_YYYYMMDD/l3/ ./l3/

# Verify backup integrity
python scripts/verify_tm_backup.py --backup backups/tm_backup_YYYYMMDD
```

#### Step 6: Reinstall Dependencies

```bash
# Reinstall dependencies (if requirements changed)
pip install -r requirements/production.txt

# Or restore full environment
conda env update -f environment.yml
```

#### Step 7: Restart Services

```bash
# Restart services

# If using systemd:
sudo systemctl start hugo-translator
sudo systemctl status hugo-translator

# If using Docker:
docker-compose up -d

# If running directly:
python src/main.py --config config/production.yaml &
```

---

## Rollback Verification

After rollback, verify system is working correctly:

### 1. Smoke Tests (Required)

```bash
# Run quick smoke tests
python scripts/run_smoke_tests.py --quick

# Expected: All tests pass in <30 seconds
# If failed: Check logs, may need further rollback
```

### 2. Production Readiness (Required)

```bash
# Validate production readiness
python scripts/validate_production_readiness.py --strict

# Expected: All checks pass
# If failed: Address failing checks before proceeding
```

### 3. Functional Tests (Required)

```bash
# Test critical functionality
python tests/live_translation_simple.py

# Expected: Translation works correctly
# If failed: Verify correct version was rolled back to
```

### 4. Performance Check (Recommended)

```bash
# Run performance benchmark
python scripts/benchmark_production.py --quick

# Expected: Performance within acceptable range
# Compare to baseline from before failed deployment
```

### 5. Integration Tests (Recommended)

```bash
# Test integrations
pytest tests/integration/ -v -m smoke

# Expected: Integration tests pass
# If failed: Check external service dependencies
```

### 6. Manual Verification (Required)

- [ ] Check service is accessible
- [ ] Verify UI loads correctly (if applicable)
- [ ] Test sample translation end-to-end
- [ ] Check logs for errors
- [ ] Verify metrics are being collected
- [ ] Test TM lookup is working
- [ ] Verify configuration is correct

### 7. Monitor for 1 Hour

After rollback, monitor for at least 1 hour:

- [ ] CPU/Memory usage normal
- [ ] No error spikes in logs
- [ ] Translation quality acceptable
- [ ] Response times normal
- [ ] No user complaints
- [ ] All services healthy

---

## Communication Template

### Pre-Rollback Notification

```
Subject: [ACTION REQUIRED] Deployment Rollback - Hugo Translation System

Team,

We are initiating a rollback of the Hugo Translation System deployment due to [ISSUE].

Issue: [Brief description]
Severity: [Critical/High/Medium]
User Impact: [Description of impact]
Rollback Target: [Commit/Tag to rollback to]
Estimated Duration: [Time estimate]
Expected Downtime: [Yes/No - if yes, duration]

Timeline:
- Rollback Start: [Time]
- Expected Completion: [Time]
- Verification Complete: [Time]

Actions Required:
- [Any actions team members need to take]

Communication Channel: [Slack channel / incident room]

Rollback Coordinator: [Name]

Updates will be provided every 15 minutes.

[Your Name]
```

### Rollback In Progress Update

```
Subject: [UPDATE] Deployment Rollback In Progress

Update #[N] - [Timestamp]

Status: Rollback in progress
Current Step: [Current step]
Progress: [X]% complete

Activities Completed:
- [Completed activities]

Next Steps:
- [Upcoming activities]

Issues Encountered: [None / Description]

Next Update: [Time]

[Your Name]
```

### Rollback Completion Notification

```
Subject: [RESOLVED] Deployment Rollback Complete

Team,

The rollback of the Hugo Translation System has been completed successfully.

Summary:
- Rolled back from: [Failed commit/version]
- Rolled back to: [Target commit/version]
- Rollback Duration: [Time taken]
- Downtime: [Actual downtime]

Verification:
✅ Smoke tests: Passed
✅ Production readiness: Passed
✅ Functional tests: Passed
✅ Performance: Within acceptable range
✅ Manual verification: Complete

Current Status: System is stable and operational

Root Cause Analysis:
- Initial findings: [Brief description]
- Full RCA: Will be completed within 24 hours

Next Steps:
1. Continue monitoring for 24 hours
2. Complete root cause analysis
3. Plan fix for original issue
4. Schedule re-deployment with fix

Thank you for your patience.

[Your Name]
```

---

## Post-Rollback Analysis

### Immediate Actions (Within 2 hours)

1. **Document Timeline**
   - When issue was detected
   - When rollback decision was made
   - Rollback start time
   - Rollback completion time
   - Total downtime (if any)

2. **Capture Evidence**
   - Screenshots of errors
   - Log snippets showing issue
   - Metrics/graphs showing problem
   - User reports or tickets
   - System state before/after

3. **Initial Assessment**
   - What went wrong
   - Why it wasn't caught in testing
   - What triggered the rollback decision

### Root Cause Analysis (Within 24 hours)

Complete RCA addressing:

1. **Timeline of Events**
   - Pre-deployment state
   - Deployment execution
   - Issue manifestation
   - Detection and response
   - Rollback execution

2. **Root Cause**
   - Technical cause of failure
   - Process gaps that allowed it
   - Testing gaps
   - Review gaps

3. **Contributing Factors**
   - Environmental differences
   - Dependencies
   - Timing issues
   - Configuration issues

4. **Impact Analysis**
   - Users affected
   - Duration of impact
   - Data impact
   - Business impact

### Preventive Measures (Within 1 week)

1. **Immediate Fixes**
   - Code fix for root cause
   - Additional tests to catch issue
   - Documentation updates

2. **Process Improvements**
   - Update deployment checklist
   - Enhance testing procedures
   - Improve monitoring/alerting
   - Update rollback procedures

3. **Validation**
   - Test fix in staging
   - Run enhanced test suite
   - Conduct deployment dry-run
   - Get peer review

### Re-Deployment Planning

Before re-deploying:

- [ ] Root cause identified and fixed
- [ ] Fix tested in all environments
- [ ] Additional tests added to prevent recurrence
- [ ] Deployment checklist updated
- [ ] Team trained on any process changes
- [ ] Monitoring enhanced for specific issue
- [ ] Rollback plan updated if needed
- [ ] Stakeholders informed of re-deployment plan

---

## Automation

### Rollback Script

The automated rollback script (`scripts/rollback.py`) provides:

- **Dry-run mode:** Preview changes before execution
- **Multiple targets:** Rollback to commit, tag, or previous version
- **Automatic backup:** Creates backup before rollback
- **Verification:** Runs smoke tests after rollback
- **Safety checks:** Prevents unsafe rollbacks

### Usage Examples

```bash
# Dry-run (safe preview)
python scripts/rollback.py --dry-run --to-previous

# Rollback to previous version
python scripts/rollback.py --to-previous

# Rollback to specific commit
python scripts/rollback.py --to-commit abc123

# Rollback to tagged version
python scripts/rollback.py --to-tag v1.2.0

# Rollback with verbose output
python scripts/rollback.py --to-previous --verbose

# Skip verification (not recommended)
python scripts/rollback.py --to-previous --skip-verify
```

### Automation Best Practices

1. **Always dry-run first** in production
2. **Create backup** before rollback
3. **Run verification** after rollback
4. **Monitor closely** after automated rollback
5. **Document** all automated rollbacks
6. **Review logs** from automation
7. **Test automation** regularly in staging

---

## Appendix

### A. Rollback Safety Guidelines

- **Never** rollback during peak usage hours (unless critical)
- **Always** create backup before rollback
- **Never** skip verification steps
- **Always** communicate with stakeholders
- **Never** rollback if unsure of target version
- **Always** document the rollback
- **Never** rollback data without explicit approval
- **Always** monitor after rollback

### B. Rollback Risk Assessment

**Low Risk Rollbacks:**
- Code-only changes
- Same database schema
- No config changes
- Recent deployment (<24 hours)

**Medium Risk Rollbacks:**
- Minor config changes
- Rolling back >24 hours
- Dependencies changed
- Database migrations (reversible)

**High Risk Rollbacks:**
- Major config changes
- Rolling back >1 week
- Database migrations (irreversible)
- Data format changes
- Integration contract changes

### C. Emergency Contacts

**Escalation Path:**
1. On-call engineer
2. Technical lead
3. Engineering manager
4. CTO/VP Engineering

**Contact Information:**
- On-call: [Contact method]
- Tech Lead: [Contact method]
- Manager: [Contact method]

### D. Related Documents

- [Deployment Checklist](DEPLOYMENT_SAFETY_CHECKLIST.md)
- [Production Readiness Guide](../PRODUCTION_READY.md)
- [Backup and Restore Procedures](../scripts/backup_tm.py)
- [Incident Response Plan](INCIDENT_RESPONSE.md) (if exists)

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2025-12-11 | System | Initial rollback procedure |

---

**Document Maintenance:**
- Review quarterly or after each rollback
- Update based on lessons learned
- Keep in sync with deployment procedures
- Validate automation still works

**Last Review:** 2025-12-11
**Next Review:** 2026-03-11
