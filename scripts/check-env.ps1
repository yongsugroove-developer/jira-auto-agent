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
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$LocalCodexCmd = Join-Path $RepoRoot ".tools\codex\node_modules\.bin\codex.cmd"
$BlockingIssues = New-Object System.Collections.Generic.List[string]
$Warnings = New-Object System.Collections.Generic.List[string]
$ManualSteps = New-Object System.Collections.Generic.List[string]

function Write-Step([string]$Message) {
    Write-Host "[check-env] $Message"
}

function Require-Command([string]$DisplayName, [string[]]$Candidates) {
    foreach ($candidate in $Candidates) {
        $command = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($command) {
            return $command.Source
        }
    }
    $BlockingIssues.Add("$DisplayName command was not found.")
    return $null
}

function Invoke-CodexCommand([string]$CodexPath, [string]$NodePath, [string[]]$Arguments) {
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $extension = [System.IO.Path]::GetExtension($CodexPath).ToLowerInvariant()
        if ($extension -eq ".js") {
            return & $NodePath $CodexPath @Arguments 2>&1
        }
        return & $CodexPath @Arguments 2>&1
    } finally {
        $ErrorActionPreference = $previousPreference
    }
}

function Warn-VersionDrift([string]$ToolName, [string]$ActualVersion, [string]$PinnedVersion) {
    if ($ActualVersion -ne $PinnedVersion) {
        $Warnings.Add("$ToolName 버전 drift: expected=$PinnedVersion actual=$ActualVersion")
    }
}

function Resolve-ClaudePath() {
    if ($env:CLAUDE_CLI_PATH) {
        $resolved = (Resolve-Path $env:CLAUDE_CLI_PATH -ErrorAction SilentlyContinue).Path
        if ($resolved) {
            return $resolved
        }
        $Warnings.Add("CLAUDE_CLI_PATH is set but invalid: $($env:CLAUDE_CLI_PATH)")
        return ""
    }
    $command = Get-Command "claude" -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    return ""
}

$pythonCmd = Require-Command "Python" @("python.exe", "python")
$gitCmd = Require-Command "Git" @("git.exe", "git")
$nodeCmd = Require-Command "Node.js" @("node.exe", "node")
$npmCmd = Require-Command "npm" @("npm.cmd")

if ($pythonCmd) {
    $pythonVersion = ((& $pythonCmd --version) -replace "^Python\s+", "").Trim()
    Warn-VersionDrift "Python" $pythonVersion $PinnedPythonVersion
    Write-Host "  Python: $pythonVersion"
}
if ($nodeCmd) {
    $nodeVersion = ((& $nodeCmd --version) -replace "^v", "").Trim()
    Warn-VersionDrift "Node" $nodeVersion $PinnedNodeVersion
    Write-Host "  Node:   $nodeVersion"
}
if ($npmCmd) {
    $npmVersion = (& $npmCmd --version).Trim()
    Warn-VersionDrift "npm" $npmVersion $PinnedNpmVersion
    Write-Host "  npm:    $npmVersion"
}
if ($gitCmd) {
    $gitVersion = ((& $gitCmd --version) -replace "^git version\s+", "").Trim()
    Warn-VersionDrift "Git" $gitVersion $PinnedGitVersion
    Write-Host "  Git:    $gitVersion"
}

if (-not (Test-Path $VenvPython)) {
    $BlockingIssues.Add(".venv is missing. Run scripts\\bootstrap-dev.ps1 first.")
}

$resolvedCodexPath = ""
if ($env:CODEX_CLI_PATH) {
    $resolvedCodexPath = (Resolve-Path $env:CODEX_CLI_PATH -ErrorAction SilentlyContinue).Path
    if (-not $resolvedCodexPath) {
        $BlockingIssues.Add("CODEX_CLI_PATH is invalid: $($env:CODEX_CLI_PATH)")
    }
} elseif (Test-Path $LocalCodexCmd) {
    $resolvedCodexPath = $LocalCodexCmd
} else {
    $BlockingIssues.Add("Repo-local Codex CLI is missing. Run scripts\\bootstrap-dev.ps1 first.")
}

if ($resolvedCodexPath -and $nodeCmd) {
    $codexVersionOutput = (Invoke-CodexCommand -CodexPath $resolvedCodexPath -NodePath $nodeCmd -Arguments @("--version") | Out-String).Trim()
    $codexVersion = ($codexVersionOutput -replace "^codex-cli\s+", "").Trim()
    Warn-VersionDrift "Codex CLI" $codexVersion $PinnedCodexVersion
    Write-Host "  Codex:  $codexVersion"

    $loginOutput = (Invoke-CodexCommand -CodexPath $resolvedCodexPath -NodePath $nodeCmd -Arguments @("login", "status") | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $loginOutput -notmatch "Logged in") {
        $BlockingIssues.Add("Codex CLI login is required. Run: $resolvedCodexPath login")
    }
}

function Invoke-ExternalCommand([string]$CommandPath, [string[]]$Arguments) {
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        return & $CommandPath @Arguments 2>&1
    } finally {
        $ErrorActionPreference = $previousPreference
    }
}

function Invoke-ExternalCommandWithTimeout([string]$CommandPath, [string[]]$Arguments, [int]$TimeoutSeconds) {
    $job = Start-Job -ScriptBlock {
        param([string]$InnerCommandPath, [string[]]$InnerArguments)
        $previousPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            $output = (& $InnerCommandPath @InnerArguments 2>&1 | Out-String).Trim()
            [pscustomobject]@{
                TimedOut = $false
                ExitCode = $LASTEXITCODE
                Output = $output
            }
        } finally {
            $ErrorActionPreference = $previousPreference
        }
    } -ArgumentList $CommandPath, $Arguments

    try {
        $completedJob = Wait-Job -Job $job -Timeout $TimeoutSeconds
        if (-not $completedJob) {
            Stop-Job -Job $job -ErrorAction SilentlyContinue | Out-Null
            return [pscustomobject]@{
                TimedOut = $true
                ExitCode = $null
                Output = ""
            }
        }
        return Receive-Job -Job $job
    } finally {
        Remove-Job -Job $job -Force -ErrorAction SilentlyContinue | Out-Null
    }
}

$resolvedClaudePath = Resolve-ClaudePath
if ($resolvedClaudePath) {
    $claudeVersionOutput = (Invoke-ExternalCommand -CommandPath $resolvedClaudePath -Arguments @("--version") | Out-String).Trim()
    Write-Host "  Claude: $claudeVersionOutput"
    Write-Host "  Claude Path: $resolvedClaudePath"

    $claudeAuthResult = Invoke-ExternalCommandWithTimeout -CommandPath $resolvedClaudePath -Arguments @("auth", "status") -TimeoutSeconds 10
    if ($claudeAuthResult.TimedOut) {
        $Warnings.Add("Claude Code auth status check timed out. Run: $resolvedClaudePath auth status")
    } elseif ($claudeAuthResult.ExitCode -ne 0) {
        $Warnings.Add("Claude Code auth status check failed. Run: $resolvedClaudePath auth status")
    } else {
        try {
            $claudeAuth = $claudeAuthResult.Output | ConvertFrom-Json
            if ($claudeAuth.loggedIn) {
                $authMethod = if ($claudeAuth.authMethod) { [string]$claudeAuth.authMethod } else { "unknown" }
                $apiProvider = if ($claudeAuth.apiProvider) { [string]$claudeAuth.apiProvider } else { "unknown" }
                Write-Host "  Claude Auth: logged in ($authMethod / $apiProvider)"
            } else {
                Write-Host "  Claude Auth: not logged in"
                $BlockingIssues.Add("Claude Code login is required. Run: $resolvedClaudePath auth login")
            }
        } catch {
            $Warnings.Add("Claude Code auth status output could not be parsed. Run: $resolvedClaudePath auth status")
        }
    }

    $doctorResult = Invoke-ExternalCommandWithTimeout -CommandPath $resolvedClaudePath -Arguments @("doctor") -TimeoutSeconds 20
    if ($doctorResult.TimedOut) {
        $Warnings.Add("Claude Code doctor check timed out after 20s. Run: $resolvedClaudePath doctor")
    } elseif ($doctorResult.ExitCode -ne 0) {
        $Warnings.Add("Claude Code doctor check needs attention. Run: $resolvedClaudePath doctor")
    } else {
        Write-Host "  Claude Doctor: OK"
    }
} else {
    $ManualSteps.Add("Install Claude Code manually if needed: npm install -g @anthropic-ai/claude-code")
    $ManualSteps.Add("After install, run: claude doctor")
    $ManualSteps.Add("Authenticate Claude Code before selecting it in the app.")
}

if ($env:AGENTATION_ENABLED -and $env:AGENTATION_ENABLED.Trim() -ne "0") {
    $Warnings.Add("Current shell AGENTATION_ENABLED is not 0. Phase-1 packaging assumes 0.")
}

$gitAuthorName = ""
$gitAuthorEmail = ""
if ($gitCmd) {
    $gitAuthorName = (& $gitCmd config user.name 2>$null).Trim()
    $gitAuthorEmail = (& $gitCmd config user.email 2>$null).Trim()
}
if (-not $gitAuthorName -or -not $gitAuthorEmail) {
    $ManualSteps.Add("Set git config user.name and user.email if you want commits to succeed without prompts.")
}

$ManualSteps.Add("Enter Jira Base URL, Jira Email, Jira API Token, and JQL in the app.")
$ManualSteps.Add("Enter per-space GitHub tokens and local repo paths in the app.")
$ManualSteps.Add("Clone the real working repositories separately before mapping local paths.")

Write-Host ""
Write-Step "Summary"
if ($BlockingIssues.Count -eq 0) {
    Write-Host "  Status: OK"
} else {
    Write-Host "  Status: action required"
}

if ($Warnings.Count -gt 0) {
    Write-Host ""
    Write-Host "Warnings"
    foreach ($warning in $Warnings) {
        Write-Host "  - $warning"
    }
}

if ($BlockingIssues.Count -gt 0) {
    Write-Host ""
    Write-Host "Blocking issues"
    foreach ($issue in $BlockingIssues) {
        Write-Host "  - $issue"
    }
}

if ($ManualSteps.Count -gt 0) {
    Write-Host ""
    Write-Host "Manual steps"
    foreach ($step in $ManualSteps) {
        Write-Host "  - $step"
    }
}

if ($BlockingIssues.Count -gt 0) {
    exit 1
}
