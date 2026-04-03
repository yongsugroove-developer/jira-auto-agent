#Requires -Version 5.1
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$LocalCodexCmd = Join-Path $RepoRoot ".tools\codex\node_modules\.bin\codex.cmd"
$AppEntry = Join-Path $RepoRoot "app\main.py"

if (-not (Test-Path $VenvPython)) {
    throw ".venv is missing. Run scripts\\bootstrap-dev.ps1 first."
}

if (-not (Test-Path $LocalCodexCmd)) {
    throw "Repo-local Codex CLI is missing. Run scripts\\bootstrap-dev.ps1 first."
}

$env:AGENTATION_ENABLED = "0"
$env:AGENTATION_AUTOSTART = "0"
$env:CODEX_CLI_PATH = $LocalCodexCmd

Write-Host "[run-dev] AGENTATION_ENABLED=0"
Write-Host "[run-dev] AGENTATION_AUTOSTART=0"
Write-Host "[run-dev] CODEX_CLI_PATH=$LocalCodexCmd"
Write-Host "[run-dev] http://localhost:5000"

& $VenvPython $AppEntry
