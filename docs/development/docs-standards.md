# Documentation Standards for Claims

## Purpose

This document defines standards for making claims in documentation to ensure accuracy, honesty, and transparency. It prevents misleading claims by requiring evidence, proper qualification, and clear status indicators.

## Overview

All documentation must distinguish between three types of claims:
- **Verified claims**: Backed by concrete evidence that has been validated
- **Reported claims**: Information reported by tools/agents but not independently verified
- **Projected claims**: Estimates, expectations, or design intentions

## Claim Categories

### 1. Verified Claims (✅)

**Definition**: Claims backed by concrete, independently validated evidence.

**Requirements**:
- Must link to evidence (file, output, test result)
- Evidence must be recent (within same development phase)
- Evidence must be relevant to the specific claim
- Evidence must be reproducible

**Status marker**: ✅ Verified

**Language patterns**:
- "Verified by [test/output/measurement]"
- "Confirmed through [method]"
- "Validated by running [command]"
- "Evidence: [link to file/output]"

**Examples**:

Good:
```markdown
✅ GPU detection works correctly
- Evidence: `tests/test_gpu_detector.py::test_detect_rtx4090` passes
- Run: `pytest tests/test_gpu_detector.py -v`
- Output shows: RTX 4090 detected with 24GB memory
```

Bad:
```markdown
GPU detection works perfectly
```

### 2. Reported Claims (📋)

**Definition**: Information reported by agents, tools, or automated processes that has not been independently verified.

**Requirements**:
- Must cite the source (agent name, tool name, log file)
- Must use qualified language
- Should include how to verify independently
- Must not use absolute language

**Status marker**: 📋 Reported

**Language patterns**:
- "Agent reports..."
- "According to [tool/agent]..."
- "Logs indicate..."
- "Tool output shows..."

**Examples**:

Good:
```markdown
📋 Agent reports 305 test files created
- Source: Implementation agent completion log
- To verify: Run `find tests/ -name "test_*.py" | wc -l`
- Status: ⏳ Pending independent verification
```

Bad:
```markdown
305 tests pass successfully
```

### 3. Projected Claims (🎯)

**Definition**: Estimates, expectations, design intentions, or future capabilities.

**Requirements**:
- Must clearly indicate projection/estimation
- Must state basis for projection
- Should include uncertainty/confidence level
- Must not be presented as current fact

**Status marker**: 🎯 Projected

**Language patterns**:
- "Expected to..."
- "Designed for..."
- "Estimated..."
- "Projected..."
- "Should handle..."
- "Intended to..."

**Examples**:

Good:
```markdown
🎯 Expected to handle 10,000 requests/minute
- Basis: Design target based on similar systems
- Confidence: Medium (not yet benchmarked)
- Verification pending: Load testing with realistic workload
```

Bad:
```markdown
Handles 10,000 requests/minute
```

## Language Standards

### Absolute Language (Requires Evidence)

The following patterns require verified evidence:

**Quantitative claims**:
- "100%" → Must link to complete test coverage report
- "All X pass" → Must link to test output showing all passing
- "X files created" → Must link to file listing or creation log
- "Zero errors" → Must link to error log or test output
- "N% improvement" → Must link to benchmark comparison

**Status claims**:
- "Production ready" → Must link to production readiness checklist
- "Fully implemented" → Must link to completion criteria and validation
- "Complete" → Must link to acceptance tests passing
- "Working" → Must link to test output or demonstration

**Capability claims**:
- "Supports X" → Must link to test demonstrating support
- "Handles X" → Must link to test with actual handling
- "Detects X" → Must link to detection test output

### Qualified Language (Allowed Without Evidence)

These patterns are acceptable without immediate evidence:

**Reported information**:
- "Agent reports X"
- "According to [source], X"
- "Logs indicate X"
- "Tool output suggests X"

**Projected information**:
- "Expected to X"
- "Designed for X"
- "Should X"
- "Intended to X"
- "Estimated to X"

**Conditional information**:
- "May X"
- "Could X"
- "Might X"
- "Potentially X"

## Evidence Requirements

### Types of Evidence

1. **Test output**: Actual pytest/test runner output showing passing tests
2. **File listings**: Directory listings, file counts, file presence verification
3. **Command output**: Results from running specific verification commands
4. **Measurements**: Performance metrics, coverage reports, benchmark results
5. **Screenshots/logs**: Visual or logged proof of functionality
6. **Code references**: Links to specific implementation with line numbers

### Evidence Validation Criteria

Valid evidence must be:

1. **Relevant**: Directly supports the specific claim being made
2. **Recent**: Created in the same development phase/sprint
3. **Complete**: Fully demonstrates the claimed capability
4. **Reproducible**: Can be regenerated by running specified commands
5. **Accessible**: Linked or referenced in documentation

### Evidence Linking

All verified claims must link to evidence using one of these formats:

```markdown
✅ Claim statement
- Evidence: [file path or command output]
- Verification: `command to reproduce`
- Date: YYYY-MM-DD
```

```markdown
✅ Claim statement (verified by [test/command])
```

```markdown
✅ Claim statement
- See: [file path]:[line numbers]
```

## Review Checklist

Use this checklist when writing or reviewing documentation:

### Claim Detection

- [ ] Identify all quantitative claims (numbers, percentages, counts)
- [ ] Identify all status claims (ready, complete, working, implemented)
- [ ] Identify all capability claims (supports, handles, detects, processes)

### Evidence Check

For each verified claim:
- [ ] Evidence link exists and is accessible
- [ ] Evidence is relevant to the specific claim
- [ ] Evidence is recent (same development phase)
- [ ] Evidence can be reproduced with given commands
- [ ] Evidence format is clear and complete

### Language Validation

- [ ] Absolute language only used with verified evidence
- [ ] Reported claims use qualified language ("agent reports", "according to")
- [ ] Projected claims clearly marked as estimates/expectations
- [ ] Status markers (✅📋🎯⏳) used consistently
- [ ] No misleading implications or ambiguity

### Structure Check

- [ ] Claims organized by category (verified/reported/projected)
- [ ] Verification commands provided for reported claims
- [ ] Confidence levels stated for projected claims
- [ ] Transparency disclosure included where appropriate

## Examples: Good vs Bad

### Example 1: Test Coverage

**Bad**:
```markdown
All tests pass successfully. Test coverage is 100%.
```

**Good**:
```markdown
✅ Core translation tests pass (verified 2024-12-11)
- Evidence: `pytest tests/core/ -v --cov=src/core`
- Coverage: 94% of core module (see reports/coverage_core.html)
- Note: Full suite not yet verified

📋 Agent reports 305 test files created
- Source: Implementation agent logs
- To verify: `find tests/ -name "test_*.py" | wc -l`
- Status: ⏳ Pending independent verification
```

### Example 2: Performance Claims

**Bad**:
```markdown
The system processes translations in under 1 second.
```

**Good**:
```markdown
🎯 Designed to process translations in under 1 second
- Basis: Design target for single-page translations
- Confidence: Medium (architecture supports it)
- Verification pending: Performance benchmarking suite

📋 Initial tests report ~0.8s for typical pages
- Source: Agent development logs
- To verify: Run `python scripts/benchmark_translation.py`
```

### Example 3: Feature Implementation

**Bad**:
```markdown
GPU acceleration fully implemented and working.
```

**Good**:
```markdown
✅ GPU detection module implemented and tested
- Evidence: `tests/test_gpu_detector.py` - 12 tests passing
- Verification: `pytest tests/test_gpu_detector.py -v`
- Tested on: RTX 4090, GTX 1080, CPU fallback

📋 Agent reports GPU-accelerated translation implemented
- Source: Implementation logs for translation pipeline
- Files: `src/translation/gpu_translator.py` (420 lines)
- Status: ⏳ End-to-end testing pending

🎯 Expected 3-5x speedup on GPU vs CPU
- Basis: Similar implementations in comparable systems
- Confidence: Low (not yet benchmarked in this system)
- Verification pending: Comparative benchmarking
```

### Example 4: System Status

**Bad**:
```markdown
System is 100% production ready. All features complete.
```

**Good**:
```markdown
**Implementation Status**: ✅ Complete
**Verification Status**: ⏳ Pending

📋 Agents report implementation complete
- Source: All taskcard completion logs
- Files claimed: 150+ Python files
- To verify: Manual review of critical paths

✅ Core architecture verified
- Evidence: Code review of main modules
- Verification: Structural validation passed
- See: docs/architecture_review.md

⏳ Pending verification:
- End-to-end integration testing
- Performance benchmarking
- Production environment testing
- Load testing
- Security review

**Confidence levels**:
- Implementation completeness: Medium (based on agent reports)
- Code quality: High (verified through reviews)
- Production readiness: Low (limited end-to-end verification)
```

## Status Markers Reference

| Marker | Meaning | Requirements |
|--------|---------|--------------|
| ✅ | Verified | Evidence exists and has been validated |
| 📋 | Reported | Information from agent/tool, not independently verified |
| 🎯 | Projected | Estimate, expectation, or design intention |
| ⏳ | Pending | Verification pending, not yet complete |
| ⚠️ | Partial | Partially verified or partially complete |
| ❌ | Not verified | Explicitly not verified or verification failed |

## Validation Process

### Automated Validation

Use the documentation validator to check compliance:

```bash
# Validate all documentation
python scripts/validate_documentation.py --check-all

# Validate specific file
python scripts/validate_documentation.py --file IMPLEMENTATION_COMPLETE.md

# Generate validation report
python scripts/validate_documentation.py --check-all --report reports/doc_validation.json
```

### Manual Review

For high-stakes documentation (releases, production deployments):

1. Run automated validation
2. Review all claims manually against checklist
3. Verify random sample of evidence links
4. Check for misleading implications
5. Validate confidence levels are appropriate
6. Ensure transparency disclosure is complete

## Common Pitfalls to Avoid

### Pitfall 1: Absolute Language Without Evidence

**Don't**:
```markdown
All integration tests pass.
```

**Do**:
```markdown
📋 Agent reports all integration tests pass
- Source: Test execution logs
- To verify: `pytest tests/integration/ -v`
- Status: ⏳ Independent verification pending
```

### Pitfall 2: Conflating Implementation with Verification

**Don't**:
```markdown
Feature X is complete and working.
```

**Do**:
```markdown
**Feature X Status**:
- Implementation: ✅ Complete (all code written)
- Verification: ⏳ Pending (tests not yet run)

📋 Agent reports feature implemented
- Files: src/features/x.py (350 lines)
- Tests: tests/test_feature_x.py (15 tests)
- Status: Code review pending
```

### Pitfall 3: Vague Evidence References

**Don't**:
```markdown
✅ Tests pass (see test results)
```

**Do**:
```markdown
✅ Core tests pass (verified 2024-12-11)
- Evidence: pytest_output_2024-12-11.log lines 45-89
- Command: `pytest tests/core/ -v`
- Result: 47/47 tests passed
```

### Pitfall 4: Unqualified Performance Claims

**Don't**:
```markdown
System handles 1000 requests per second.
```

**Do**:
```markdown
🎯 Designed to handle 1000 requests per second
- Basis: Architecture supports async processing
- Confidence: Low (not yet load tested)
- Verification: `python scripts/load_test.py --target-rps 1000`
```

### Pitfall 5: Missing Verification Commands

**Don't**:
```markdown
📋 Agent reports GPU detected
```

**Do**:
```markdown
📋 Agent reports RTX 4090 GPU detected
- Source: GPU detector execution log
- To verify: `python -c "from src.gpu import detect_gpu; print(detect_gpu())"`
- Expected output: "RTX 4090 (24GB)"
```

## Transparency Disclosure Template

For major documentation (implementation summaries, release notes), include:

```markdown
## Verification Methodology Disclosure

**Report Generation**: This report aggregates information from [source]

**Verification Levels**:

✅ **Independently Verified** (High Confidence):
- [List what was actually verified with evidence]

📋 **Reported by Agents** (Medium Confidence):
- [List what agents claim but wasn't independently verified]

⏳ **Pending Verification** (Low Confidence):
- [List what needs verification]

**Recommended Next Steps**:
1. [Verification command/action 1]
2. [Verification command/action 2]
3. [etc.]

**Confidence Assessment**: [Overall confidence level with justification]
```

## Updates and Maintenance

These standards should be:
- Reviewed quarterly for effectiveness
- Updated when new claim patterns emerge
- Aligned with industry technical writing standards
- Validated through regular documentation audits

## References

- Technical Writing Standards: IEEE Standard for Software Documentation
- Evidence-Based Documentation: Google Developer Documentation Style Guide
- Status Markers: Conventional Commits Specification (adapted)

## Version

- Version: 1.0
- Last Updated: 2024-12-11
- Owner: Documentation Standards Working Group
