"""ORC | Is it running, is it producing, is anything stuck?  One screen.

status.py answers "where does the research stand". This answers the different
question an owner actually has between sessions: is the machine alive right now,
and would I know if it were not.

Everything else in this project reports into a commit message, a JSON file or a
chat summary, none of which can be checked at a glance. So this reads the four
things that decide whether the loop is working and prints them together:

  MACHINE    the schedules -- cloud worker, local reasoning pass, watchdog,
             kernel review -- with when each last ran, what it returned, and
             when it fires next. Including whether a run is happening AS YOU
             READ THIS.
  RESEARCH   N, when it last grew, which families are open, which are closed,
             and how many cells clear every check.
  HEALTH     the things that stop the loop or make it lie: blocking findings,
             split close votes, staleness, and whether the kernel tests pass.

What "working" means here is worth stating plainly, because it is not what a
backtester usually means. This project's product is a MAP OF WHERE RULES BREAK.
Three families closed today and no cell has ever cleared every check. That is
the machine working, not failing. It would be failing if it produced a winner it
could not defend, or stopped and did not say so.

  python scripts/health.py            once
  python scripts/health.py --watch    every 30s until Ctrl-C
  python scripts/health.py --no-tests skip the 3-second suite

Exit code is the worst line on the screen: 0 all clear, 1 something to look at,
2 something is broken. So `python scripts/health.py --no-tests || echo check it`
works in a shell.

A local task showing "exited 1" is not necessarily broken. The reasoning pass
REFUSES to run while a high-severity finding is open, and refusing is the
behaviour that protects every number in the ledger. logs/reasoning_<date>.log
says which it was.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    sys.stdout.reconfigure(errors="replace")
except (AttributeError, OSError):                                  # pragma: no cover
    pass
sys.path.insert(0, str(Path(__file__).resolve().parent))

from orc import config, runstate                                   # noqa: E402

KST = timezone(timedelta(hours=9))
OK, WARN, BAD, DIM = "  ok  ", " WARN ", " BAD  ", "  --  "


def _ago(stamp: str | None) -> str:
    if not stamp:
        return "never"
    try:
        t = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return str(stamp)[:19]
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    d = datetime.now(timezone.utc) - t
    if d.days > 0:
        return f"{d.days}d {d.seconds // 3600}h ago"
    if d.seconds >= 3600:
        return f"{d.seconds // 3600}h {(d.seconds % 3600) // 60}m ago"
    return f"{max(d.seconds, 0) // 60}m ago"


def _load(name: str):
    p = config.REPORTS / name
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return None


def worker_state() -> list[tuple[str, str, str]]:
    """The cloud half, from the GitHub CLI.  Its cron is nominal: scheduled runs
    on a public repository are routinely delayed two to four hours, so 'next' is
    an estimate and lateness alone is not a fault."""
    try:
        r = subprocess.run(
            ["gh", "run", "list", "--limit", "6", "--json",
             "databaseId,status,conclusion,createdAt,workflowName,event"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=45, cwd=config.ORC_ROOT)
        runs = json.loads(r.stdout) if r.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        runs = None
    if runs is None:
        return [(DIM, "worker (GitHub Actions)",
                 "cannot reach the GitHub CLI; check `gh auth status`")]

    out = []
    live = [x for x in runs if x["status"] not in ("completed",)]
    for x in live:
        out.append((WARN, f"{x['workflowName']} #{x['databaseId']}",
                    f"RUNNING NOW, started {_ago(x['createdAt'])} "
                    f"(a full cycle takes ~40m)"))
    # orc-guard is here because a red one means the LAST PUSH went out on a
    # check nobody could confirm had run, and because twice on 2026-09-04 it
    # was pushed and not read: the first red run was a test of mine that only
    # passes on this workstation, and the same test then failed the cycle's own
    # gate step and stopped research for two hours. A gate whose verdict is not
    # on the screen the owner checks is a gate that reports to nobody.
    for wf in ("orc-cycle", "orc-guard", "orc-watchdog"):
        done = [x for x in runs if x["workflowName"] == wf and x["status"] == "completed"]
        if not done:
            out.append((DIM, wf, "no completed run in the last 6"))
            continue
        last = done[0]
        mark = OK if last["conclusion"] == "success" else BAD
        note = f"last {last['conclusion']} {_ago(last['createdAt'])}"
        if last["conclusion"] != "success":
            note += (f"  -> gh run view {last['databaseId']} --log-failed")
        out.append((mark, wf, note))
    return out


def local_tasks(tasks: list[dict] | None = None,
                queried: bool = False) -> list[tuple[str, str, str]]:
    """The workstation half.  It needs the machine awake; WakeToRun is set, but
    a powered-off machine still misses its slot and catches up later.

    The paths come first, and they are the row this screen used to be missing.
    A scheduled task stores an ABSOLUTE path: when the checkout moved on
    2026-09-03 the reasoning layer stopped launching entirely, Task Scheduler
    reported 0x8007010B, and this screen showed one yellow "last result
    2147942667" line among a dozen green ones.  A task that cannot find the
    repository is not a warning; nothing it is supposed to do can happen.
    """
    tasks = tasks if queried else runstate.local_tasks()
    if tasks is None:
        return [(DIM, "local schedules", "not queryable (not Windows, or no tasks)")]
    if not tasks:
        return [(BAD, "local schedules",
                 "no ORC* task registered -- the reasoning layer is the only "
                 "thing that proposes, and nothing will fire it. "
                 "python scripts/schedule.py --install")]

    problems = runstate.task_path_problems(tasks)
    out = []

    # The supervisor first, because it is the thing that is supposed to be
    # working RIGHT NOW. The three tasks below are how it gets started; this
    # row is whether it is running, and it is the only row on this screen that
    # answers the question the screen is named after.
    sup = runstate.supervisor()
    acts = runstate.activities(1)
    did = (f"last did {acts[0].get('action')} {runstate.ago(acts[0].get('utc'))}"
           if acts else "has never recorded an action")
    if sup.get("alive"):
        try:
            act, why = runstate.next_action()
        except Exception as exc:                                   # noqa: BLE001
            act, why = "unknown", f"{type(exc).__name__}: {exc}"
        out.append((OK, "supervisor (24h)",
                    f"alive, pid {sup['pid']}, heartbeat "
                    f"{runstate.ago(sup['heartbeat_utc'])}; {did}; "
                    f"next: {act} -- {why[:80]}"))
    elif sup.get("heartbeat_utc"):
        out.append((BAD, "supervisor (24h)",
                    f"DEAD -- heartbeat stopped "
                    f"{runstate.ago(sup['heartbeat_utc'])} (pid {sup['pid']}); "
                    f"{did}. Start-ScheduledTask -TaskName 'ORC Forever'"))
    else:
        out.append((BAD, "supervisor (24h)",
                    f"not running and no heartbeat; {did}. "
                    f"Start-ScheduledTask -TaskName 'ORC Forever'"))

    if problems:
        out.append((BAD, "schedule -> repository",
                    "; ".join(problems)
                    + "  -> python scripts/schedule.py --repair"))
    else:
        out.append((OK, "schedule -> repository",
                    f"every ORC task points at {config.ORC_ROOT}"))

    # Whether the gate is wired up on THIS machine, which is a question about a
    # checkout and not about the code -- so it belongs here and not in the
    # suite. A test asserting it took the first server-side gate run red: true
    # on the workstation, false in every fresh clone and on every CI runner.
    missing = [h for h in ("pre-commit", "commit-msg")
               if not (config.ORC_ROOT / ".git" / "hooks" / h).exists()]
    if missing:
        out.append((BAD, "git 훅",
                    f"{', '.join(missing)} 미설치 — 이 체크아웃에서는 커밋이 "
                    "검사 없이 통과합니다. python scripts/precommit.py --install"))
    else:
        out.append((OK, "git 훅",
                    "pre-commit(테스트·원장·새 파일) + commit-msg(테스트 약화·"
                    "동결 임계값·변경 예산) 설치됨"))
    for t in tasks:
        sev, note = runstate.task_result_note(t.get("result"))
        # A launch failure recorded against paths that are now correct is
        # history: LastTaskResult keeps the old code until the task fires
        # again.  Calling it BAD would send someone to fix what is fixed.
        if sev == "bad" and not problems:
            sev = "warn"
            note += " (paths are correct now; this clears on the next fire)"
        mark = {"ok": OK, "warn": WARN, "bad": BAD}[sev]
        out.append((mark, t["name"],
                    f"{note}; last {runstate.task_time(t.get('last'))}; "
                    f"next {runstate.task_time(t.get('next'))}"))
    return out


def research_state(tasks: list[dict] | None = None,
                   queried: bool = False) -> list[tuple[str, str, str]]:
    from orc.orchestrator.spec import closed_families, load_registry

    out = []
    # The durable verdict, from the same facts a briefing read hours from now
    # will see.  Everything below this line describes what the research HAS
    # done; this line says whether it is still doing any.
    try:
        a = runstate.activity(tasks=tasks if queried else None)
        # .get, not [], and every status listed. A new status used to make this
        # row read "KeyError: 'WORKING'" -- the screen reporting a fault in
        # itself at the exact moment the machine was finally working.
        mark = {runstate.RUNNING: OK, runstate.QUEUED: OK,
                runstate.WORKING: OK, runstate.IDLE: WARN,
                runstate.STALLED: WARN,
                runstate.STOPPED: BAD}.get(a["status"], WARN)
        out.append((mark, "loop", f"{a['status']} -- "
                    + " / ".join(a["reasons"])[:160]))
    except Exception as exc:                                       # noqa: BLE001
        out.append((WARN, "loop", f"{type(exc).__name__}: {exc}"))
    try:
        from orc.ledger.trials import Ledger
        with Ledger() as led:
            n, newest = led.total_trials(), led.newest_trial_utc()
        grew = _ago(newest)
        stale = newest is None or (
            datetime.now(timezone.utc) - datetime.fromisoformat(
                newest.replace("Z", "+00:00")).replace(
                    tzinfo=timezone.utc) if newest else timedelta(0)) > timedelta(days=2)
        out.append((WARN if stale else OK, "ledger",
                    f"N = {n}; a question nobody had asked was last answered {grew}"))
    except Exception as exc:                                       # noqa: BLE001
        out.append((BAD, "ledger", f"cannot open: {type(exc).__name__}: {exc}"))

    try:
        # load_registry() narrates each closed family it skips, which belongs in
        # a cycle log and not on a status screen.
        import contextlib, io
        with contextlib.redirect_stdout(io.StringIO()):
            openf = [h.hypothesis_id for h in load_registry()]
        closed = closed_families()
    except Exception as exc:                                       # noqa: BLE001
        return out + [(BAD, "registry", f"{type(exc).__name__}: {exc}")]

    out.append((OK if openf else WARN, "open families",
                ", ".join(openf) if openf else
                "NONE -- every registered mechanism is closed, so the next "
                "reasoning pass must name a new one or the loop has nothing to do"))
    out.append((OK, "closed and answered",
                ", ".join(f"{k} ({v.get('family')})" for k, v in sorted(closed.items()))
                or "none yet"))

    # The number the whole apparatus exists to produce, and it is allowed to be
    # zero: a map of where rules break is the deliverable, not a winner.
    cleared, judged = 0, 0
    try:
        from orc.orchestrator.verdict import survivors
        for hid in openf:
            rep = _load(f"{hid}_SURFACE.json")
            if rep is None:
                continue
            judged += len(rep.get("surfaces", {}))
            cleared += len(list(survivors(rep)))
    except Exception:                                              # noqa: BLE001
        pass
    out.append((OK, "cells clearing every check",
                f"{cleared} of {judged} reported cells. Zero is a normal, "
                "publishable result here -- FAIL is the product"))

    # Where the run leaves the owner's stop condition. On one screen because
    # the alternative is three files nobody opens between sessions.
    tgt = _load("TARGET.json") or {}
    if tgt:
        t = tgt.get("target", {})
        best = tgt.get("best_cagr") or {}
        near = f", MDD 25% 이내 최고 {near_c['cagr']:+.1%}" if (
            near_c := tgt.get("best_cagr_within_drawdown")) else ""
        out.append((OK if tgt.get("state") == "NO_CANDIDATE" else WARN,
                    "종료 조건",
                    f"{tgt.get('state')} — 목표 CAGR {t.get('cagr', 0):.0%} / MDD "
                    f"{t.get('max_drawdown', 0):.0%}; 최고 "
                    f"{best.get('cagr', float('nan')):+.1%} "
                    f"(MDD {best.get('max_drawdown', float('nan')):.0%})" + near))

    # A surviving mutation is the one bad state in this whole screen that makes
    # nothing else look wrong: the suite is green, the code is correct, and a
    # defect of that shape would not be noticed.
    mut = _load("MUTATION.json") or {}
    if mut:
        n_s = len(mut.get("survived") or [])
        aged = _ago(mut.get("generated_utc"))
        out.append((BAD if n_s else OK, "뮤테이션 게이트",
                    (f"{n_s}개 결함을 테스트가 못 잡음 "
                     f"({', '.join(mut['survived'][:3])}) — 코드가 아니라 "
                     "테스트의 구멍입니다" if n_s else
                     f"{mut.get('killed')}/{mut.get('mutations')} 결함 모두 "
                     f"테스트가 잡음") + f"; 마지막 실행 {aged}"))
    else:
        out.append((WARN, "뮤테이션 게이트",
                    "한 번도 실행되지 않음 — python scripts/mutation.py"))
    return out


def health_state(run_tests: bool) -> list[tuple[str, str, str]]:
    out = []
    try:
        import findings as ledger
        blocking = ledger.blocking()
        allf = ledger.load()["findings"]
        openn = sum(1 for f in allf.values() if f["status"] == "open")
        out.append((BAD if blocking else OK, "blocking findings",
                    (f"{len(blocking)} HIGH finding(s) open -- every cycle "
                     f"refuses until fixed: "
                     + ", ".join(f['id'] for f in blocking)) if blocking else
                    f"none. {openn} open at medium/low, {len(allf)} recorded total"))
    except Exception as exc:                                       # noqa: BLE001
        out.append((WARN, "findings", f"{type(exc).__name__}: {exc}"))

    votes = (_load("CLOSE_VOTES.json") or {}).get("families") or {}
    splits = [k for k, v in votes.items() if v.get("decision") == "SPLIT"]
    out.append((WARN if splits else OK, "close votes",
                f"SPLIT on {', '.join(splits)} -- providers disagree about "
                f"whether a pre-registered clause applies; nothing was closed"
                if splits else "no disagreement between providers"))

    try:
        import notify_issue
        quiet = notify_issue.watchdog_message()
        out.append((WARN if quiet else OK, "staleness",
                    "the watchdog would raise: " + quiet[1].splitlines()[2][:90]
                    if quiet else "nothing has gone quiet"))
    except Exception as exc:                                       # noqa: BLE001
        out.append((WARN, "staleness", f"{type(exc).__name__}: {exc}"))

    if run_tests:
        r = subprocess.run([sys.executable, "-m", "pytest", "tests", "-q"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", cwd=config.ORC_ROOT)
        tail = [l for l in (r.stdout or "").splitlines() if "passed" in l or "failed" in l]
        out.append((OK if r.returncode == 0 else BAD, "kernel tests",
                    tail[-1].strip() if tail else "no result"))
        out.append((OK, "", "if the two evaluators ever disagree that test fails "
                            "and every result in the project is void"))
    return out


def render(run_tests: bool = True) -> int:
    now = datetime.now(KST)
    print(f"\nORC health   {now:%Y-%m-%d %H:%M} KST   ({now.astimezone(timezone.utc):%H:%M}Z)")
    worst = 0
    # Queried once: every ORC* task with its action paths.  Two callers need it
    # and the PowerShell round trip is the slowest thing on this screen.
    tasks = runstate.local_tasks()
    for title, rows in (("MACHINE -- is it running",
                         worker_state() + local_tasks(tasks, True)),
                        ("RESEARCH -- is it producing",
                         research_state(tasks, True)),
                        ("HEALTH -- would I know if it broke", health_state(run_tests))):
        print(f"\n{title}")
        for mark, name, note in rows:
            worst = max(worst, {BAD: 2, WARN: 1}.get(mark, 0))
            print(f"  [{mark}] {name:26s} {note}")
    print("\nnext: python scripts/status.py   (the research itself, family by family)")
    print("      gh run watch <id>          (a live run, bar by bar)\n")
    return worst


def main(argv: list[str]) -> int:
    run_tests = "--no-tests" not in argv
    if "--watch" not in argv:
        return render(run_tests)
    try:
        while True:
            print("\033[2J\033[H", end="")
            render(run_tests)
            print("watching; Ctrl-C to stop")
            time.sleep(30)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
