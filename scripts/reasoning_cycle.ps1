# ORC | Local reasoning cycle.
#
# The reasoning layer that decides what to ask next.  It normally runs as a
# scheduled cloud routine, but this account's Claude organization has the
# GitHub connector switched off, so cloud routines cannot reach the repository
# at all.  This script is the local stand-in: same prompt, same output, run by
# Windows Task Scheduler instead of Anthropic's cloud.  The trade is that the
# workstation has to be awake at the scheduled minute.
#
# It writes hypotheses to configs/queue/ and pushes.  It never evaluates
# anything - the GitHub Actions worker does that within six hours.

param(
    # Overridable so the plumbing can be smoke-tested with a harmless prompt
    # without registering a hypothesis.  Pre-registration is irreversible, so
    # there is no such thing as a throwaway real run.
    [string]$PromptFile,

    # Run even if today's cycle already happened.  Only for a deliberate manual
    # re-run; see the once-a-day guard below for why that is not the default.
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Claude   = Join-Path $env:USERPROFILE ".local\bin\claude.exe"
$LogDir   = Join-Path $RepoRoot "logs"

if ($PromptFile) { $Prompt = $PromptFile }
else { $Prompt = Join-Path $PSScriptRoot "reasoning_prompt.txt" }

# Frozen before any result was seen: the reasoning layer may read and write the
# working tree and talk to git, and nothing else.  A scheduled job with a free
# shell is a liability, and this one has no reason to need one.
$AllowedTools = @("Read", "Glob", "Grep", "Write", "Edit", "Bash(git *)")

if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
$Log = Join-Path $LogDir ("reasoning_" + (Get-Date -Format "yyyy-MM-dd") + ".log")

function Write-Log($msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Add-Content -Path $Log -Value $line -Encoding utf8
}

Set-Location $RepoRoot
Write-Log "=== cycle start ==="

# Once a day, no matter how many times the scheduler fires.  A missed 08:25
# start is retried after boot, a failed run is retried 15 minutes later, and a
# human can launch the task by hand - any two of those landing on the same day
# would register two batches of hypotheses.  Registration is irreversible and
# every trial counts toward N, so a duplicate run permanently inflates the
# multiple-testing correction.  Cheaper to refuse.
$Stamp = Join-Path $LogDir ".last_cycle"
$today = Get-Date -Format "yyyy-MM-dd"
if ((-not $Force) -and (Test-Path $Stamp) -and ((Get-Content $Stamp -Raw).Trim() -eq $today)) {
    Write-Log "already ran today ($today); nothing to do"
    Write-Log "=== cycle skipped ==="
    exit 0
}

# The report this layer reasons from is written by the Actions worker, so the
# local checkout is stale until we pull.  Reasoning from a stale report would
# re-propose hypotheses the worker has already answered.
git pull --rebase --autostash 2>&1 | ForEach-Object { Write-Log "git: $_" }
if ($LASTEXITCODE -ne 0) {
    Write-Log "ABORT: git pull failed ($LASTEXITCODE). Refusing to reason from a stale report."
    exit 1
}

$head = (git rev-parse --short HEAD)
Write-Log "head $head"

$promptText = Get-Content -Raw $Prompt
$promptText | & $Claude -p --model claude-opus-5 --allowedTools $AllowedTools 2>&1 |
    ForEach-Object { Write-Log "claude: $_" }
$rc = $LASTEXITCODE

if ($rc -ne 0) {
    # Deliberately no stamp: a failed cycle should be retried, not skipped.
    Write-Log "=== cycle FAILED (exit $rc) ==="
    exit $rc
}

Set-Content -Path $Stamp -Value $today -Encoding utf8

$after = (git rev-parse --short HEAD)
if ($after -eq $head) {
    Write-Log "no commit produced this cycle"
} else {
    Write-Log "committed $head -> $after"
}
Write-Log "=== cycle done ==="
