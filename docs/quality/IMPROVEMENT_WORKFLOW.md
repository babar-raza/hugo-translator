# Iterative Improvement Workflow

This document describes the iterative improvement process for achieving 5/5 ratings on all quality dimensions.

## Overview

Every taskcard must achieve a minimum overall rating of 4.0/5 with no dimension below 3.0. The iterative improvement workflow is a systematic process for identifying gaps, making targeted improvements, and tracking progress until all criteria are met.

## The Improvement Cycle

```
┌─────────────────────────────────────────────────────┐
│  1. Run Automated Checks                           │
│     └─ scripts/check_quality.py                    │
└─────────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────────┐
│  2. Rate Current State                             │
│     └─ scripts/rate_taskcard.py <taskcard_id>     │
└─────────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────────┐
│  3. Identify Lowest Dimension                      │
│     └─ Focus improvement effort here               │
└─────────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────────┐
│  4. Apply Targeted Improvements                    │
│     └─ Follow dimension-specific guidance          │
└─────────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────────┐
│  5. Re-run Checks and Re-rate                      │
│     └─ Verify improvements                         │
└─────────────────────────────────────────────────────┘
                    ↓
            ┌───────────────┐
            │ Rating ≥ 4.0? │
            └───────────────┘
              │           │
             Yes          No
              │           │
              ↓           └─── Return to Step 3
          ✅ DONE               (Max 5 iterations)
```

## Step-by-Step Guide

### Step 1: Run Automated Checks

Start every improvement cycle by running all automated quality checks:

```bash
# Run all automated checks
python scripts/check_quality.py

# Output shows pass/fail for each check:
# ✓ python_syntax: All 125 Python files have valid syntax
# ✗ print_statements: Found 3 print() statements (use logger instead)
# ✓ yaml_syntax: All 12 YAML files have valid syntax
# ...
```

**Fix any failing checks immediately** before moving to manual rating.

### Step 2: Rate Current State

Use the rating script to assess the taskcard on all 5 dimensions:

```bash
python scripts/rate_taskcard.py BM-LANG-01
```

The script will prompt you for:
- **Rating (1-5)** for each dimension
- **Evidence** supporting each rating

Example interaction:
```
Correctness
============================================================
  5/5: Works perfectly, all edge cases handled
  4/5: Works correctly, edge cases may fail
  3/5: Works mostly, minor bugs
  2/5: Works partially, major bugs
  1/5: Fundamentally broken

Rating (1-5): 4
Evidence (brief): All tests pass, 2 minor edge cases not covered
```

### Step 3: Identify Lowest Dimension

After rating, the script shows a summary:

```
RATING SUMMARY
============================================================
Correctness         : 4/5
Completeness        : 3/5  ← LOWEST
Production-Ready    : 4/5
Documentation       : 4/5
Testability         : 3/5
------------------------------------------------------------
Overall (weighted)  : 3.65/5

❌ FAIL - Taskcard needs improvement
✗ Overall below 4.0
✗ Completeness below 4.0 (critical dimension)
```

**Focus on the lowest dimension first**, especially if it's a critical dimension (Correctness or Completeness).

### Step 4: Apply Targeted Improvements

Use the dimension-specific improvement guides below to address gaps.

#### Improving Correctness (1→2→3→4→5)

**1/5 → 2/5**: Make it work for basic cases
- Fix syntax errors
- Implement core functionality
- Handle happy path

**2/5 → 3/5**: Reduce major bugs
- Fix critical bugs
- Add input validation
- Handle common error cases

**3/5 → 4/5**: Handle edge cases
- Add unit tests
- Test boundary conditions
- Fix all known bugs

**4/5 → 5/5**: Perfection
- 100% test coverage
- All edge cases tested
- No known bugs
- Manual testing confirms

#### Improving Completeness (1→2→3→4→5)

**1/5 → 2/5**: Implement >50% of requirements
- Focus on core features
- Get something working

**2/5 → 3/5**: Implement 80%+ of requirements
- Add remaining features
- Fill functional gaps

**3/5 → 4/5**: Implement 95%+ of requirements
- Complete all critical features
- Remove most TODOs
- Handle most edge cases

**4/5 → 5/5**: 100% complete
- Remove ALL TODOs
- All acceptance criteria met
- All edge cases covered
- No gaps in functionality

#### Improving Production-Ready (1→2→3→4→5)

**1/5 → 2/5**: Remove obvious prototype code
- Replace stubs with real implementations
- Add basic error handling

**2/5 → 3/5**: Remove most hardcoded values
- Move config to YAML files
- Add basic logging
- Remove debug code

**3/5 → 4/5**: Production-grade code
- All config from files
- Comprehensive error handling
- Structured logging
- No hardcoded secrets

**4/5 → 5/5**: Production-ready
- Security scan passing
- Performance optimized
- Resource cleanup
- Monitoring hooks

#### Improving Documentation (1→2→3→4→5)

**1/5 → 2/5**: Add basic README
- Project description
- Installation steps

**2/5 → 3/5**: Document core APIs
- Docstrings for public functions
- Basic usage examples

**3/5 → 4/5**: Comprehensive docs
- All public APIs documented
- Multiple examples
- Architecture overview

**4/5 → 5/5**: Excellent documentation
- API docs auto-generated
- Architecture diagrams
- Troubleshooting guide
- Examples for all features

#### Improving Testability (1→2→3→4→5)

**1/5 → 2/5**: Add basic tests
- Test core functionality
- Aim for 40%+ coverage

**2/5 → 3/5**: Expand test coverage
- Test edge cases
- Aim for 70%+ coverage

**3/5 → 4/5**: Comprehensive testing
- Unit tests for all functions
- Integration tests for workflows
- Aim for 90%+ coverage

**4/5 → 5/5**: Complete test suite
- 100% line coverage
- All branches covered
- Performance tests
- Regression tests

### Step 5: Re-run Checks and Re-rate

After applying improvements:

1. **Re-run automated checks**:
   ```bash
   python scripts/check_quality.py
   ```

2. **Re-rate the taskcard**:
   ```bash
   python scripts/rate_taskcard.py BM-LANG-01
   ```

3. **Track progress**:
   - Did the lowest dimension improve?
   - Did overall score increase?
   - Are any dimensions now below threshold?

### Iteration Limits

**Maximum 5 iterations** per taskcard. If not converging after 5 iterations:

1. **Review requirements** - Are they realistic?
2. **Reassess approach** - Is the implementation strategy sound?
3. **Ask for help** - Get peer review
4. **Split taskcard** - May be too large

## Example: Successful Improvement Cycle

### Iteration 1 (Initial State)

**Automated Checks**: 3/7 passing
- ✗ TODOs: Found 8 TODO comments
- ✗ print statements: Found 5 print() calls
- ✗ hardcoded paths: Found 2 localhost references

**Manual Rating**:
- Correctness: 4/5 (works, minor bugs)
- Completeness: 3/5 (TODOs remain)
- Production-Ready: 2/5 (hardcoded values, print statements)
- Documentation: 3/5 (basic docs)
- Testability: 3/5 (70% coverage)
- **Overall: 3.15/5 ❌**

**Action**: Focus on Production-Ready (lowest at 2/5)

### Iteration 2 (After Fixes)

**Changes Made**:
- Replaced all print() with logger.info()
- Moved hardcoded values to config/global.yaml
- Added proper error handling

**Automated Checks**: 5/7 passing
- ✓ print statements: None found
- ✓ hardcoded paths: None found
- ✗ TODOs: Still 8 TODO comments

**Manual Rating**:
- Correctness: 4/5
- Completeness: 3/5
- Production-Ready: 4/5 ← **Improved!**
- Documentation: 3/5
- Testability: 3/5
- **Overall: 3.55/5** ← **Progress!**

**Action**: Focus on Completeness (now lowest, critical dimension)

### Iteration 3 (After More Fixes)

**Changes Made**:
- Implemented all 8 TODO items
- Added missing edge case handling
- Updated tests

**Automated Checks**: 7/7 passing ✅
- ✓ All checks passing

**Manual Rating**:
- Correctness: 5/5 ← **Improved!**
- Completeness: 5/5 ← **Improved!**
- Production-Ready: 4/5
- Documentation: 4/5 ← **Improved!**
- Testability: 4/5 ← **Improved!**
- **Overall: 4.65/5 ✅**

**Result**: PASS! All criteria met.

## Tracking Progress

Use the improve_taskcard.py script to track progress across iterations:

```bash
python scripts/improve_taskcard.py BM-LANG-01
```

This creates a history file tracking:
- Ratings at each iteration
- Changes made
- Time spent
- Progress trajectory

## Best Practices

1. **Fix automated issues first** - They're objective and easy to verify
2. **One dimension at a time** - Focused improvements are more effective
3. **Measure before and after** - Track actual improvement
4. **Document changes** - Note what was fixed and why
5. **Celebrate wins** - Each dimension improvement is progress
6. **Know when to stop** - Perfect is the enemy of good (aim for 4/5, not 5/5 on everything)

## Common Pitfalls

❌ **Trying to fix everything at once** - Leads to unfocused work
✅ **Focus on one dimension per iteration**

❌ **Ignoring automated checks** - They catch objective issues
✅ **Run automated checks first, every time**

❌ **Skipping re-rating** - Can't track progress without measurement
✅ **Re-rate after each improvement cycle**

❌ **Perfectionism** - Spending too long getting 5/5 on non-critical dimensions
✅ **Aim for 4/5 on most, 5/5 on critical dimensions only**

## Summary

The iterative improvement workflow is:

1. **Automated checks** → Fix failures
2. **Rate current state** → Identify gaps
3. **Focus on lowest dimension** → Targeted improvement
4. **Apply fixes** → Dimension-specific actions
5. **Re-run and re-rate** → Verify progress
6. **Repeat** → Until passing (max 5 iterations)

**Success criteria**: Overall ≥ 4.0, no dimension < 3.0, Correctness/Completeness ≥ 4.0

With this systematic approach, **most taskcards converge to passing in 2-3 iterations**.
