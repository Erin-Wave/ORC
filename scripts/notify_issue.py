"""ORC | What the loop says when nobody is at the workstation.

notify.py decides what counts as news. The local cycle then raises a desktop
toast and appends to logs/NEWS.md -- both of which are invisible when the
machine is asleep, which is most of the time and exactly when an unattended
loop needs to be able to speak.

The worker runs in the cloud, so it can. A GitHub issue is the only channel
that reaches a phone with no new service, no secret and no bill: the repository
owner is already notified by email and through the GitHub app. This prints the
title and body for that issue and says, by its exit code, whether there is
anything worth saying at all.

The message that matters most is not a result. It is the loop announcing that
it has STOPPED: an unaddressed high-severity finding makes both the worker and
the reasoning pass refuse, and they keep refusing every six hours until a human
fixes it or records a decision. findings.py keeps fixing manual on purpose --
an agent that could patch the evaluators could also quietly change what a
result means -- so a block that nobody hears about is a loop that has quietly
retired.

  python scripts/notify_issue.py            news from reports/NEWS.json
  python scripts/notify_issue.py --blocked  the cycle refused or crashed

exit 0  there is something to say, on stdout as "title\\n---\\nbody"
exit 1  nothing to say
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    sys.stdout.reconfigure(errors="replace")
except (AttributeError, OSError):                                  # pragma: no cover
    pass

from orc import config                                             # noqa: E402

SEP = "\n---\n"


def _run_url() -> str:
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    if not (repo and run_id):
        return "(no run url; not running in Actions)"
    return f"{server}/{repo}/actions/runs/{run_id}"


def blocked_message() -> tuple[str, str]:
    """The loop has stopped itself. Say what is holding it and how to release it."""
    lines = [
        "The cycle did not complete, so nothing was evaluated and nothing was "
        "committed. N is unchanged.",
        "",
    ]
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import findings as ledger
        blocking = ledger.blocking()
    except Exception:                                              # noqa: BLE001
        blocking = []

    if blocking:
        lines.append(f"**{len(blocking)} high-severity finding(s) are holding the "
                     "loop.** Both the worker and the reasoning pass refuse to run "
                     "on a kernel a review has condemned, and they will keep "
                     "refusing -- every six hours, indefinitely -- until each one "
                     "is fixed or a decision is recorded on it.")
        lines.append("")
        for f in blocking:
            lines.append(f"- `{f['id']}` {f.get('file')}:{f.get('line')}")
            lines.append(f"  {' '.join(str(f.get('what', '')).split())[:400]}")
        lines += [
            "",
            "Fixing is deliberately manual: an agent that could patch the "
            "evaluators could also quietly change what a result means. To fix, or "
            "to decide not to:",
            "",
            "```",
            "python scripts/findings.py                       # what is open",
            "python scripts/findings.py fixed <id>",
            "python scripts/findings.py wontfix <id> <reason>",
            "```",
        ]
    else:
        lines.append("No high-severity finding is open, so this was not the "
                     "findings gate -- the cycle crashed or the panel was missing. "
                     "The log says which.")
    lines += ["", f"Log: {_run_url()}"]
    return "ORC cycle BLOCKED -- the loop has stopped itself", "\n".join(lines)


def news_message() -> tuple[str, str] | None:
    """Whatever notify.py decided was worth waking someone for."""
    p = config.REPORTS / "NEWS.json"
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    items = d.get("items") or []
    if not items:
        return None
    body = "\n".join(f"- {i}" for i in items)
    body += (f"\n\nrun `{d.get('run_id')}` at {d.get('generated_utc')}"
             f"\n\nLog: {_run_url()}"
             "\n\nNothing here is a result until it clears shape, independent "
             "paths, PBO, the search test and the robustness gate. The cycle "
             "report says which of those each cell failed.")
    return f"ORC: {len(items)} thing(s) to look at", body


def watchdog_message() -> tuple[str, str] | None:
    """Has the loop gone quiet?  Asked from OUTSIDE the loop.

    notify.py already knows the six ways this goes quiet without going wrong,
    but it only runs INSIDE a cycle, so the only thing that can report a stopped
    loop is the loop. That is not a watchdog. If the worker stops firing and the
    workstation is off, both halves are silent and so is every alarm -- and a
    public repository's scheduled workflows are themselves disabled after long
    enough without activity, so a stall can quietly become permanent.

    This reads only committed artefacts, so a separate workflow on its own
    schedule can ask the question without the panel, the ledger build or any
    dependency the cycle needs:

      reports/CYCLE_SUMMARY.json   when the worker last finished
      reports/REASONING_LOG.json   when the local reasoning pass last attempted
      ledger/trials.sqlite         when a question nobody had asked was answered
      reports/FINDINGS.json        whether the gate is holding the loop shut
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import notify

    now = datetime.now(timezone.utc)
    quiet: list[str] = []

    def _age(stamp: str | None) -> timedelta | None:
        if not stamp:
            return None
        try:
            return now - datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        except ValueError:
            return None

    summary = config.REPORTS / "CYCLE_SUMMARY.json"
    age = _age(json.loads(summary.read_text(encoding="utf-8")).get("finished_utc")
               if summary.exists() else None)
    if age is None:
        quiet.append("- **the worker has never reported.** No "
                     "reports/CYCLE_SUMMARY.json, or it cannot be read.")
    elif age > notify.STALL_AFTER:
        quiet.append(f"- **the worker has not finished a cycle in "
                     f"{age.days}d {age.seconds // 3600}h.** It is scheduled every "
                     "six hours. Check whether the scheduled workflow is still "
                     "enabled -- GitHub disables them on a repository that has "
                     "gone quiet, which turns a stall into a permanent one.")

    rlog = config.REPORTS / "REASONING_LOG.json"
    age = _age(json.loads(rlog.read_text(encoding="utf-8")).get("utc")
               if rlog.exists() else None)
    if age is not None and age.days >= notify.REASONING_STALE_DAYS:
        quiet.append(f"- **the reasoning pass has not run in {age.days} day(s).** "
                     "It runs on the workstation at 08:25 with a 20:25 retry, so "
                     "this means the machine has been off or asleep through both, "
                     "or the task is failing before it writes its log. Nothing new "
                     "is being asked.")

    try:
        from orc.ledger.trials import Ledger
        with Ledger() as led:
            age = _age(led.newest_trial_utc())
            total = led.total_trials()
    except Exception as exc:                                       # noqa: BLE001
        quiet.append(f"- **the ledger cannot be opened**: {type(exc).__name__}: {exc}")
        age, total = None, "?"
    if age is not None and age.days >= notify.LEDGER_IDLE_DAYS:
        quiet.append(f"- **no new trial in {age.days} day(s)** (N = {total}). Both "
                     "halves may be running while every proposal is killed or "
                     "every registered grid is exhausted. The reports stay fresh "
                     "and the research has stopped.")

    try:
        import findings as ledger
        blocking = ledger.blocking()
    except Exception:                                              # noqa: BLE001
        blocking = []
    if blocking:
        quiet.append(f"- **{len(blocking)} high-severity finding(s) hold the gate "
                     "shut.** Every cycle refuses until each is fixed or "
                     "dispositioned: " + ", ".join(f"`{f['id']}`" for f in blocking))

    if not quiet:
        return None
    body = ("The watchdog runs outside the cycle it watches, so this is what the "
            "loop could not tell you itself.\n\n" + "\n".join(quiet)
            + f"\n\nChecked {now.isoformat(timespec='seconds')} from committed "
              f"artefacts only.\n\nLog: {_run_url()}")
    return "ORC has gone quiet", body


def main(argv: list[str]) -> int:
    if "--watchdog" in argv:
        out = watchdog_message()
    else:
        out = blocked_message() if "--blocked" in argv else news_message()
    if out is None:
        print("nothing to say", file=sys.stderr)
        return 1
    title, body = out
    print(title + SEP + body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
