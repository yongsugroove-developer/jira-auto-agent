#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$TagName = "phase-1-freeze"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$GitCmd = (Get-Command git.exe -ErrorAction Stop).Source
$RequiredFiles = @(
    (Join-Path $RepoRoot "README.md"),
    (Join-Path $RepoRoot "docs\phase-1-freeze.md"),
    (Join-Path $RepoRoot "scripts\bootstrap-dev.ps1"),
    (Join-Path $RepoRoot "scripts\check-env.ps1"),
    (Join-Path $RepoRoot "scripts\run-dev.ps1"),
    (Join-Path $RepoRoot "scripts\freeze-phase1.ps1")
)

function Write-Step([string]$Message) {
    Write-Host "[freeze-phase1] $Message"
}

foreach ($requiredFile in $RequiredFiles) {
    if (-not (Test-Path $requiredFile)) {
        throw "Required file is missing: $requiredFile"
    }
}

Write-Step "Checking tracked runtime files"
$trackedRuntime = @(& $GitCmd ls-files data/workflow-batches data/workflow-runs data/project-memory data/.enc_key data/app.db .tools)
$trackedRuntime = @($trackedRuntime | Where-Object { $_ -and $_.Trim() })
if ($trackedRuntime.Count -gt 0) {
    throw "Runtime files are still tracked by git.`n$($trackedRuntime -join [Environment]::NewLine)"
}

Write-Step "Checking worktree state"
& $GitCmd diff --quiet --ignore-submodules=all --
if ($LASTEXITCODE -ne 0) {
    throw "Tracked changes are still present. Commit them first."
}
& $GitCmd diff --cached --quiet --ignore-submodules=all --
if ($LASTEXITCODE -ne 0) {
    throw "Staged changes are still present. Commit them first."
}
$untracked = @(& $GitCmd ls-files --others --exclude-standard)
$untracked = @($untracked | Where-Object { $_ -and $_.Trim() })
if ($untracked.Count -gt 0) {
    throw "Untracked files are still present. Commit or clean them first.`n$($untracked -join [Environment]::NewLine)"
}

Write-Step "Running tests"
$pythonCmd = if (Test-Path $VenvPython) { $VenvPython } else { (Get-Command python.exe -ErrorAction Stop).Source }
& $pythonCmd -m pytest -q

Write-Step "Checking existing tag"
& $GitCmd rev-parse --verify "refs/tags/$TagName" *> $null
if ($LASTEXITCODE -eq 0) {
    throw "Tag already exists: $TagName"
}

Write-Step "Creating tag"
& $GitCmd tag -a $TagName -m "phase-1 freeze"

Write-Host ""
Write-Host "Freeze complete"
Write-Host "  Name: phase-1"
Write-Host "  Tag:  $TagName"
