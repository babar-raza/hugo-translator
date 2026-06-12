# GitLab Runner Setup

> **GitLab instance:** `https://gitlab.recruitize.ai`
> **Project:** `sialkot/cantt-smallize/hugo-translator` (project ID 722)
> **Runner ID:** 150 (`local-windows-powershell`)
> **Status:** Active — first pipeline (14302) passed 2026-06-12

---

## Current Runner

| Field | Value |
|-------|-------|
| ID | 150 |
| Description | `local-windows-powershell` |
| Host | ALIENWARE-M18 (user: prora) |
| Executor | shell (PowerShell 5.1) |
| Tags | `windows`, `python`, `self-hosted` |
| Python | C:\Python313\python.exe (3.13.2) |
| Config | `C:\Users\prora\gitlab-runner-config\config.toml` |
| Binary | `C:\Users\prora\bin\gitlab-runner.exe` (v19.0.1) |
| Work dir | `C:\Users\prora\gitlab-runner-config\work\` |

---

## Starting the Runner

The runner is **not** installed as a Windows Service (requires admin). Start it manually:

```powershell
Start-Process -NoNewWindow ~/bin/gitlab-runner.exe -ArgumentList "run","--config","$HOME/gitlab-runner-config/config.toml","--working-directory","$HOME/gitlab-runner-config/work"
```

Or from Git Bash:
```bash
~/bin/gitlab-runner.exe run \
  --config ~/gitlab-runner-config/config.toml \
  --working-directory ~/gitlab-runner-config/work &
```

To check if the runner is online:
```bash
curl -s --header "PRIVATE-TOKEN: <your-token>" \
  "https://gitlab.recruitize.ai/api/v4/projects/722/runners?status=online"
```

### Auto-start (optional)

To auto-start on login without admin privileges, add a Task Scheduler entry:
```powershell
$action  = New-ScheduledTaskAction -Execute "$env:USERPROFILE\bin\gitlab-runner.exe" `
             -Argument "run --config `"$env:USERPROFILE\gitlab-runner-config\config.toml`" --working-directory `"$env:USERPROFILE\gitlab-runner-config\work`""
$trigger = New-ScheduledTaskTrigger -AtLogOn
Register-ScheduledTask -TaskName "GitLabRunner" -Action $action -Trigger $trigger -RunLevel Limited
```

---

## Registering a New Runner

If the runner is lost or the machine changes, create a new runner authentication token via the API and register:

**Step 1: Create runner token via API**
```bash
curl -s -X POST \
  --header "PRIVATE-TOKEN: <your-token>" \
  --header "Content-Type: application/json" \
  --data '{"runner_type":"project_type","project_id":722,"description":"<description>","tag_list":"windows,python,self-hosted","run_untagged":false}' \
  "https://gitlab.recruitize.ai/api/v4/user/runners"
```

The response contains a `token` field — use it in Step 2.

> **GitLab 17+ note:** `--tag-list` is set server-side at creation (via the API above), not via the `register` command. Do not pass `--tag-list` to `gitlab-runner register`.

**Step 2: Download binary**
```bash
mkdir -p ~/bin
curl -sL "https://gitlab-runner-downloads.s3.amazonaws.com/latest/binaries/gitlab-runner-windows-amd64.exe" \
  -o ~/bin/gitlab-runner.exe
```

**Step 3: Register**
```bash
mkdir -p ~/gitlab-runner-config ~/gitlab-runner-config/work
~/bin/gitlab-runner.exe register \
  --non-interactive \
  --url "https://gitlab.recruitize.ai" \
  --token "<auth-token-from-step-1>" \
  --description "<description>" \
  --executor "shell" \
  --shell "powershell" \
  --config ~/gitlab-runner-config/config.toml
```

**Step 4: Start**
```bash
~/bin/gitlab-runner.exe run \
  --config ~/gitlab-runner-config/config.toml \
  --working-directory ~/gitlab-runner-config/work &
```

---

## Pipeline Design Notes

### venv caching

The `.gitlab-ci.yml` creates a Python venv in `.venv/` (the build directory) on first run and caches it keyed on `requirements/cpu.txt + requirements/dev.txt`. On subsequent runs the cache is restored and the venv is reused, making validate-stage jobs fast.

`GIT_CLEAN_FLAGS: -ffdx --exclude=.venv` prevents `git clean` from deleting the cached `.venv/` between jobs in the same pipeline.

### Why PowerShell 5.1 (not pwsh/PS7)

`pwsh` (PowerShell Core 7) is not installed on ALIENWARE-M18. The runner is configured with `shell = "powershell"` (PowerShell 5.1). The pipeline YAML is compatible with PS5.1. If PS7 is installed in future, update `config.toml` shell to `pwsh`.

### Triggering a pipeline manually

The pipeline only auto-triggers on push when `src/**`, `tests/**`, or `requirements/**` change. To trigger manually:

```bash
curl -s -X POST \
  --header "PRIVATE-TOKEN: <your-token>" \
  "https://gitlab.recruitize.ai/api/v4/projects/722/pipeline?ref=main"
```

Or via the GitLab UI: **CI/CD → Pipelines → Run pipeline**.

---

## First Pipeline Results (14302)

Run on 2026-06-12. All 5 required jobs passed:

| Job | Duration | Status |
|-----|----------|--------|
| unit-tests | 427s | ✓ success |
| manifest-check | 196s | ✓ success |
| regression-tests | 548s | ✓ success |
| quality-gate | 355s | ✓ success |
| gate-summary | 194s | ✓ success |
| security-scan | 281s | advisory (allow_failure: true) |

**Overall: success**

Second run will be significantly faster due to venv cache hit.
