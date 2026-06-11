# Phase 4 - Adversarial Plan Review

## Checks

1. **Is the plan too documentation-heavy?** NO - 5 of 7 items are source/test changes.
2. **Does it avoid source/tests unnecessarily?** NO - core work is source bug fix + test fix.
3. **Does it improve appearance without actual maturity?** NO - fixes real bugs, real test failures, real lint violations.
4. **Does it lack verification?** NO - Lane 7 includes re-running all affected tests.
5. **Does it lack rollback?** MINOR - all changes are file edits, easily reverted via git checkout.
6. **Does it use stale reports as truth?** NO - assessment based on live test runs.
7. **Does it create scorecards without enforcement?** NO - no scorecard-only items.
8. **Does it miss real rating-impacting defects?** Review: The shortcode bug is the highest-impact real defect. The ruff violations are real but minor. The FutureWarning is real but minor. No other high-impact defects found.
9. **Does it touch unsafe paths?** NO - all changes are source/test/lint scope.
10. **Does it require human action unnecessarily?** NO - all lanes are agent-executable.

## Plan Adjustments

1. Add backward-compatible `_extract_shortcodes()` method to validator instead of rewriting all tests. This is simpler and keeps test intent clear.
2. Add a comment regex pattern alongside the existing `_SHORTCODE_RE` rather than making one complex regex.
3. Ensure the WARNING vs ERROR distinction is clear: missing/reduced shortcodes = ERROR, extra/unexpected = WARNING.

## Conclusion

Plan is implementation-focused, scoped, safe, and verifiable. Proceed.
