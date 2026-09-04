"""ORC | Decide whether anything happened worth interrupting someone for.

These are the ways this system goes quiet without going wrong-looking. Every
one of them leaves the reports fresh, the exit codes zero and the dashboard
green, which is why each needs its own signal rather than a general health check:

  a survivor    A cell cleared every check. This is the one the whole apparatus
                exists to produce, and it must not scroll past unseen.
  a rejection   A queued hypothesis failed its schema and was moved aside. The
                cycle carries on reporting success while the reasoning layer's
                output is silently going in the bin.
  a stall       No cycle has finished recently. The worker runs every six hours
                and the reasoning layer daily, so silence past a day means one
                of them stopped and nothing else will say so.
  an idle loop  Both halves ran and neither asked anything new. Nothing fails:
                the reasoning stamp is fresh, the cycle report is fresh, the
                queue is empty because everything in it was consumed. The
                ledger simply stops growing and the project quietly becomes a
                job that re-scores its exhausted grids forever.
  a stuck push  A hypothesis was registered locally and never reached the
                remote. The worker collects from the remote, so the question
                exists on exactly one machine and will never be answered.
  a finding     An open high-severity review finding. A cycle refuses to run on
                top of one, so it stops the research until it is dispositioned.
  the target    A cell reaches the owner's stop condition -- CAGR 100 % at a
                drawdown of 25 % or less -- or, having reached it, finishes its
                verification. Nothing else in this file can say that the
                research is over, and the last step before it is over needs a
                person: only a hand-written token opens the holdout.
  a split vote  Two providers disagree about whether a family's pre-registered
                kill condition applies. Nothing closes and nothing fails: the
                family stays open and is re-enumerated every six hours while a
                sentence written before the numbers existed turns out to be
                readable two ways. The first split found a reporting defect --
                the metric the clause named had fallen out of the surface.

Prints one line per item and exits 0 when there is news, 1 when there is not,
so a scheduler can branch on the exit code without parsing anything.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Findings and reports quote code and prose that a cp949 console cannot encode.
# A print that raises takes the whole run down over a dash, which is how the
# first full panel build died at symbol 807 of 810.
try:
    sys.stdout.reconfigure(errors="replace")
except (AttributeError, OSError):                                  # pragma: no cover
    pass
sys.path.insert(0, str(Path(__file__).resolve().parent))

from orc import config, runstate                                  # noqa: E402
from orc.orchestrator.verdict import survivors                    # noqa: E402

# The worker fires every six hours; a day of silence is past any schedule
# slipping and means something stopped.
STALL_AFTER = timedelta(hours=30)

# The reasoning pass fires four times a day, so a full day without the task
# even STARTING is not a missed slot -- it is a task that is not firing. Kept
# separate from the staleness of its OUTPUT below, which a healthy loop is
# allowed to have: the evidence gate skips a pass that has nothing new to read.
REASONING_ASLEEP_AFTER = timedelta(hours=26)

# The reasoning pass runs daily. Two missed days is past any single
# machine-was-off explanation.
REASONING_STALE_DAYS = 2

# The reasoning pass runs daily and every hypothesis that survives the adversary
# puts new rows in the ledger, so two days without a single new trial means the
# proposals are not arriving, or all of them are being killed, or the registered
# grids are exhausted. Any of those ends the research, and none of them looks
# like a failure from the outside.
LEDGER_IDLE_DAYS = 2

# The supervisor is the thing that is supposed to be working right now, so its
# silence is measured in hours rather than days. Its longest single action is a
# reasoning pass with a three-hour ceiling, and it writes a row when that
# finishes -- so four hours of nothing means it is not running, not that it is
# busy. This is the alarm the whole continuous loop turns on: if the supervisor
# dies, every other screen looks exactly as it did while it was alive.
SUPERVISOR_SILENT_AFTER = timedelta(hours=4)


def _load(name: str):
    p = config.REPORTS / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def collect() -> list[str]:
    news: list[str] = []

    summary = _load("CYCLE_SUMMARY.json")
    if summary is None:
        return ["ORC: no cycle has ever finished"]

    finished = datetime.fromisoformat(summary["finished_utc"])
    if finished.tzinfo is None:
        finished = finished.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - finished
    if age > STALL_AFTER:
        news.append(f"ORC stalled: last cycle was {age.days}d {age.seconds // 3600}h ago")

    for res in summary.get("results", []):
        rep = _load(f"{res['hypothesis_id']}_SURFACE.json")
        if rep is None:
            continue
        for sym, s in survivors(rep):
            news.append(
                f"{rep['hypothesis_id']} {rep['family']}: {sym} clears every check "
                f"at {rep['metric']} {s['best_value']:+.4f}  {s['best_config']}")

    # The owner's stop condition, which is the one piece of news that ends the
    # project rather than informing it.  Read from the report the cycle wrote
    # so this file keeps its reports-only property; a missing file is silence,
    # not a clean bill of health, and the stall check above already covers a
    # cycle that stopped writing.
    tgt = _load("TARGET.json") or {}
    if tgt.get("state") == "COMPLETE":
        news.append(f"ORC 연구 종료 조건 충족: {tgt.get('headline')}. "
                    "reports/TARGET.json 에 검증 목록이 있습니다")
    elif tgt.get("state") == "VERIFIED_ON_DEVELOPMENT":
        news.append(f"ORC: {tgt.get('headline')}. 봉인 홀드아웃은 사람이 "
                    "토큰 파일을 써야 열립니다 -- 남은 개봉 횟수는 유한합니다")
    elif tgt.get("state") == "CANDIDATE_UNVERIFIED":
        news.append(f"ORC: {tgt.get('headline')}")

    # A surviving mutation is not a broken build and nothing goes red for it,
    # which is exactly why it needs a line here: the suite is green, the code
    # is correct, and a defect of that shape would not be noticed.
    mut = _load("MUTATION.json") or {}
    if mut.get("survived"):
        news.append(
            f"ORC mutation gate: {len(mut['survived'])} of {mut.get('mutations')} "
            f"deliberate defects were NOT caught by the suite "
            f"({', '.join(mut['survived'])}). The code is fine; the tests are "
            "not looking. See reports/MUTATION.json")

    # Two providers reading one pre-registered sentence differently is a fact
    # about the sentence, and it closes nothing, so without this it would sit in
    # a JSON file nobody opens while the family is re-enumerated every six
    # hours. The first split found a real defect -- the metric the clause named
    # had fallen out of the report -- which is exactly the class of thing that
    # must not wait for someone to go looking.
    votes = _load("CLOSE_VOTES.json") or {}
    for hid, fam in (votes.get("families") or {}).items():
        if fam.get("decision") != "SPLIT":
            continue
        said = ", ".join(f"{n}={v.get('verdict')}"
                         for n, v in sorted((fam.get("votes") or {}).items()))
        news.append(
            f"ORC close vote SPLIT on {hid} {fam.get('family')}: {said}. The "
            f"family stays open and nothing was closed. Two models disagreeing "
            f"about whether a pre-registered clause applies is a fact about the "
            f"clause -- see reports/CLOSE_VOTES.json")

    rejected = sorted((config.QUEUE / "rejected").glob("*.json")) \
        if (config.QUEUE / "rejected").exists() else []
    for r in rejected:
        news.append(f"ORC rejected a queued hypothesis: {r.name}")

    # The ledger's newest row, not the cycle's freshness. A cycle that re-scored
    # the whole registry and added nothing is indistinguishable, by every other
    # signal in this file, from one that answered a brand new question.
    try:
        from orc.ledger.trials import Ledger
        with Ledger() as led:
            newest = led.newest_trial_utc()
        if newest:
            last = datetime.fromisoformat(newest)
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            idle = (datetime.now(timezone.utc) - last).days
            if idle >= LEDGER_IDLE_DAYS:
                queued = len(list(config.QUEUE.glob("*.json")))
                news.append(
                    f"ORC is idle: no new trial in {idle} days, {queued} hypothesis "
                    f"file(s) queued. The cycle keeps reporting and nothing new is "
                    f"being asked or answered")
    except Exception:                                              # noqa: BLE001
        pass

    # A commit that never reached the remote is a hypothesis that exists only
    # on this workstation. The worker collects from the remote, so the reports
    # stay fresh, the ledger keeps its count, and the question is simply never
    # asked. Nothing else in this file can see it.
    try:
        import subprocess
        r = subprocess.run(["git", "rev-list", "--count", "@{u}..HEAD"],
                           cwd=config.ORC_ROOT, capture_output=True, text=True,
                           check=False, timeout=30)
        if r.returncode == 0 and int(r.stdout.strip() or 0) > 0:
            news.append(f"ORC has {r.stdout.strip()} commit(s) that never reached "
                        f"the remote; the worker cannot see them")
    except Exception:                                              # noqa: BLE001
        pass

    # The worker refreshes CYCLE_SUMMARY every six hours whether or not the
    # reasoning layer ran, so a reasoning pass that dies -- an expired token, a
    # rate limit, a machine asleep at a slot, a scheduled task whose absolute
    # path no longer exists -- leaves the reports looking perfectly fresh while
    # no new question is ever asked again.
    #
    # Two different clocks, and conflating them was a bug waiting to happen.
    # WOKE UP says the schedule is still firing: since the guard became an
    # evidence fingerprint a healthy pass often decides there is nothing new to
    # read and writes no output at all, so silence in the output is not a
    # fault. ASKED says a question was actually put. Only the first going quiet
    # means the machinery is broken.
    try:
        woke = runstate.reasoning_wakeups(1)
        if woke:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(
                str(woke[0]["utc"]).replace("Z", "+00:00"))
            if age > REASONING_ASLEEP_AFTER:
                news.append(
                    f"ORC reasoning has not woken up in {age.days}d "
                    f"{age.seconds // 3600}h; it is scheduled four times a day, "
                    f"so the task itself is not firing "
                    f"(python scripts/schedule.py)")
    except Exception:                                              # noqa: BLE001
        pass
    try:
        last = runstate.last_reasoning()
        if last.get("utc"):
            days = (datetime.now(timezone.utc) - datetime.fromisoformat(
                str(last["utc"]).replace("Z", "+00:00"))).days
            if days >= REASONING_STALE_DAYS:
                news.append(f"ORC reasoning has asked nothing for {days} days; "
                            f"the worker keeps reporting but the queue stays empty")
    except Exception:                                              # noqa: BLE001
        pass

    # The supervisor, from two different angles, because they fail differently.
    #
    # The LOCK says whether a process is alive on this machine right now. It is
    # gitignored, so this branch only means anything where the supervisor
    # actually runs -- which is the workstation, which is where this function
    # is called from a cycle.
    try:
        sup = runstate.supervisor()
        if sup.get("heartbeat_utc") and not sup.get("alive"):
            news.append(
                f"ORC supervisor is DEAD: its heartbeat stopped "
                f"{runstate.ago(sup['heartbeat_utc'])} (pid {sup.get('pid')}). "
                f"Nothing is scouting, reviewing or proposing. "
                f"Start-ScheduledTask -TaskName 'ORC Forever'")
        elif not sup.get("heartbeat_utc") and runstate.activities(1):
            news.append("ORC supervisor has no heartbeat at all, but has worked "
                        "before -- the lock was removed or the process was "
                        "killed without releasing it")
    except Exception:                                              # noqa: BLE001
        pass

    # The ACTIVITY LOG is committed, so this branch works from anywhere -- and
    # it answers the question the lock cannot: has the supervisor DONE anything
    # lately, as opposed to merely being alive.
    try:
        acts = runstate.activities(1)
        if acts:
            quiet = datetime.now(timezone.utc) - datetime.fromisoformat(
                str(acts[0]["utc"]).replace("Z", "+00:00"))
            if quiet > SUPERVISOR_SILENT_AFTER:
                news.append(
                    f"ORC supervisor has done nothing for {quiet.days}d "
                    f"{quiet.seconds // 3600}h; its longest single action is "
                    f"capped at three hours, so this is a stop and not a "
                    f"long run")
    except Exception:                                              # noqa: BLE001
        pass

    # Open findings, not the latest review: a finding reported last week and
    # never dispositioned is exactly the one that needs saying again.
    try:
        import findings as ledger
        for f in ledger.blocking():
            news.append(f"BLOCKING finding {f['id']} {f.get('file')}:"
                        f"{f.get('line', '?')} {str(f.get('what', ''))[:110]}")
    except Exception:                                              # noqa: BLE001
        pass

    return news


def main() -> int:
    news = collect()
    for line in news:
        print(line)
    return 0 if news else 1


if __name__ == "__main__":
    raise SystemExit(main())
