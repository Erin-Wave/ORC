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

    # Run even when the evidence gate says there is nothing new to reason from.
    # Only for a deliberate manual re-run; see the gate below for why that is
    # not the default.
    [switch]$Force
)

$ErrorActionPreference = "Stop"

# The gate and the notifier answer in Korean, and this console is cp949.  Python
# then encodes the reason with replacement characters, PowerShell decodes those
# bytes as something else again, and the log line arrives as mojibake -- which
# for a log whose entire job is to say why a cycle did not run is the same as
# having no line at all.  Fixing it at both ends: Python emits UTF-8, and this
# session reads UTF-8.
$env:PYTHONIOENCODING = "utf-8"
try {
    [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
    $OutputEncoding = [Console]::OutputEncoding
} catch {
    # A redirected or absent console refuses the assignment.  The cycle is the
    # point, not the transcript.
}

$RepoRoot = Split-Path -Parent $PSScriptRoot
$LogDir   = Join-Path $RepoRoot "logs"

if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
$Log = Join-Path $LogDir ("reasoning_" + (Get-Date -Format "yyyy-MM-dd") + ".log")

function Write-Log($msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    # Add-Content is a cmdlet, so under $ErrorActionPreference = "Stop" a
    # transient failure -- the file held open by something else reading it, a
    # sharing violation -- is TERMINATING, and it would take the cycle down
    # from inside the function whose only job is to describe the cycle.  On
    # 2026-09-03 a run reached the end of its pipeline and left no log line
    # for it at all.  The transcript is never worth the run.
    try {
        Add-Content -Path $Log -Value $line -Encoding utf8 -ErrorAction Stop
    } catch {
        # Retried once after a moment, then given up on.  Silently: a warning
        # here would go to a console that does not exist.
        Start-Sleep -Milliseconds 200
        try { Add-Content -Path $Log -Value $line -Encoding utf8 -ErrorAction Stop } catch { }
    }
}

function Invoke-Native($Tag, [scriptblock]$Cmd) {
    # Every native call in this script goes through here, and the reason is a
    # PowerShell 5.1 rule with teeth: merging a native command's stderr into
    # the success stream with 2>&1 wraps each line in a NativeCommandError, and
    # under $ErrorActionPreference = "Stop" that error is TERMINATING.
    #
    # `git pull` writes "From https://github.com/..." to stderr on every fetch
    # that actually brings something down.  So this script died, silently and
    # without a single log line past "cycle start", on exactly the cycles that
    # had new results to reason about.  The ones that survived were the ones
    # where git printed "Already up to date." on stdout and wrote nothing to
    # stderr -- which is every run in the logs up to 2026-09-03, because the
    # workstation had always been the last one to push.  A latent defect whose
    # trigger was the worker getting there first.
    #
    # Streamed, not collected.  Assigning the whole run to a variable first
    # would hold every line until the process exits, and the pipeline step here
    # makes eight to ten model calls over tens of minutes -- so the log, whose
    # entire job is to say what is happening, would stay empty for the whole
    # run and then arrive at once.  Each line is logged as it comes and also
    # passed on, so a caller can still capture the output.
    #
    # $LASTEXITCODE is global, so the caller reads it exactly as before.
    & { $ErrorActionPreference = "Continue"; & $Cmd 2>&1 } |
        ForEach-Object { Write-Log "${Tag}: $_"; $_ }
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

# The report this layer reasons from is written by the Actions worker, so the
# local checkout is stale until we pull.  Reasoning from a stale report would
# re-propose hypotheses the worker has already answered.
Invoke-Native "git" { git pull --rebase --autostash } | Out-Null
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
    Invoke-Native "push" { git push } | Out-Null
}

# The worker's results arrived with that pull, so this is the freshest view of
# them there will be today.  Check before reasoning, not after: the reasoning
# pass writes hypotheses, not results, and would leave the report unchanged.
$newsText = Invoke-Native "NEWS" { & python "$PSScriptRoot\notify.py" }
if ($LASTEXITCODE -eq 0) {
    Show-Toast "ORC" ($newsText -join "`n")
    Add-Content -Path (Join-Path $LogDir "NEWS.md") -Encoding utf8 `
        -Value ("## {0}`n{1}`n" -f (Get-Date -Format "yyyy-MM-dd HH:mm"), ($newsText -join "`n"))
} else {
    Write-Log "no news"
}

# The gate, and it is deliberately not a calendar day.
#
# What must never happen twice is two registrations against the SAME evidence:
# pre-registration is irreversible and every trial counts toward N, so a
# duplicate batch permanently inflates the multiple-testing correction.  A
# date was a bad proxy for that in both directions.  It permitted a second
# pass over an unchanged report the moment midnight passed, and - the failure
# that actually cost this project a day - it blocked every later attempt after
# the morning one was refused, whether the refusal was a blocking finding, a
# dead network or a directory that had moved.
#
# runstate.reasoning_due() asks the question directly: is there something new
# to reason from, and is the previous batch already answered.  That makes it
# safe to fire four times a day, which is why schedule.py sets four slots.
if (-not $Force) {
    Invoke-Native "gate" { & python -m orc.runstate --due } | Out-Null
    $gateRc = $LASTEXITCODE
    if ($gateRc -eq 10) {
        Write-Log "=== cycle skipped (nothing new to reason from) ==="
        exit 0
    }
    if ($gateRc -ne 0) {
        Write-Log "ABORT: the evidence gate could not be evaluated (exit $gateRc)"
        exit 1
    }
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
    Invoke-Native "reason" { & python $pipeline } | Out-Null
    $rc = $LASTEXITCODE
}

if ($rc -ne 0) {
    # Deliberately no stamp: a failed cycle should be retried, not skipped, and
    # with the evidence gate the retry happens at the next slot instead of
    # tomorrow.
    Write-Log "=== cycle FAILED (exit $rc) ==="
    exit $rc
}

# Records WHAT this pass was made against, not that a day was spent.  The next
# fire compares its own fingerprint to this one and skips only if nothing has
# moved since.
Invoke-Native "stamp" { & python -m orc.runstate --stamp } | Out-Null

$after = (git rev-parse --short HEAD)
if ($after -eq $head) {
    Write-Log "no commit produced this cycle"
} else {
    Write-Log "committed $head -> $after"
}
Write-Log "=== cycle done ==="
