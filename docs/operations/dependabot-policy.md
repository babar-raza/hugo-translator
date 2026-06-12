# Dependabot PR Handling Policy

> **Applies to:** GitHub mirror (`babar-raza/hugo-translator`) — CI runs here.
> Primary remote is GitLab (`gitlab.recruitize.ai/sialkot/cantt-smallize/hugo-translator`).

---

## Review Ownership

| Category | Owner | SLA |
|----------|-------|-----|
| GitHub Actions version bumps | Maintainer | 7 days |
| ML dependencies (`torch`, `transformers`, `tokenizers`) | ML lead | 14 days |
| Infra/server deps (`redis`, `pydantic`, `fastapi`) | Backend lead | 7 days |
| Dev-only deps (`black`, `ruff`, `ipython`, `pytest-*`) | Any contributor | 3 days |
| Security advisory upgrades | Maintainer | 48 hours |

---

## Auto-Merge Policy

**Auto-merge is disabled** for this repo (as of sprint `cicd-hooks-continuation-20260611`).

All Dependabot PRs require manual review before merging. This is intentional:

- ML deps (`torch`, `transformers`) frequently introduce silent regressions in translation quality.
- GitHub Actions major bumps (e.g. `actions/checkout v5 → v6`) can change checkout behavior, token scopes, and path handling.
- The release gate runs on every PR; merging without reading the CI summary defeats the purpose of the gate.

**Future policy:** Consider enabling auto-merge for dev-only deps (scope `dev.txt` only) once the regression test suite achieves >95% branch coverage for the translation engine.

---

## Handling Procedure

### 1. PR arrives — check CI status

```
gh pr checks <PR_NUMBER> --repo babar-raza/hugo-translator --watch
```

All 6 jobs must pass: Unit Tests, Manifest Check, Regression Tests, Quality Gate, Security Scan, Gate Summary.

### 2. If CI fails with `--exit-zero` or pip-audit error

**Root cause:** PR branch predates `82e5f0c` (pip-audit `--exit-zero` fix, 2026-06-10).

**Fix:** Post a rebase comment on the PR:
```
@dependabot rebase
```

Dependabot will rebase the branch onto current `main` within a few minutes, picking up the workflow fix. Re-check CI.

### 3. If CI fails with ruff I001 (isort)

**Root cause:** PR branch predates `b4d8910` (`pyproject.toml` `I001` per-file-ignores fix, 2026-06-12).

**Fix:** Same — post `@dependabot rebase`.

### 4. If CI fails because of the dependency itself

Example: a new version of `torch` breaks an import used by the translation engine.

1. Read the failing test output in the CI run.
2. If the breakage is in a test file, investigate whether the test is correctly written.
3. If the breakage is real, post `@dependabot ignore this version` and open an issue to track the upgrade separately.
4. Do **not** merge a PR that breaks the regression test suite.

### 5. Review checklist before merge

For **dev-only deps** (black, ruff, ipython, pytest-*):
- [ ] All 6 CI jobs pass
- [ ] `ruff` version bump: check `pyproject.toml` pin compatibility (per-file-ignores, selected rules)

For **infra deps** (redis, pydantic):
- [ ] All 6 CI jobs pass
- [ ] Check for API breaking changes in release notes

For **ML deps** (torch, transformers, tokenizers):
- [ ] All 6 CI jobs pass
- [ ] Run a local smoke translation to verify quality is not regressed
- [ ] Check torch release notes for `torch.jit`, `torch.load`, and model serialization changes
- [ ] Verify no new CVEs introduced (Security Scan job output)

For **GitHub Actions** (actions/checkout, actions/setup-python):
- [ ] All 6 CI jobs pass
- [ ] Read the release notes for the bumped version
- [ ] Check for changes to token permissions, path handling, and cache behavior

### 6. Merge command

```bash
gh pr merge <PR_NUMBER> --repo babar-raza/hugo-translator --squash --delete-branch
```

Use `--squash` to keep the main branch history clean. The commit message is auto-generated from the PR title.

After merge, verify the Release Gate triggers and passes on `main`:

```bash
gh run list --repo babar-raza/hugo-translator --workflow release_gate.yml --limit 3
```

---

## Deferred / Blocked PRs

### PRs requiring manual testing before merge

| PR | Package | Concern |
|----|---------|---------|
| #5 | `transformers >=4.57.6` | HuggingFace M2M100 pipeline API may have changed in 4.57.x series |
| #4 | `actions/checkout v6` | Major version bump — review behavior changes before merging |
| #6 | `actions/setup-python v6` | Major version bump — review pip cache key format changes |

### torch CVE note

`torch==2.12.0` is flagged by pip-audit for CVE-2025-3000. This is a **false positive**: CVE-2025-3000 targets `torch.jit.script` in versions ≤2.6.0, and `fix_versions: []` in the vulnerability database confirms no advisory-specified fix version. This repo is not affected. The Security Scan job runs with `continue-on-error: true` so it does not block the gate.

**Action required:** When pip-audit's vulnerability database is updated with a `fix_versions` entry for CVE-2025-3000, re-evaluate whether `torch==2.12.0` is within the affected range.

---

## Contact

Questions about this policy: open an issue in the repo or ping the maintainer.
