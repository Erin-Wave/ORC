"""ORC | The local schedule, checked against the repository it points at.

The reasoning layer is the only thing in this project that proposes a new
question.  It runs from Windows Task Scheduler because this account's Claude
organization has the GitHub connector switched off, so a cloud routine cannot
reach the repository at all.  That trade has one failure mode nothing was
watching:

    the tasks store an ABSOLUTE path.  The checkout moved from D:\\Project\\ORC
    to D:\\Project\\harness\\invest\\ORC on 2026-09-03, and from that moment
    Task Scheduler returned 0x8007010B -- "the directory name is invalid" --
    without ever launching the script.  The GitHub worker kept firing every six
    hours, kept writing a report and kept committing, so health.py, status.py
    and the briefing all stayed green while the queue drained to empty and no
    new question was asked for the rest of the day.

A path in a registered task is a claim about where this repository lives, and
this project's rule is that a claim must be backed by something that fails when
it is false.  So:

  --check     compares every ORC* task's script and start-in folder against
              THIS checkout and exits 2 on a mismatch.  Run by health.py, and
              by tests/test_runstate.py against fixtures so the comparison
              itself is covered on a machine with no Task Scheduler at all.
  --repair    rewrites just the action paths of the existing tasks, leaving
              triggers and settings exactly as they were.  The minimal fix
              after a move.
  --cadence   sets the reasoning task's daily triggers to the four documented
              slots.  Separate from --repair because changing WHEN research is
              asked for is a decision, and repairing a path is not.
  --install   registers both tasks from scratch on a fresh machine.

Nothing here needs elevation: the tasks run interactively as the logged-in
user, which is also why they are launched through wscript.exe -- see
reasoning_cycle_hidden.vbs for why a console window must never be created.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    sys.stdout.reconfigure(errors="replace")
except (AttributeError, OSError):                                  # pragma: no cover
    pass

from orc import config, runstate                                   # noqa: E402

ROOT = config.ORC_ROOT

REASONING_TASK = "ORC Reasoning Cycle"
REVIEW_TASK = "ORC Kernel Review"
FOREVER_TASK = "ORC Forever"

# 35 minutes before each orc-cycle slot (03:00 / 09:00 / 15:00 / 21:00 KST,
# from `cron: "0 */6 * * *"` in UTC).  A hypothesis registered at :25 is
# collected by the worker 35 minutes later; miss the slot and it waits six
# hours.  Four slots rather than one because the gate is now
# runstate.reasoning_due(), which refuses a pass that has nothing new to read.
# The old single 08:25 slot meant a day whose morning pass was refused - by a
# blocking finding, by a dead network, by a moved directory - asked nothing at
# all for twenty-four hours.
#
# The times live in runstate because a briefing rendered on the Linux worker
# has no Task Scheduler to ask and still has to say when the next question is
# due.  This module is the only thing allowed to APPLY them.
REASONING_SLOTS_KST = runstate.REASONING_SLOTS_KST

# Weekly adversarial read of the evaluation kernel.  Sunday morning, offset
# from every cycle slot so it reports on a settled tree.
REVIEW_SLOT_KST = ("Sunday", "09:30")

TASKS = {
    FOREVER_TASK: "scripts/forever_hidden.vbs",
    REASONING_TASK: "scripts/reasoning_cycle_hidden.vbs",
    REVIEW_TASK: "scripts/kernel_review_hidden.vbs",
}

# The supervisor is the thing that actually runs 24 hours: every tick it decides
# what the most useful thing to do is, and only sometimes is that a new
# hypothesis.  It is a long-running process, so its triggers are not a cadence
# but three ways of making sure one copy is always alive:
#
#   at logon and at startup   a reboot brings it back with no human
#   hourly                    a watchdog re-fire.  MultipleInstances IgnoreNew
#                             leaves a live copy alone, and forever.py also
#                             holds a heartbeat lock -- so the hourly trigger is
#                             a no-op on a healthy supervisor and the restart on
#                             a dead one.
#
# The reasoning task's four daily slots stay registered on purpose: they are the
# fallback for a supervisor that cannot start at all, which is the state this
# session was spent recovering from.  A double fire is harmless because the
# evidence gate makes whichever runs second skip.
FOREVER_WATCHDOG_MINUTES = 60

# Hours a task may run before Task Scheduler kills it.  Zero means no ceiling,
# and only the supervisor gets it: three hours is right for a reasoning pass,
# and on a process meant to live until the machine stops it would be a kill
# mid-action every three hours for the life of the project.
TASK_HOURS = {FOREVER_TASK: 0}
DEFAULT_TASK_HOURS = 3


def _ps(script: str, timeout: int = 120) -> tuple[int, str, str]:
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                        "-Command", script], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


# ---------------------------------------------------------------------------
def check(tasks: list[dict] | None = None) -> tuple[int, list[str]]:
    """(exit code, lines).  2 when a task cannot find this repository."""
    lines: list[str] = []
    tasks = runstate.local_tasks() if tasks is None else tasks
    if tasks is None:
        return 0, ["작업 스케줄러를 조회할 수 없습니다 (Windows가 아니거나 "
                   "권한 없음) — 로컬 스케줄 검사를 건너뜁니다"]
    if not tasks:
        return 2, [f"ORC* 작업이 하나도 등록돼 있지 않습니다. "
                   f"`python scripts/schedule.py --install` 로 등록하십시오"]

    problems = runstate.task_path_problems(tasks, ROOT)
    stale = False
    for t in tasks:
        sev, note = runstate.task_result_note(t.get("result"))
        # A launch failure recorded against paths that are now correct is
        # history, not a fault: LastTaskResult keeps the code from before the
        # repair until the task fires again.  Saying BAD here would send
        # someone to fix a thing that is already fixed.
        if sev == "bad" and not problems:
            sev, stale = "warn", True
            note += " — 경로는 지금 정상이므로 이 코드는 수정 이전의 기록이고, 다음 발화에서 지워집니다"
        mark = {"ok": "ok  ", "warn": "WARN", "bad": "BAD "}[sev]
        lines.append(f"[{mark}] {t.get('name')}  {note}")
        lines.append(f"         start-in {t.get('workdir')}")
        lines.append(f"         last {t.get('last')}   next {t.get('next')}")
    missing = [name for name in TASKS
               if not any(t.get("name") == name for t in tasks)]
    for name in missing:
        lines.append(f"[BAD ] {name}  등록돼 있지 않습니다")
    for p in problems:
        lines.append(f"[BAD ] 경로 불일치: {p}")
    if problems or missing:
        lines.append("")
        lines.append(f"이 저장소: {ROOT}")
        lines.append("고치기: python scripts/schedule.py --repair")
        return 2, lines
    lines.append("")
    lines.append(f"모든 ORC 작업이 이 저장소({ROOT})를 가리킵니다")
    return (1 if stale else 0), lines


def repair() -> int:
    """Re-point the existing tasks' actions at this checkout.  Triggers and
    settings are untouched: a moved repository is a path problem and nothing
    else, and rewriting a schedule to fix a path would hide the difference."""
    rc_all = 0
    for name, rel in TASKS.items():
        target = ROOT / rel
        if not target.exists():
            print(f"[skip] {name}: {target} 가 없습니다")
            rc_all = max(rc_all, 2)
            continue
        script = (
            f'$ErrorActionPreference = "Stop"; '
            f'$t = Get-ScheduledTask -TaskName "{name}" '
            f'-ErrorAction SilentlyContinue; '
            f'if ($null -eq $t) {{ Write-Output "ABSENT"; exit 3 }}; '
            f'$a = New-ScheduledTaskAction -Execute "wscript.exe" '
            f'-Argument \'"{target}"\' -WorkingDirectory "{ROOT}"; '
            f'Set-ScheduledTask -TaskName "{name}" -Action $a | Out-Null; '
            f'Write-Output "REPOINTED"'
        )
        rc, out, err = _ps(script)
        if rc == 0 and "REPOINTED" in out:
            print(f"[ok]   {name} -> {target}")
        elif "ABSENT" in out:
            print(f"[--]   {name}: 등록돼 있지 않습니다 (--install 필요)")
            rc_all = max(rc_all, 2)
        else:
            print(f"[fail] {name}: {err or out}")
            rc_all = max(rc_all, 2)
    return rc_all


def cadence() -> int:
    """Set the reasoning task's daily triggers to REASONING_SLOTS_KST.

    Firing four times a day would once have been reckless: registration is
    irreversible and every trial raises N.  It is safe only because the guard
    moved from a calendar date to runstate.reasoning_due(), which refuses a
    pass while the queue still holds an unanswered question and refuses one
    whose evidence fingerprint has not changed.  Four fires a day therefore buy
    a faster response to new results, never a second batch on the same report.
    """
    trigs = "; ".join(
        f'(New-ScheduledTaskTrigger -Daily -At "{s}")' for s in REASONING_SLOTS_KST)
    script = (
        f'$ErrorActionPreference = "Stop"; '
        f'$t = Get-ScheduledTask -TaskName "{REASONING_TASK}" '
        f'-ErrorAction SilentlyContinue; '
        f'if ($null -eq $t) {{ Write-Output "ABSENT"; exit 3 }}; '
        f'$ts = @({trigs}); '
        f'foreach ($x in $ts) {{ $x.Enabled = $true }}; '
        f'Set-ScheduledTask -TaskName "{REASONING_TASK}" -Trigger $ts | Out-Null; '
        f'Write-Output "TRIGGERS SET"'
    )
    rc, out, err = _ps(script)
    if rc == 0 and "TRIGGERS SET" in out:
        print(f"[ok]   {REASONING_TASK} 발화 시각 "
              f"{', '.join(REASONING_SLOTS_KST)} KST")
        return 0
    print(f"[fail] {REASONING_TASK}: {err or out}")
    return 2


def install() -> int:
    """Register both tasks from scratch.  Settings are the ones MANUAL_SETUP.md
    documents and the ones the hand-registered tasks actually carried:
    StartWhenAvailable so a missed slot is caught up after boot, WakeToRun,
    two retries fifteen minutes apart, a three-hour ceiling because the pass
    makes eight to ten judgement calls, and IgnoreNew so an overlapping fire
    cannot start a second pass."""
    rc_all = 0
    for name, rel in TASKS.items():
        target = ROOT / rel
        if not target.exists():
            print(f"[skip] {name}: {target} 가 없습니다")
            rc_all = max(rc_all, 2)
            continue
        if name == FOREVER_TASK:
            # -RepetitionDuration is OMITTED on purpose.  The documented way to
            # say "repeat forever" is [TimeSpan]::MaxValue, and on this build
            # that serialises to P99999999DT23H59M59S, which Task Scheduler's
            # own XML schema then rejects with 0x80041318 -- so the task simply
            # does not register.  Leaving the duration empty is what the
            # scheduler reads as indefinite.
            #
            # -AtStartup is NOT here and cannot be: a boot trigger fires before
            # any logon, so registering one needs elevation this account does
            # not have.  -AtLogOn covers a reboot anyway, because the
            # supervisor runs in the user's own session -- which is also why it
            # is launched through wscript.
            #
            # -User is not decoration either.  An unscoped -AtLogOn means "any
            # user logs on", and registering THAT also needs elevation:
            # probed on this machine, unscoped fails with 0x80070005 "Access is
            # denied" and the scoped form registers.
            trigs = ('(New-ScheduledTaskTrigger -AtLogOn -User "$env:USERNAME"); '
                     "(New-ScheduledTaskTrigger -Once -At (Get-Date) "
                     "-RepetitionInterval (New-TimeSpan -Minutes "
                     f"{FOREVER_WATCHDOG_MINUTES}))")
        elif name == REASONING_TASK:
            trigs = "; ".join(f'(New-ScheduledTaskTrigger -Daily -At "{s}")'
                              for s in REASONING_SLOTS_KST)
        else:
            day, at = REVIEW_SLOT_KST
            trigs = (f'(New-ScheduledTaskTrigger -Weekly '
                     f'-DaysOfWeek {day} -At "{at}")')
        hours = TASK_HOURS.get(name, DEFAULT_TASK_HOURS)
        script = (
            f'$ErrorActionPreference = "Stop"; '
            f'$a = New-ScheduledTaskAction -Execute "wscript.exe" '
            f'-Argument \'"{target}"\' -WorkingDirectory "{ROOT}"; '
            f'$ts = @({trigs}); '
            f'$s = New-ScheduledTaskSettingsSet -StartWhenAvailable '
            f'-WakeToRun -MultipleInstances IgnoreNew '
            f'-ExecutionTimeLimit (New-TimeSpan -Hours {hours}) '
            f'-RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 15); '
            f'$p = New-ScheduledTaskPrincipal -UserId "$env:USERNAME" '
            f'-LogonType Interactive -RunLevel Limited; '
            f'Register-ScheduledTask -TaskName "{name}" -Action $a '
            f'-Trigger $ts -Settings $s -Principal $p -Force | Out-Null; '
            f'Write-Output "REGISTERED"'
        )
        rc, out, err = _ps(script)
        if rc == 0 and "REGISTERED" in out:
            print(f"[ok]   {name} 등록: {target}")
        else:
            print(f"[fail] {name}: {err or out}")
            rc_all = max(rc_all, 2)
    return rc_all


def main(argv: list[str]) -> int:
    if "--repair" in argv:
        rc = repair()
        print()
        code, lines = check()
        print("\n".join(lines))
        return max(rc, code)
    if "--cadence" in argv:
        return cadence()
    if "--install" in argv:
        rc = install()
        print()
        code, lines = check()
        print("\n".join(lines))
        return max(rc, code)
    if "--json" in argv:
        print(json.dumps({"root": str(ROOT), "tasks": runstate.local_tasks(),
                          "problems": runstate.task_path_problems()},
                         indent=2, ensure_ascii=False, default=str))
        return 0
    code, lines = check()
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
