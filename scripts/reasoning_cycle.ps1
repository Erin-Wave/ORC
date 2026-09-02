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
    # Run the plumbing - pull, news, toast, stamp - without the pipeline, so the
    # scheduled path can be tested end to end without proposing anything.
    # Pre-registration is irreversible, so there is no throwaway real run.
    [switch]$SkipPipeline,

    # Run even if today's cycle already happened.  Only for a deliberate manual
    # re-run; see the once-a-day guard below for why that is not the default.
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$LogDir   = Join-Path $RepoRoot "logs"

if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
$Log = Join-Path $LogDir ("reasoning_" + (Get-Date -Format "yyyy-MM-dd") + ".log")

function Write-Log($msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Add-Content -Path $Log -Value $line -Encoding utf8
}

function Show-Toast($title, $text) {
    # A desktop toast, with no module to install.  It borrows PowerShell's own
    # registered application id because a toast raised without one is accepted
    # and then silently never drawn - which for a notifier is the worst of both
    # worlds.  Failure here must never take the cycle down with it: the point
    # of the run is the research, not the announcement.
    try {
        [void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime]
        $xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent(
            [Windows.UI.Notifications.ToastTemplateType]::ToastText02)
        $nodes = $xml.GetElementsByTagName("text")
        [void]$nodes.Item(0).AppendChild($xml.CreateTextNode($title))
        [void]$nodes.Item(1).AppendChild($xml.CreateTextNode($text))
        $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
        $appId = "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"
        [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show($toast)
    } catch {
        Write-Log "toast failed: $($_.Exception.Message)"
    }
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

# A previous cycle may have committed and failed to push -- the network was
# down, the token had expired.  Those hypotheses are registered locally and the
# worker collects from the remote, so until this succeeds they are questions
# nobody will ever answer.  Pushing is not retried inside the reasoning pass,
# because a retry there would register a second batch against the same report.
$pending = (git rev-list --count "@{u}..HEAD" 2>$null)
if ($LASTEXITCODE -eq 0 -and [int]$pending -gt 0) {
    Write-Log "$pending commit(s) never reached the remote; pushing before reasoning"
    git push 2>&1 | ForEach-Object { Write-Log "push: $_" }
}

# The worker's results arrived with that pull, so this is the freshest view of
# them there will be today.  Check before reasoning, not after: the reasoning
# pass writes hypotheses, not results, and would leave the report unchanged.
$newsText = & python "$PSScriptRoot\notify.py" 2>&1
if ($LASTEXITCODE -eq 0) {
    foreach ($line in $newsText) { Write-Log "NEWS: $line" }
    Show-Toast "ORC" ($newsText -join "`n")
    Add-Content -Path (Join-Path $LogDir "NEWS.md") -Encoding utf8 `
        -Value ("## {0}`n{1}`n" -f (Get-Date -Format "yyyy-MM-dd HH:mm"), ($newsText -join "`n"))
} else {
    Write-Log "no news"
}

# The pipeline orchestrates several model calls -- propose, adversary,
# mechanism, surfaces, post-mortem -- so it is driven from Python rather than
# from inside one session. A session whose tools are restricted to reading and
# writing cannot spawn the adversary that is supposed to judge it.
if ($SkipPipeline) {
    Write-Log "pipeline skipped by request"
    $rc = 0
} else {
    $pipeline = Join-Path $PSScriptRoot "reasoning.py"
    & python $pipeline 2>&1 | ForEach-Object { Write-Log "reason: $_" }
    $rc = $LASTEXITCODE
}

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
