<#
.SYNOPSIS
TC-PORT-LLM-014: explicit, auditable repin of the qualification harness's
execution clone -- closes the "known gap" dd68f590's root-cause record left
open ("left for the next agent/operator rather than forced").

.DESCRIPTION
.local/portfolio-runtime-writable's own `origin` is NOT this control repo --
it is C:\Windows\Temp\hugo-translator-portfolio-autonomous, an intermediate
clone whose own remotes are GitHub (babar-raza/hugo-translator) and GitLab
(gitlab.recruitize.ai/...). Getting a commit from this control repo into the
runtime clone through that chain would require pushing to one of those
remotes -- forbidden for autonomous execution under this mission's
governance ("no push ... human-only actions").

Everything involved is a local git repository on this machine, so this
script instead fetches directly from THIS control repo's own working copy
into the runtime clone -- a local filesystem operation, not a push to any
shared/external remote, and fully reversible. It refuses to touch the
runtime clone unless it is verified clean first (never discards in-flight
work there), and records the before/after SHA so the repin is auditable
evidence, not a silent side effect.
#>
[CmdletBinding()]
param(
    [string]$ControlRepo,
    [string]$RuntimeRepo,
    [string]$Ref = (git -C $ControlRepo rev-parse --abbrev-ref HEAD),
    # Optional: a campaign manifest whose translator_repo_sha must track the
    # repinned clone. verify_environment() hard-refuses on SHA drift, so a
    # repin without this update just trades one preflight failure for
    # another -- learned the hard way running TC-PORT-LLM-008 for real.
    [string]$ManifestPath
)

function Sync-ManifestTranslatorSha([string]$Sha) {
    if (-not $ManifestPath) { return }
    $py = Join-Path $ControlRepo '.venv\Scripts\python.exe'
    & $py -c @"
import yaml
path = r'$ManifestPath'
d = yaml.safe_load(open(path, encoding='utf-8'))
if d.get('translator_repo_sha') != '$Sha':
    d['translator_repo_sha'] = '$Sha'
    with open(path, 'w', encoding='utf-8') as f:
        yaml.safe_dump(d, f, sort_keys=False, allow_unicode=True)
    print(f'updated translator_repo_sha -> $Sha in {path}')
else:
    print(f'{path} translator_repo_sha already $Sha')
"@
}

$ErrorActionPreference = 'Stop'

# PowerShell 5.1 evaluates parameter defaults before reliably populating
# $PSScriptRoot when invoked with -File. Resolve dependent defaults after the
# parameter block so the governed repin works from any working directory.
if ([string]::IsNullOrWhiteSpace($ControlRepo)) {
    $ControlRepo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
}
if ([string]::IsNullOrWhiteSpace($RuntimeRepo)) {
    $RuntimeRepo = Join-Path $ControlRepo '.local\portfolio-runtime-writable'
}

if (-not (Test-Path (Join-Path $RuntimeRepo '.git'))) {
    throw "Not a git repository: $RuntimeRepo"
}

$dirty = git -C $RuntimeRepo status --porcelain
if ($dirty) {
    throw "Refusing to repin: $RuntimeRepo has uncommitted changes (in-flight work). Investigate before forcing anything: `n$dirty"
}

$before = git -C $RuntimeRepo rev-parse HEAD
$controlHead = git -C $ControlRepo rev-parse $Ref

if ($before -eq $controlHead) {
    Write-Output "Already current: $RuntimeRepo is at $before (matches $ControlRepo`:$Ref). Nothing to do."
    Sync-ManifestTranslatorSha $before
    exit 0
}

Write-Output "Repinning $RuntimeRepo from $before to $controlHead (control repo $Ref)..."
# Do not redirect git's stderr in PowerShell 5.1: git's normal progress output
# (e.g. "From <path>") goes to stderr, and 2>&1 here turns each such line into
# a terminating ErrorRecord under $ErrorActionPreference = 'Stop' even though
# the fetch succeeds -- confirmed live (fetch created the ref correctly; only
# the redirect made the script think it had failed).
# A local-path remote does not resolve a short branch name as a fetch source
# on every Git-for-Windows version.  Fetch the explicit branch ref; this is
# still entirely local and does not contact or push to any external remote.
git -C $RuntimeRepo fetch $ControlRepo "refs/heads/${Ref}:refs/repin/${Ref}" | Out-Null
git -C $RuntimeRepo checkout --detach "refs/repin/${Ref}"
git -C $RuntimeRepo update-ref -d "refs/repin/${Ref}"

$after = git -C $RuntimeRepo rev-parse HEAD
if ($after -ne $controlHead) {
    throw "Repin verification failed: expected $controlHead, got $after"
}

$stillDirty = git -C $RuntimeRepo status --porcelain
if ($stillDirty) {
    throw "Repin left the runtime clone dirty -- refusing to declare success: `n$stillDirty"
}

Sync-ManifestTranslatorSha $after

[pscustomobject]@{
    RuntimeRepo = $RuntimeRepo
    Before      = $before
    After       = $after
    ControlRef  = $Ref
} | Format-List
Write-Output "Repin verified clean at $after."
