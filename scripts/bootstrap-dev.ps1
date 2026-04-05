#Requires -Version 5.1
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PinnedPythonVersion = "3.14.3"
$PinnedNodeVersion = "24.13.1"
$PinnedNpmVersion = "11.8.0"
$PinnedGitVersion = "2.45.2.windows.1"
$PinnedCodexVersion = "0.104.0"
$VenvDir = Join-Path $RepoRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$CodexInstallRoot = Join-Path $RepoRoot ".tools\codex"
$LocalCodexCmd = Join-Path $CodexInstallRoot "node_modules\.bin\codex.cmd"

function Write-Step([string]$Message) {
    Write-Host "[bootstrap] $Message"
}

function Require-Command([string]$DisplayName, [string[]]$Candidates) {
    foreach ($candidate in $Candidates) {
        $command = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($command) {
            return $command.Source
        }
    }
    throw "$DisplayName command was not found."
}

function Warn-VersionDrift([string]$ToolName, [string]$ActualVersion, [string]$PinnedVersion) {
    if ($ActualVersion -ne $PinnedVersion) {
        Write-Warning "$ToolName version drift detected. expected=$PinnedVersion actual=$ActualVersion"
    }
}

$pythonCmd = Require-Command "Python" @("python.exe", "python")
$gitCmd = Require-Command "Git" @("git.exe", "git")
$nodeCmd = Require-Command "Node.js" @("node.exe", "node")
$npmCmd = Require-Command "npm" @("npm.cmd")

$pythonVersion = ((& $pythonCmd --version) -replace "^Python\s+", "").Trim()
$nodeVersion = ((& $nodeCmd --version) -replace "^v", "").Trim()
$npmVersion = (& $npmCmd --version).Trim()
$gitVersion = ((& $gitCmd --version) -replace "^git version\s+", "").Trim()

Write-Step "Checking tool versions"
Write-Host "  Python: $pythonVersion"
Write-Host "  Node:   $nodeVersion"
Write-Host "  npm:    $npmVersion"
Write-Host "  Git:    $gitVersion"

Warn-VersionDrift "Python" $pythonVersion $PinnedPythonVersion
Warn-VersionDrift "Node" $nodeVersion $PinnedNodeVersion
Warn-VersionDrift "npm" $npmVersion $PinnedNpmVersion
Warn-VersionDrift "Git" $gitVersion $PinnedGitVersion

if (-not (Test-Path $VenvPython)) {
    Write-Step "Creating .venv"
    & $pythonCmd -m venv $VenvDir
} else {
    Write-Step "Reusing .venv"
}

Write-Step "Installing Python dependencies"
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r (Join-Path $RepoRoot "requirements.txt")

Write-Step "Installing repo-local Codex CLI"
New-Item -ItemType Directory -Force -Path $CodexInstallRoot | Out-Null
& $npmCmd install --prefix $CodexInstallRoot "@openai/codex@$PinnedCodexVersion" --save-exact

if (-not (Test-Path $LocalCodexCmd)) {
    throw "Repo-local Codex CLI installation did not finish: $LocalCodexCmd"
}

$codexVersionOutput = (& $LocalCodexCmd --version).Trim()
$codexVersion = ($codexVersionOutput -replace "^codex-cli\s+", "").Trim()
Write-Host "  Local Codex CLI: $codexVersion"
Warn-VersionDrift "Codex CLI" $codexVersion $PinnedCodexVersion

Write-Host ""
Write-Host "Next manual steps"
Write-Host ("1. {0} login" -f $LocalCodexCmd)
Write-Host "2. Optional Claude Code install: npm install -g @anthropic-ai/claude-code"
Write-Host "3. Optional Claude Code check: claude doctor"
Write-Host "4. powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-env.ps1"
Write-Host "5. powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-dev.ps1"
Write-Host "6. Enter Jira/GitHub tokens and per-space local repo paths in the app"
