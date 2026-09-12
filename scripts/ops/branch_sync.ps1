<#
.SYNOPSIS
  Keeps whatever branch is currently checked out in hugo-translator pushed to
  GitHub (origin) and GitLab, independent of any specific mission.

.DESCRIPTION
  .github/workflows/mirror-gitlab.yml only mirrors main + tags from GitHub to
  GitLab, since that workflow can only react to commits already on GitHub. Real
  work here lives on long-running mission branches that don't merge to main on
  any regular cadence, so this script covers the gap: it pushes the current
  branch (read dynamically, never hardcoded, so it keeps working across mission
  boundaries without edits) on a schedule.

  GitHub is the priority target - a push failure there is logged as an error.
  GitLab is best-effort - a push failure there is logged as a warning and does
  not block or retry; someone can rerun scripts/ops/branch_sync.ps1 manually
  once the underlying issue (e.g. an expired token, see
  docs/operations/github-gitlab-sync.md) is fixed.

  Never force-pushes. A non-fast-forward rejection (someone else pushed
  different commits to the same branch name) is logged as an error and left
  for a human to reconcile, same philosophy as the mirror workflow.

.PARAMETER DryRun
  Log decisions without pushing. Safe any time.
#>

param(
    [switch]$DryRun
)

$ErrorActionPreference = 'Continue'

$RepoRoot  = "c:\Users\prora\OneDrive\Documents\GitHub\hugo-translator"
$LogDir    = Join-Path $RepoRoot "logs"
$LogFile   = Join-Path $LogDir "branch_sync.log"
$LockFile  = Join-Path $LogDir "branch_sync.lock"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-Log {
    param([string]$Message)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$ts  $Message" | Add-Content -Path $LogFile -Encoding utf8
}

function Short($sha) {
    if ([string]::IsNullOrEmpty($sha)) { return "<none>" }
    return $sha.Substring(0, [Math]::Min(7, $sha.Length))
}

if (Test-Path $LockFile) {
    $lockedPid = Get-Content $LockFile -ErrorAction SilentlyContinue | Select-Object -First 1
    $existing = $null
    if ($lockedPid) { $existing = Get-Process -Id $lockedPid -ErrorAction SilentlyContinue }
    if ($existing) {
        Write-Log "Previous run still in flight (PID $lockedPid). Skipping."
        return
    } else {
        Remove-Item $LockFile -Force -ErrorAction SilentlyContinue
    }
}
$PID | Set-Content -Path $LockFile -Encoding ascii

try {
    Set-Location $RepoRoot

    $branch = (git rev-parse --abbrev-ref HEAD 2>$null)
    if ($LASTEXITCODE -ne 0 -or -not $branch -or $branch.Trim() -eq "HEAD") {
        Write-Log "Detached HEAD or no branch resolved. Skipping."
        return
    }
    $branch = $branch.Trim()
    $localHead = (git rev-parse HEAD 2>$null).Trim()

    git fetch origin $branch --quiet 2>$null
    git fetch gitlab $branch --quiet 2>$null

    # --- GitHub (origin): priority target ---
    $originHead = (git rev-parse "origin/$branch" 2>$null)
    if ($LASTEXITCODE -ne 0) { $originHead = "" } else { $originHead = $originHead.Trim() }
    if ($localHead -ne $originHead) {
        if ($DryRun) {
            Write-Log "DryRun: would push $branch to origin ($(Short $originHead) -> $(Short $localHead))."
        } else {
            $out = git push origin "${branch}:${branch}" 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-Log "Pushed $branch to origin ($(Short $localHead))."
            } else {
                Write-Log "ERROR: push to origin failed for ${branch}: $out"
            }
        }
    }

    # --- GitLab: best-effort, never blocks on failure ---
    $gitlabHead = (git rev-parse "gitlab/$branch" 2>$null)
    if ($LASTEXITCODE -ne 0) { $gitlabHead = "" } else { $gitlabHead = $gitlabHead.Trim() }
    if ($localHead -ne $gitlabHead) {
        if ($DryRun) {
            Write-Log "DryRun: would push $branch to gitlab ($(Short $gitlabHead) -> $(Short $localHead))."
        } else {
            $out = git push gitlab "${branch}:${branch}" 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-Log "Pushed $branch to gitlab ($(Short $localHead))."
            } else {
                Write-Log "WARN: push to gitlab failed for ${branch}: $out"
            }
        }
    }
} finally {
    Remove-Item $LockFile -Force -ErrorAction SilentlyContinue
}
