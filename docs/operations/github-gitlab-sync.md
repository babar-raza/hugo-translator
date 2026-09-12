# GitHub / GitLab Sync

> **GitHub:** `https://github.com/babar-raza/hugo-translator` (`origin`, source of truth)
> **GitLab:** `https://gitlab.recruitize.ai/sialkot/cantt-smallize/hugo-translator` (`gitlab`, mirror + CI gate)
> **Pattern reused from:** `repository-presenter`'s `.github/workflows/mirror-gitlab.yml`

---

## Two mechanisms, two jobs

Real work in this repo lives on long-running mission branches (weeks, hundreds of
commits) that don't merge to `main` on any regular cadence — unlike a normal PR-per-feature
repo, a `main`-only mirror would leave GitLab stale for the entire life of a mission. So
there are two independent mechanisms:

| Mechanism | Scope | Trigger | File |
|---|---|---|---|
| CI mirror | `main` + tags | push to `main`, tag push, manual | `.github/workflows/mirror-gitlab.yml` |
| Branch sync | whatever branch is checked out locally | every 5 min, scheduled task | `scripts/ops/branch_sync.ps1` |

Both are one-way, GitHub-priority, **never force-pushed**: a real divergence on the
GitLab side makes the push fail loudly (CI run failure, or an ERROR line in
`logs/branch_sync.log`) rather than silently overwriting GitLab-only commits.

## CI mirror (`main` + tags)

Runs on GitHub's infrastructure regardless of which machine pushed to GitHub, so it
covers the case a local scheduled task can't: multiple machines/worktrees pushing to
`origin`. Re-run manually if needed:
```
gh workflow run mirror-gitlab.yml --repo babar-raza/hugo-translator
gh run watch --repo babar-raza/hugo-translator
```

## Branch sync (active mission/work branches)

`scripts/ops/branch_sync.ps1` reads the currently checked-out branch dynamically (never
hardcoded), so it keeps working across mission boundaries without edits. Registered once via:
```
powershell -ExecutionPolicy Bypass -File scripts\ops\register_branch_sync_task.ps1
```
which creates the `HugoTranslatorBranchSync` scheduled task (5-minute repeating trigger,
no admin rights required — git push doesn't need them). Logs to `logs/branch_sync.log`.
GitHub is the priority target (a failed push there logs as `ERROR`); GitLab is
best-effort (a failed push there logs as `WARN` and does not block or retry).

## Credentials — `gitlab_token`

Both mechanisms authenticate to GitLab with the same underlying personal access token,
stored in two places that do **not** stay in sync with each other automatically:

1. **Locally**, as the machine-wide Windows environment variable `gitlab_token`, read by
   a git credential helper scoped to `https://gitlab.recruitize.ai` in this repo's
   *local* `.git/config` (not global — see gotcha below):
   ```
   git config --add credential."https://gitlab.recruitize.ai".helper ""
   git config --add credential."https://gitlab.recruitize.ai".helper '!f() { echo username=oauth2; echo "password=$gitlab_token"; }; f'
   ```
2. **In GitHub Actions**, as the repo secret `GITLAB_TOKEN`, a one-time copy of the same
   value (GitHub secrets can never be read back once set, so this can't be a live
   reference — it's a snapshot):
   ```
   printenv gitlab_token | gh secret set GITLAB_TOKEN --repo babar-raza/hugo-translator
   ```

**If `gitlab_token` is ever rotated**, both places need a manual update — rotating the
Windows env var alone does not update the GitHub secret, and vice versa.

### Gotcha: the empty `helper = ` reset line is required

Git's default install on this machine sets a *generic* (matches every host)
`credential.helper = manager` in the global config, which runs Git Credential Manager
for every request — including GitLab's. Because that generic entry is defined after a
plain `credential.<url>.helper = <value>` line would be appended, GCM wins the race and
the custom helper above is silently never invoked, surfacing as
`remote: HTTP Basic: Access denied` on `git fetch`/`git push` to `gitlab.recruitize.ai`,
even with the token line correctly present.

The fix is the `helper = ` (empty) line *before* the real one, set locally (not
`--global`): an empty `helper` value resets the accumulated helper list for that URL
match, discarding the inherited generic `manager` entry, so the custom helper right
after it is the only one that runs for `gitlab.recruitize.ai`. `repository-presenter`'s
local `.git/config` already carries this exact pattern — this repo's config was simply
missing it. Verify with `git fetch gitlab` after applying the fix; it should succeed
silently.
