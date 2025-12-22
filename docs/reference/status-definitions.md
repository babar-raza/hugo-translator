# Status Definitions - Two-Tier Status System

## Purpose

This document defines the two-tier status system used throughout project documentation to clearly separate "implementation complete" from "verification complete". This distinction prevents misleading claims about production readiness.

## Overview

The two-tier status system tracks work across two independent dimensions:

1. **Implementation Status**: Has the code been written?
2. **Verification Status**: Has the code been tested and validated?

Both dimensions must reach "Complete" before a feature can be considered production-ready.

## Two-Tier Status Model

### Dimension 1: Implementation Status

Tracks whether code has been written and integrated.

| Status | Icon | Meaning | Criteria |
|--------|------|---------|----------|
| Not Started | ❌ | No code written | No files created, no code exists |
| In Progress | 🔄 | Code being written | Some files exist, implementation incomplete |
| Complete | ✅ | Code written | All planned code written, files created, integrated |

**Definition**: Implementation is "Complete" when:
- All planned source files have been created
- All planned functions/classes have been implemented
- Code compiles/runs without syntax errors
- Code has been integrated into the codebase
- Basic smoke tests pass (code runs without crashing)

**Does NOT require**:
- Tests passing
- Code review approval
- Performance validation
- Integration testing
- Production deployment

### Dimension 2: Verification Status

Tracks whether implementation has been tested and validated.

| Status | Icon | Meaning | Criteria |
|--------|------|---------|----------|
| Not Started | ⏳ | Not verified | No tests run, no validation performed |
| Partial | ⚠️ | Partially verified | Some tests pass, limited validation |
| Complete | ✅ | Fully verified | All tests pass, comprehensive validation |

**Definition**: Verification is "Complete" when:
- All unit tests pass
- Integration tests pass
- Code review completed and approved
- Performance meets requirements
- Edge cases tested
- Error handling validated
- Documentation reviewed
- Acceptance criteria met

**Does NOT require**:
- Production deployment
- User acceptance testing (unless specified)
- Load testing (unless specified)

### Combined Status Notation

Use both statuses together in this format:

```markdown
**Status:** [Implementation: ✅ Complete] [Verification: ⏳ Not Started]
```

Examples:
- `[Implementation: ❌ Not Started] [Verification: ⏳ Not Started]` - Work hasn't begun
- `[Implementation: 🔄 In Progress] [Verification: ⏳ Not Started]` - Coding in progress
- `[Implementation: ✅ Complete] [Verification: ⏳ Not Started]` - Code done, testing pending
- `[Implementation: ✅ Complete] [Verification: ⚠️ Partial]` - Code done, some tests passing
- `[Implementation: ✅ Complete] [Verification: ✅ Complete]` - Fully done and verified

## Status Transition Rules

### Valid Transitions

**Implementation Status:**
1. ❌ Not Started → 🔄 In Progress (start writing code)
2. 🔄 In Progress → ✅ Complete (finish all code)
3. 🔄 In Progress → ❌ Not Started (abandoned/restarted)
4. ✅ Complete → 🔄 In Progress (major refactoring)

**Verification Status:**
1. ⏳ Not Started → ⚠️ Partial (some tests passing)
2. ⏳ Not Started → ✅ Complete (all tests pass first try)
3. ⚠️ Partial → ✅ Complete (all tests now passing)
4. ⚠️ Partial → ⏳ Not Started (tests broken, need restart)
5. ✅ Complete → ⚠️ Partial (regression, some tests failing)
6. ✅ Complete → ⏳ Not Started (major changes invalidate tests)

### Invalid Transitions

**Cannot verify before implementing:**
- ❌ `[Implementation: ❌] [Verification: ✅]` - Cannot verify code that doesn't exist
- ❌ `[Implementation: 🔄] [Verification: ✅]` - Cannot fully verify incomplete code

**Logical rule**: Verification status cannot exceed Implementation status
- If Implementation is ❌ Not Started, Verification must be ⏳ Not Started
- If Implementation is 🔄 In Progress, Verification can be ⏳ Not Started or ⚠️ Partial
- If Implementation is ✅ Complete, Verification can be any status

## Status Criteria Details

### Implementation Complete Criteria

To mark Implementation as ✅ Complete, verify:

- [ ] All planned source files created (check file list)
- [ ] All planned functions/classes implemented (check function count)
- [ ] Code compiles without syntax errors (run linter)
- [ ] Code runs without immediate crashes (basic smoke test)
- [ ] Code integrated into codebase (imports work, no broken references)
- [ ] Basic functionality works (can execute main code path)
- [ ] No TODO markers for critical functionality
- [ ] Dependencies added to requirements

**Evidence**: File listings, line counts, basic execution logs

### Verification Complete Criteria

To mark Verification as ✅ Complete, verify:

- [ ] All unit tests pass (`pytest tests/unit/ -v`)
- [ ] Integration tests pass (`pytest tests/integration/ -v`)
- [ ] Code coverage meets threshold (typically 80%+)
- [ ] Code review completed and approved
- [ ] Performance meets requirements (benchmarks pass)
- [ ] Edge cases tested (boundary conditions, error cases)
- [ ] Error handling validated (test failure modes)
- [ ] Security review passed (if applicable)
- [ ] Documentation complete and accurate
- [ ] All acceptance criteria met

**Evidence**: Test output, coverage reports, review approvals, benchmark results

### Partial Verification Criteria

Mark Verification as ⚠️ Partial when:

- Some but not all tests pass (e.g., 80% passing)
- Unit tests pass but integration tests don't
- Happy path tested but edge cases not tested
- Manual testing done but automated tests incomplete
- Code review in progress but not complete
- Performance partially validated

**Evidence**: Partial test output, specific test results, review status

## Usage in Documentation

### In Plan Files

Each task/taskcard should show both statuses:

```markdown
## [TASK-001] Implement Feature X

**Status:** [Implementation: ✅ Complete] [Verification: ⚠️ Partial]
**Completed:** 2024-12-11

### Implementation Evidence
- Files created: src/feature_x.py (350 lines)
- Functions implemented: 12/12
- Integration: Successfully imported by main module

### Verification Evidence
- Unit tests: 15/15 passing
- Integration tests: 2/5 passing (3 failing due to dependency issues)
- Coverage: 78% (target: 80%)
- Status: Partial - integration tests need fixing
```

### In Status Reports

```markdown
## Feature Status Summary

| Feature | Implementation | Verification | Ready? |
|---------|---------------|--------------|--------|
| User Auth | ✅ Complete | ✅ Complete | ✅ YES |
| Data Export | ✅ Complete | ⚠️ Partial | ❌ NO |
| API Client | 🔄 In Progress | ⏳ Not Started | ❌ NO |
| Logging | ✅ Complete | ⏳ Not Started | ❌ NO |
```

### In Pull Requests

```markdown
## Changes

Implements feature X as described in ticket #123.

**Status:** [Implementation: ✅ Complete] [Verification: ✅ Complete]

**Implementation:**
- Created src/feature_x.py (350 lines)
- Created src/feature_x_utils.py (120 lines)
- Updated src/main.py to integrate feature

**Verification:**
- Unit tests: 15 tests, all passing
- Integration tests: 5 tests, all passing
- Coverage: 92% (exceeds 80% target)
- Manual testing: Smoke tested on dev environment
- Code review: Self-review complete, awaiting peer review
```

## Common Scenarios

### Scenario 1: New Feature Development

**Day 1**: Start coding
```
[Implementation: 🔄 In Progress] [Verification: ⏳ Not Started]
```

**Day 3**: Code complete
```
[Implementation: ✅ Complete] [Verification: ⏳ Not Started]
```

**Day 4**: Some tests passing
```
[Implementation: ✅ Complete] [Verification: ⚠️ Partial]
```

**Day 5**: All tests passing
```
[Implementation: ✅ Complete] [Verification: ✅ Complete]
```

### Scenario 2: Bug Fix Breaks Tests

**Before**: Feature working
```
[Implementation: ✅ Complete] [Verification: ✅ Complete]
```

**After bug fix**: Implementation changed
```
[Implementation: 🔄 In Progress] [Verification: ⏳ Not Started]
```

**Fix complete**: Code updated
```
[Implementation: ✅ Complete] [Verification: ⏳ Not Started]
```

**Tests updated**: Tests passing again
```
[Implementation: ✅ Complete] [Verification: ✅ Complete]
```

### Scenario 3: Integration Issues

**After coding**: Implementation done
```
[Implementation: ✅ Complete] [Verification: ⏳ Not Started]
```

**After unit tests**: Unit tests pass
```
[Implementation: ✅ Complete] [Verification: ⚠️ Partial]
Note: Unit tests pass, integration tests pending
```

**Integration tests fail**: Issues found
```
[Implementation: ✅ Complete] [Verification: ⚠️ Partial]
Note: 2/5 integration tests failing, investigating
```

**After fixes**: All tests pass
```
[Implementation: ✅ Complete] [Verification: ✅ Complete]
```

## Anti-Patterns to Avoid

### Anti-Pattern 1: Claiming Verification Without Evidence

**Wrong**:
```markdown
**Status:** [Implementation: ✅ Complete] [Verification: ✅ Complete]

All tests pass.
```

**Right**:
```markdown
**Status:** [Implementation: ✅ Complete] [Verification: ✅ Complete]

**Verification Evidence:**
- Test output: pytest_output_2024-12-11.log
- Command: `pytest tests/ -v`
- Result: 45/45 tests passed
- Coverage: 87% (see coverage_report.html)
```

### Anti-Pattern 2: Marking Complete Based on Agent Reports

**Wrong**:
```markdown
**Status:** [Implementation: ✅ Complete] [Verification: ✅ Complete]

Agent reports all tests passing.
```

**Right**:
```markdown
**Status:** [Implementation: ✅ Complete] [Verification: ⏳ Not Started]

📋 Agent reports all tests passing.
⏳ Independent verification pending: run `pytest tests/ -v` to confirm.
```

### Anti-Pattern 3: Skipping Partial Status

**Wrong**:
```markdown
**Status:** [Implementation: ✅ Complete] [Verification: ⏳ Not Started]

(when actually 80% of tests pass)
```

**Right**:
```markdown
**Status:** [Implementation: ✅ Complete] [Verification: ⚠️ Partial]

**Verification Evidence:**
- Unit tests: 40/45 passing (5 failing)
- Integration tests: Not yet run
- Status: Partial - fixing 5 failing unit tests
```

## Integration with Documentation Standards

The two-tier status system integrates with [DOCUMENTATION_STANDARDS.md](DOCUMENTATION_STANDARDS.md):

- ✅ **Verified claims** require `[Verification: ✅ Complete]`
- 📋 **Reported claims** typically have `[Verification: ⏳ Not Started]` or `[Verification: ⚠️ Partial]`
- 🎯 **Projected claims** usually have `[Implementation: ❌ Not Started]`

Example:
```markdown
## Feature X

**Status:** [Implementation: ✅ Complete] [Verification: ⏳ Not Started]

📋 Agent reports feature X implemented with full test coverage.

⏳ **Verification pending**: Run `pytest tests/test_feature_x.py -v` to verify claim.
```

## Quick Reference

### Status Icons

**Implementation:**
- ❌ Not Started
- 🔄 In Progress
- ✅ Complete

**Verification:**
- ⏳ Not Started
- ⚠️ Partial
- ✅ Complete

### Common Combinations

| Implementation | Verification | Meaning |
|---------------|--------------|---------|
| ❌ | ⏳ | Work not started |
| 🔄 | ⏳ | Coding in progress |
| ✅ | ⏳ | Code done, testing pending |
| ✅ | ⚠️ | Code done, some tests passing |
| ✅ | ✅ | Fully done and verified |

### Production Ready?

A feature is **production-ready** only when:
```
[Implementation: ✅ Complete] [Verification: ✅ Complete]
```

All other combinations indicate the feature is **not production-ready**.

## Updates and Maintenance

- Review status definitions quarterly
- Update criteria as testing standards evolve
- Align with industry best practices
- Maintain consistency across all documentation

## Version

- Version: 1.0
- Last Updated: 2024-12-11
- Owner: Documentation Standards Working Group
