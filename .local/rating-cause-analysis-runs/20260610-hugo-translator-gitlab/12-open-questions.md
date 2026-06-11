# Open Questions

1. **What is the actual test coverage?** The coverage gate is disabled and no coverage report was found. Running `pytest --cov` would reveal the true number. Given the 1,417-line untested method, coverage is likely below 60%.

2. **What would mypy report?** With strict config but no runs, the first mypy pass could produce 100-1000+ errors. This is unknown without running it.

3. **Are the 689 except-Exception blocks legitimate graceful degradation or bug-hiding?** Auditing each one is needed. The 84 blocks in engine.py alone are concerning — some may mask production-impacting bugs.

4. **Do workers actually respect the documented guardrails?** AGENT_GUARDRAILS.md says "always run release gate" but there's no enforcement. Are developers actually running it?

5. **Are the 123 doc files accurate?** Without automated verification, we can't know which docs have drifted from reality. The batch-generation pattern (same day as src) suggests they may have been generated rather than evolved.

6. **Is the translate_file method actually correct?** At 1,417 lines, it's beyond human review capacity. Edge case bugs could hide for months. Only comprehensive integration tests can provide confidence.

7. **What is the actual runtime behavior under load?** The 48 exception blocks in the worker suggest many failure modes are swallowed. Production logs would need to be audited for suppressed errors.
