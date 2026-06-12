# Verification Workflow

**Purpose:** Systematic verification approach to ensure all implementation claims are validated before declaring "production ready."

**Philosophy:** Verification is not a final gate—it's integrated throughout the development lifecycle. Each phase has specific checks that must pass before proceeding.

---

## Table of Contents

1. [Overview](#overview)
2. [Phase 1: Design Review](#phase-1-design-review)
3. [Phase 2: Implementation](#phase-2-implementation)
4. [Phase 3: Integration](#phase-3-integration)
5. [Phase 4: Production Readiness](#phase-4-production-readiness)
6. [Rollback Procedures](#rollback-procedures)
7. [Troubleshooting](#troubleshooting)
8. [Quick Reference](#quick-reference)

---

## Overview

### Verification Principles

1. **Verify Early, Verify Often** - Don't wait until the end to verify. Check at each phase.
2. **Automated First** - Prefer automated checks over manual reviews where possible.
3. **Evidence-Based** - Every claim must have verifiable evidence (test results, logs, metrics).
4. **Fail Fast** - If a critical check fails, stop and fix it before proceeding.
5. **Reproducible** - All verification steps must be reproducible by anyone on the team.

### Four-Phase Workflow

```
Design Review → Implementation → Integration → Production Readiness
     ↓               ↓               ↓               ↓
  Plan Valid    Code Works     System Works    Ready to Deploy
```

Each phase has:
- **Purpose**: What this phase validates
- **Checklist**: Specific items to verify
- **Automated Checks**: Scripts/commands to run
- **Manual Reviews**: Human checks required
- **Exit Criteria**: Requirements to move to next phase

---

## Phase 1: Design Review

**Purpose:** Validate design before writing code. Ensure the approach is sound and achievable.

**Owner:** Implementer + Reviewer

### Checklist

- [ ] **Requirement Clarity** - All requirements are clear and unambiguous
- [ ] **Scope Definition** - Scope is well-defined (what's in, what's out)
- [ ] **Dependencies Identified** - All dependencies are documented
- [ ] **Edge Cases Considered** - Edge cases and failure modes identified
- [ ] **API Contracts Defined** - Input/output contracts are documented
- [ ] **Test Strategy Planned** - How will this be tested?
- [ ] **Rollback Plan Exists** - How to undo changes if verification fails?

### Automated Checks

None at this phase (design is primarily manual review).

### Manual Reviews

1. **Requirement Review**
   - Read task description carefully
   - Identify ambiguities and ask questions
   - Document assumptions

2. **Design Sketch**
   - Sketch the implementation approach
   - List files to create/modify
   - Identify integration points

3. **Feasibility Check**
   - Can this be implemented with available tools?
   - Are there any blockers?
   - Estimate effort realistically

### Exit Criteria

- [ ] All checklist items marked complete
- [ ] Design approved by reviewer (if applicable)
- [ ] No critical questions remain unanswered

### Example

```bash
# 1. Document the design
cat > design_notes.md <<EOF
## Task: Add GPU detection

### Requirements
- Detect CUDA version
- Report VRAM available
- Graceful fallback to CPU

### Approach
- Create src/hardware/gpu_manager.py
- Use torch.cuda API for detection
- Add tests in tests/hardware/test_gpu_manager.py

### Edge Cases
- No GPU present → fallback to CPU
- Multiple GPUs → select best GPU
- CUDA drivers not installed → graceful error

### Test Strategy
- Unit tests with mocked torch.cuda
- Integration test on actual GPU
- Test CPU fallback path
EOF

# 2. Get design reviewed
# (Share design_notes.md with team/reviewer)
```

---

## Phase 2: Implementation

**Purpose:** Write code with continuous verification. Unit tests as you go.

**Owner:** Implementer

### Checklist

- [ ] **Files Created** - All planned files are created
- [ ] **Syntax Valid** - No syntax errors
- [ ] **Imports Work** - All imports resolve correctly
- [ ] **Unit Tests Written** - Each function has unit tests
- [ ] **Tests Pass** - All unit tests pass
- [ ] **Code Style** - Follows project conventions
- [ ] **Documentation Added** - Docstrings and comments present
- [ ] **No TODOs** - No placeholder code or TODOs left

### Automated Checks

```bash
# 1. Verify files exist
python scripts/verify_implementation.py --files-only

# 2. Check syntax
python scripts/verify_implementation.py --syntax-only

# 3. Validate imports
python scripts/verify_implementation.py --imports-only

# 4. Run unit tests
python scripts/ci/run_all_tests.py --suite unit --timeout 60

# 5. Check code style (if linter configured)
# python -m flake8 src/
# python -m pylint src/
```

### Manual Reviews

1. **Self-Review**
   - Read your own code
   - Check for obvious bugs
   - Verify error handling exists

2. **Test Coverage Check**
   - Every function has at least one test
   - Happy path tested
   - Error paths tested

3. **Documentation Review**
   - Every module has a docstring
   - Complex functions documented
   - Public APIs documented

### Exit Criteria

- [ ] All unit tests pass (0 failures)
- [ ] Code syntax is valid
- [ ] All imports work
- [ ] No placeholder code remains

### Example

```bash
# 1. Implement the feature
# (Write code in src/...)

# 2. Write unit tests
# (Write tests in tests/...)

# 3. Run checks
python scripts/verify_implementation.py
python scripts/ci/run_all_tests.py --suite unit

# 4. Fix any failures
# (Iterate until all checks pass)

# 5. Verify exit criteria
python scripts/verify_implementation.py --checklist --phase implementation
```

---

## Phase 3: Integration

**Purpose:** Verify the feature integrates correctly with the rest of the system.

**Owner:** Implementer + Reviewer

### Checklist

- [ ] **Integration Tests Written** - Tests for interactions with other components
- [ ] **Integration Tests Pass** - All integration tests pass
- [ ] **Smoke Tests Pass** - Quick end-to-end tests pass
- [ ] **No Regressions** - Existing functionality still works
- [ ] **Performance Acceptable** - No unexpected performance degradation
- [ ] **Error Handling Robust** - Errors are caught and handled gracefully
- [ ] **Observability Added** - Logging/metrics for the new feature
- [ ] **Documentation Updated** - User-facing docs updated if needed

### Automated Checks

```bash
# 1. Run integration tests
python scripts/ci/run_all_tests.py --suite integration --timeout 300

# 2. Run smoke tests
python scripts/ci/run_all_tests.py --suite smoke --timeout 60

# 3. Run all tests (regression check)
python scripts/ci/run_all_tests.py --suite all --timeout 600

# 4. Verify observability
python scripts/verify_implementation.py --check-logging
```

### Manual Reviews

1. **Integration Review**
   - Feature works with real dependencies
   - No mocking in integration tests
   - Tests realistic scenarios

2. **Performance Check**
   - Run performance benchmarks
   - Compare before/after metrics
   - Verify no slowdown

3. **Error Scenario Testing**
   - Manually trigger error conditions
   - Verify error messages are clear
   - Verify system recovers gracefully

### Exit Criteria

- [ ] All integration tests pass (0 failures)
- [ ] All smoke tests pass
- [ ] No regressions in existing tests
- [ ] Performance is acceptable

### Example

```bash
# 1. Run integration tests
python scripts/ci/run_all_tests.py --suite integration -v

# 2. Run smoke tests
python scripts/ci/run_all_tests.py --suite smoke -v

# 3. Check for regressions
python scripts/ci/run_all_tests.py --suite all

# 4. Review test results
cat reports/test_execution.json

# 5. Verify exit criteria
python scripts/verify_implementation.py --checklist --phase integration
```

---

## Phase 4: Production Readiness

**Purpose:** Final gate before declaring "production ready." Comprehensive validation.

**Owner:** Implementer + Reviewer + QA (if applicable)

### Checklist

- [ ] **All Tests Pass** - 100% of tests passing (no skipped critical tests)
- [ ] **Code Coverage Acceptable** - Meets project coverage threshold
- [ ] **Documentation Complete** - All docs updated
- [ ] **Security Review Done** - No security vulnerabilities
- [ ] **Performance Benchmarked** - Meets performance requirements
- [ ] **Monitoring Configured** - Metrics/logs are being collected
- [ ] **Rollback Tested** - Rollback procedure has been tested
- [ ] **Deployment Plan Ready** - Deployment steps documented
- [ ] **Stakeholder Approval** - (If required) Stakeholders signed off

### Automated Checks

```bash
# 1. Run complete verification suite
python scripts/verify_implementation.py --strict

# 2. Run all tests with coverage
python scripts/ci/run_all_tests.py --suite all --timeout 600 --report reports/final_test_results.json

# 3. Run quality gates
python scripts/quality/quality_gates.py --gate all

# 4. Generate verification report
python scripts/verify_implementation.py --report reports/production_readiness.json --markdown reports/production_readiness.md

# 5. Run production readiness checklist
python scripts/quality/production_readiness_check.py --strict
```

### Manual Reviews

1. **Final Code Review**
   - Full code review by peer
   - Check for code smells
   - Verify best practices followed

2. **Security Review**
   - Check for common vulnerabilities (OWASP Top 10)
   - Verify no hardcoded secrets
   - Check input validation

3. **Documentation Review**
   - User-facing docs are accurate
   - API docs are complete
   - Runbooks are up to date

4. **Deployment Dry Run**
   - Walk through deployment steps
   - Verify rollback procedure
   - Check monitoring dashboards

### Exit Criteria

- [ ] All automated checks pass (100%)
- [ ] All quality gates pass
- [ ] Code review approved
- [ ] Security review passed
- [ ] Documentation complete
- [ ] Deployment plan reviewed

### Example

```bash
# 1. Run full verification
python scripts/verify_implementation.py --strict --report reports/production_readiness.json

# 2. Run all tests
python scripts/ci/run_all_tests.py --suite all --report reports/final_tests.json

# 3. Run quality gates
python scripts/quality/quality_gates.py --gate all

# 4. Review reports
cat reports/production_readiness.json
cat reports/final_tests.json

# 5. Get approval
# (Share reports with team/stakeholders)

# 6. Final checklist
python scripts/verify_implementation.py --checklist --phase production
```

---

## Rollback Procedures

### When to Rollback

Rollback if:
- Critical tests fail
- Performance degradation > 20%
- Security vulnerability discovered
- Production incidents caused by changes
- Stakeholder veto

### Rollback Steps

#### 1. Stop Deployment

```bash
# If using CI/CD, cancel the pipeline
# If manual deployment, stop the process
```

#### 2. Revert Code Changes

```bash
# Option A: Revert git commit
git revert <commit-hash>
git push origin main

# Option B: Reset to previous commit (if not pushed)
git reset --hard <previous-commit>

# Option C: Restore from backup (if available)
git checkout <backup-branch>
```

#### 3. Verify Rollback

```bash
# 1. Run verification on rolled-back code
python scripts/verify_implementation.py

# 2. Run smoke tests
python scripts/ci/run_all_tests.py --suite smoke

# 3. Verify system is stable
python scripts/health_check.py
```

#### 4. Document Incident

```bash
# Create incident report
cat > incident_report.md <<EOF
## Incident Report

**Date:** $(date)
**Issue:** [Brief description]
**Rollback Reason:** [Why rollback was needed]
**Actions Taken:** [What was rolled back]
**Status:** System rolled back to previous stable state
**Next Steps:** [What needs to be fixed before retrying]
EOF
```

#### 5. Post-Mortem

- Identify root cause
- Document lessons learned
- Update verification workflow if needed
- Plan fix and re-verification

---

## Troubleshooting

### Common Issues

#### Issue: Tests Timeout

**Symptom:** Tests take too long and hit timeout

**Solution:**
```bash
# 1. Increase timeout
python scripts/ci/run_all_tests.py --suite all --timeout 1200

# 2. Run tests in parallel
python scripts/ci/run_all_tests.py --suite all --parallel

# 3. Run only failing tests
python scripts/ci/run_all_tests.py --suite critical --timeout 300
```

#### Issue: Import Errors

**Symptom:** Modules cannot be imported

**Solution:**
```bash
# 1. Check if files exist
python scripts/verify_implementation.py --files-only

# 2. Check syntax
python scripts/verify_implementation.py --syntax-only

# 3. Verify Python path
python -c "import sys; print('\n'.join(sys.path))"

# 4. Check for circular imports
python -c "import src.module_name"
```

#### Issue: Test Failures

**Symptom:** Tests fail unexpectedly

**Solution:**
```bash
# 1. Run specific test with verbose output
pytest tests/path/to/test.py::test_name -v --tb=short

# 2. Check test dependencies
pip list | grep pytest

# 3. Clear pytest cache
rm -rf .pytest_cache
pytest --cache-clear

# 4. Run tests in isolation
pytest tests/path/to/test.py --forked
```

#### Issue: Quality Gates Fail

**Symptom:** Quality gates block production readiness

**Solution:**
```bash
# 1. See which gates failed
python scripts/quality/quality_gates.py --gate all --verbose

# 2. Run specific gate
python scripts/quality/quality_gates.py --gate test_pass_rate

# 3. Check gate configuration
cat config/quality_gates.yaml

# 4. Adjust thresholds if needed (with justification)
# Edit config/quality_gates.yaml
```

---

## Quick Reference

### Commands Summary

```bash
# Full verification
python scripts/verify_implementation.py --strict

# Run all tests
python scripts/ci/run_all_tests.py --suite all

# Run specific suite
python scripts/ci/run_all_tests.py --suite critical --timeout 300

# Check quality gates
python scripts/quality/quality_gates.py --gate all

# View checklist
python scripts/verify_implementation.py --checklist

# Generate reports
python scripts/verify_implementation.py --report reports/verification.json
python scripts/ci/run_all_tests.py --suite all --report reports/tests.json
```

### Phase Checklists Quick Access

```bash
# Phase 1: Design Review
python scripts/verify_implementation.py --checklist --phase design

# Phase 2: Implementation
python scripts/verify_implementation.py --checklist --phase implementation

# Phase 3: Integration
python scripts/verify_implementation.py --checklist --phase integration

# Phase 4: Production Readiness
python scripts/verify_implementation.py --checklist --phase production
```

### Emergency Rollback

```bash
# 1. Revert last commit
git revert HEAD
git push origin main

# 2. Verify rollback
python scripts/verify_implementation.py
python scripts/ci/run_all_tests.py --suite smoke

# 3. Check system health
python scripts/health_check.py
```

---

## Maintenance

This workflow document should be updated when:
- New verification tools are added
- Quality gates change
- Process improvements are identified
- Common issues are discovered

**Last Updated:** 2025-12-11
**Version:** 1.0.0
**Maintainer:** Development Team
