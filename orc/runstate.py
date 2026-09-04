"""ORC | Is the loop running right now, and when did it last actually research?

`health.py` answers "is the machine alive" by probing GitHub and Task
Scheduler, which costs a minute and needs credentials.  `status.py` and
`briefing.py` are read long after they were written, often from a phone, and
they need the same answer from **durable** facts instead: files and timestamps
that still mean the same thing five hours later.

That distinction matters because this project has two ways of looking busy
while researching nothing, and neither one raises an error:

  the worker fires on a six-hour cron whether or not anything was proposed.
  Trials dedupe on (config, symbol, evaluator, panel, code), so a cycle over an
  unchanged registry inserts ZERO rows and still writes a fresh report, a
  fresh commit and a green run.

  the reasoning layer is the only thing that proposes, and it runs on the
  workstation.  When it cannot launch at all -- the repository moved and the
  scheduled task still pointed at the old path, which is what happened on
  2026-09-03 -- the queue drains once and is never refilled.  Every other
  screen stayed green for that whole day.

So "running" is decided here from four clocks and nothing else:

  newest trial     the only clock that moves when a question nobody had asked
                   before gets answered
  cycle attempts   reports/CYCLE_LOG.jsonl, append-only, one line per worker
                   attempt INCLUDING the ones that added nothing
  the queue        a registered question waiting for the next worker slot
  the schedule     whether the local task can still find this repository

`reasoning_due()` lives here too, because "may the reasoning layer run now" is
the same question read from the same clocks.  It replaces a once-a-calendar-day
stamp: the thing that must never happen twice is two registrations against the
SAME evidence, and a date is a poor proxy for that -- it blocks a second pass
after new results have landed, and permits one after nothing has changed.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from orc import config

KST = timezone(timedelta(hours=9))

# orc-cycle.yml runs `cron: "0 */6 * * *"`.  Nominal: GitHub routinely delays a
# scheduled run on a public repository by two to four hours, so a slot that has
# passed without a run is not by itself a fault.
WORKER_SLOTS_UTC = (0, 6, 12, 18)

# When the local reasoning layer fires: 35 minutes before each worker slot, so
# a hypothesis registered at :25 is collected on the next one instead of
# waiting six hours.  Declared here rather than in schedule.py because a
# briefing generated on the Linux worker has no Task Scheduler to ask, and the
# answer to "when is the next question due" must not depend on which machine
# is rendering it.  schedule.py applies these; nothing else may.
REASONING_SLOTS_KST = ("02:25", "08:25", "14:25", "20:25")

# The floor between two reasoning passes, once the supervisor is driving rather
# than a four-times-a-day trigger.  A pass makes eight to ten model calls and
# takes tens of minutes; a kill is new information, so without a floor the loop
# would start a fresh pass the instant the adversary rejected one and never
# stop.  Forty-five minutes is longer than a pass takes and short enough that a
# day still has room for far more attempts than the budget allows registrations.
MIN_REASONING_INTERVAL_MIN = 45

# How long the newest trial may stand still before the loop is described as
# stalled rather than idle.  One worker slot plus GitHub's routine delay is
# ~10 h, and a reasoning pass fires at least once a day, so a full day with no
# new row means both halves produced nothing -- not that one slot was late.
STALE_HOURS = 26

# One line per worker attempt, appended and never rewritten.  CYCLE_SUMMARY.json
# is overwritten every cycle, so the state this file exists to make visible --
# four attempts in a row that added no trials -- was unrecoverable from it.
CYCLE_LOG = config.REPORTS / "CYCLE_LOG.jsonl"

# One line per reasoning pass, for the same reason: REASONING_LOG.json holds
# only the newest pass, so "has anything been PROPOSED lately" -- the question
# a stalled loop turns on -- could not be answered from the repository at all.
# Both are committed with a union merge driver, because two machines append to
# them and a conflict resolved by picking a side deletes attempts.
REASONING_LOG = config.REPORTS / "REASONING_LOG.jsonl"

# Machine-local, gitignored: what evidence the last registration was made
# against.  Not committed, because it describes this workstation's history with
# the queue and not a research result.
LAST_REASONING = config.ORC_ROOT / "logs" / ".last_cycle"

# Windows HRESULTs a scheduled task returns when it could not even start.  These
# are not "the script refused"; the script never ran, and the difference decides
# whether a human has to repair the schedule or read a log.
LAUNCH_FAILURES = {
    2147942402: "the program named by the task does not exist (0x80070002)",
    2147942667: "the task's start-in folder does not exist (0x8007010B) -- "
                "the repository was almost certainly moved",
    2147942403: "the task's path cannot be reached (0x80070003)",
    2147943712: "the saved credentials were rejected (0x80070520)",
}

# SCHED_S_* informational codes.  None of these is a failure, and reading them
# as one is how a screen ends up printing WARN while everything is right.
# 267009 in particular is what a HEALTHY supervisor reports for as long as it
# runs, which is meant to be always -- so getting it wrong means the row that
# answers "is it working" says WARN forever.
NEVER_RAN = 267011                 # SCHED_S_TASK_HAS_NOT_RUN
TASK_RUNNING = 267009              # SCHED_S_TASK_RUNNING
NO_MORE_RUNS = 267012              # SCHED_S_TASK_NO_MORE_RUNS
TASK_TERMINATED = 267014           # SCHED_S_TASK_TERMINATED
BENIGN_RESULTS = {
    0: "마지막 실행 성공",
    NEVER_RAN: "등록됐고 아직 발화 시각이 오지 않았음",
    TASK_RUNNING: "**지금 실행 중입니다**",
    NO_MORE_RUNS: "더 예정된 실행이 없음 (트리거를 확인하십시오)",
}


# ---------------------------------------------------------------------------
# clocks
# ---------------------------------------------------------------------------
def _utc(stamp: str | None) -> datetime | None:
    if not stamp:
        return None
    try:
        t = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def kst(stamp: str | datetime | None) -> str:
    t = stamp if isinstance(stamp, datetime) else _utc(stamp)
    return "기록 없음" if t is None else f"{t.astimezone(KST):%Y-%m-%d %H:%M} KST"


def ago(stamp: str | datetime | None, now: datetime | None = None) -> str:
    t = stamp if isinstance(stamp, datetime) else _utc(stamp)
    if t is None:
        return "기록 없음"
    d = (now or datetime.now(timezone.utc)) - t
    if d.total_seconds() < 0:
        return "미래"
    if d.days:
        return f"{d.days}일 {d.seconds // 3600}시간 전"
    if d.seconds >= 3600:
        return f"{d.seconds // 3600}시간 {(d.seconds % 3600) // 60}분 전"
    return f"{d.seconds // 60}분 전"


def until(stamp: str | datetime | None, now: datetime | None = None) -> str:
    t = stamp if isinstance(stamp, datetime) else _utc(stamp)
    if t is None:
        return "미정"
    d = t - (now or datetime.now(timezone.utc))
    if d.total_seconds() < 0:
        return "지났음"
    if d.days:
        return f"{d.days}일 {d.seconds // 3600}시간 후"
    if d.seconds >= 3600:
        return f"{d.seconds // 3600}시간 {(d.seconds % 3600) // 60}분 후"
    return f"{max(d.seconds // 60, 1)}분 후"


def task_time(raw: str | None) -> str:
    """A Task Scheduler timestamp in the same shape as every other time here.

    Get-ScheduledTaskInfo returns a US-format local string, and 11/30/1999 is
    its sentinel for "never ran".  Both leak straight into a Korean report as
    noise if they are printed as-is.
    """
    s = str(raw or "").strip()
    if not s or s.startswith("11/30/1999"):
        return "없음"
    for fmt in ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y %I:%M:%S %p", "%Y-%m-%d %H:%M:%S"):
        try:
            return f"{datetime.strptime(s, fmt):%Y-%m-%d %H:%M} KST"
        except ValueError:
            continue
    return s


def next_worker_slot(now: datetime | None = None) -> datetime:
    """The next nominal orc-cycle firing, from the cron in the workflow."""
    now = now or datetime.now(timezone.utc)
    for h in WORKER_SLOTS_UTC:
        t = now.replace(hour=h, minute=0, second=0, microsecond=0)
        if t > now:
            return t
    return (now + timedelta(days=1)).replace(
        hour=WORKER_SLOTS_UTC[0], minute=0, second=0, microsecond=0)


def next_reasoning_slot(now: datetime | None = None) -> datetime:
    """The next nominal reasoning fire, from REASONING_SLOTS_KST.

    Nominal because the workstation has to be awake for it.  WakeToRun and
    StartWhenAvailable are set, so a machine that was off catches up after
    boot rather than skipping -- which is a different statement from "it ran".
    """
    now = (now or datetime.now(timezone.utc)).astimezone(KST)
    for s in REASONING_SLOTS_KST:
        hh, mm = (int(x) for x in s.split(":"))
        t = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if t > now:
            return t.astimezone(timezone.utc)
    hh, mm = (int(x) for x in REASONING_SLOTS_KST[0].split(":"))
    return (now + timedelta(days=1)).replace(
        hour=hh, minute=mm, second=0, microsecond=0).astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# what actually happened
# ---------------------------------------------------------------------------
def _append(path: Path, row: dict) -> None:
    """Append-only, and a failure to write must never take a run down: the log
    describes the run, it is not the run."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=str, ensure_ascii=False) + "\n")
    except OSError:                                                # pragma: no cover
        pass


def _read_jsonl(path: Path, limit: int, key: str) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict):
            rows.append(rec)
    rows.sort(key=lambda r: str(r.get(key) or ""), reverse=True)
    return rows[:limit]


def append_cycle_log(summary: dict, path: Path | None = None) -> None:
    """Record one worker attempt, including one that added no trials."""
    _append(path or CYCLE_LOG,
            {k: summary.get(k) for k in
             ("run_id", "started_utc", "finished_utc", "trials_before",
              "trials_after", "trials_added", "hypotheses_run")})


def cycle_attempts(limit: int = 10, path: Path | None = None) -> list[dict]:
    """Worker attempts, newest first, from the append-only log.

    Rows that added no trials are the point of this list.  A cycle that ran and
    inserted nothing is the signature of an empty queue, and it is invisible in
    the ledger by construction.
    """
    return _read_jsonl(path or CYCLE_LOG, limit, "started_utc")


def append_reasoning_log(report: dict, path: Path | None = None) -> None:
    """Record one reasoning pass: when, and what came out of it.

    `registered` is the only field that can be checked against the tree, and it
    is the one that matters: a run of passes that registered nothing is a loop
    that is alive and asking nothing, which looks identical to a healthy one on
    every other screen.
    """
    steps = report.get("steps") or {}
    row = {"utc": report.get("utc"),
           "blocked": steps.get("blocked") or [],
           "registered": [a.get("file") for a in (steps.get("adversary") or [])
                          if a.get("verdict") == "REGISTER"],
           "killed": [a.get("file") for a in (steps.get("adversary") or [])
                      if a.get("verdict") != "REGISTER"],
           "held": steps.get("held") or [],
           "proposed": steps.get("propose") if isinstance(
               steps.get("propose"), list) else [],
           "unavailable": [k for k, v in steps.items()
                           if isinstance(v, str) and v.startswith("skipped")]}
    _append(path or REASONING_LOG, row)


def record_gate(due: bool, why: str, path: Path | None = None) -> None:
    """Record that the reasoning layer WOKE UP, and what the gate decided.

    Without this a healthy skip and a dead scheduled task are the same silence.
    The pass only writes REASONING_LOG.json when it produces something, so once
    skipping became normal - which is the whole point of the evidence gate -
    "nothing has been written lately" stopped meaning "nothing is running".
    A wake-up row is the difference, and it is the row that says the schedule
    is still firing at all.
    """
    _append(path or REASONING_LOG,
            {"utc": datetime.now(timezone.utc).isoformat(),
             "gate": "DUE" if due else "SKIP", "why": why})


def reasoning_wakeups(limit: int = 10, path: Path | None = None) -> list[dict]:
    """Every time the reasoning layer woke up, pass or skip, newest first."""
    return _read_jsonl(path or REASONING_LOG, limit, "utc")


def reasoning_passes(limit: int = 10, path: Path | None = None) -> list[dict]:
    """Reasoning passes that actually ran the pipeline, newest first.

    Gate rows are excluded: they say the schedule fired, not that a question
    was asked, and mixing them would make a week of skips look like a week of
    work.
    """
    return [r for r in _read_jsonl(path or REASONING_LOG, limit * 8, "utc")
            if "gate" not in r][:limit]


def research_runs(limit: int = 10) -> list[dict]:
    """Runs that inserted at least one new trial, newest first, FROM THE LEDGER.

    This reads counts and timestamps, never a metric: hunting a maximum across
    every trial ever recorded is the selection bias the protocol exists to
    contain, and a clock is not a maximum.
    """
    try:
        from orc.ledger.trials import Ledger
        with Ledger() as led:
            return led.runs(limit)
    except Exception:                                              # noqa: BLE001
        return []


def timeline(limit: int = 8) -> list[dict]:
    """Cycle attempts and ledger runs merged on run_id, newest first.

    Either source alone lies in a different direction.  The ledger cannot show
    an attempt that produced nothing; the log only covers attempts made after
    it was introduced.  Merged, an attempt is present if either knows about it.
    """
    merged: dict[str, dict] = {}
    for r in research_runs(limit * 3):
        merged[r["run_id"]] = {
            "run_id": r["run_id"], "started_utc": r["first_utc"],
            "finished_utc": r["last_utc"], "trials_added": r["trials"],
            "hypotheses_run": r["hypotheses"], "source": "ledger"}
    for a in cycle_attempts(limit * 3):
        rid = str(a.get("run_id") or "")
        row = merged.setdefault(rid, {"run_id": rid})
        row.update({k: v for k, v in a.items() if v is not None})
        row["source"] = "log"
    out = sorted(merged.values(),
                 key=lambda r: str(r.get("started_utc") or ""), reverse=True)
    return out[:limit]


# ---------------------------------------------------------------------------
# the local schedule
# ---------------------------------------------------------------------------
TASK_QUERY = (
    "Get-ScheduledTask | Where-Object {$_.TaskName -like 'ORC*'} | "
    "ForEach-Object { $i = Get-ScheduledTaskInfo $_; "
    "[pscustomobject]@{name=$_.TaskName; state=[string]$_.State; "
    "last=[string]$i.LastRunTime; result=$i.LastTaskResult; "
    "next=[string]$i.NextRunTime; "
    "exec=($_.Actions | ForEach-Object {$_.Execute}) -join '|'; "
    "arguments=($_.Actions | ForEach-Object {$_.Arguments}) -join '|'; "
    "workdir=($_.Actions | ForEach-Object {$_.WorkingDirectory}) -join '|'} } | "
    "ConvertTo-Json -Compress -Depth 4")


def _powershell(cmd: str, timeout: int = 60):
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                            "-Command", cmd], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0 or not (r.stdout or "").strip():
        return None
    try:
        return json.loads(r.stdout)
    except ValueError:
        return None


def local_tasks() -> list[dict] | None:
    """Every ORC* scheduled task with its action paths.  None when not queryable.

    The paths are the part health.py used to omit, and their absence is why a
    task that could not launch for a whole day was one yellow line on a screen
    that was otherwise green.
    """
    data = _powershell(TASK_QUERY)
    if data is None:
        return None
    if isinstance(data, dict):
        data = [data]
    return sorted(data, key=lambda t: str(t.get("name", "")))


# A task registered with Windows Task Scheduler carries a Windows path no
# matter which machine later READS it, and CI reads it on Linux.  Matches a
# drive letter ("D:\..." or "D:/...") and a UNC share ("\\server\share").
_WINDOWS_ABSOLUTE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")


def _same_tree(path: str, root: Path) -> bool:
    r"""Is `path` inside `root`?

    Decided by the flavour of the PATH, never by the flavour of the host.  On
    Linux ``Path(r"D:\Project\ORC")`` is not an absolute path at all: it is one
    ordinary FILENAME that happens to contain backslashes, so ``resolve()``
    hangs it off the current directory -- which during a run IS this
    repository.  A task pointing at a checkout that no longer exists therefore
    read as living inside the repo, and the check that exists to catch a moved
    checkout returned the opposite answer on the runner from the one it returns
    on the workstation.  That is how a green suite here failed there.

    A Windows path cannot be inside a POSIX checkout, so on any host that is
    not Windows the answer is False and does not depend on the cwd.
    """
    text = str(path).strip().strip('"')
    if not text:
        return False
    if _WINDOWS_ABSOLUTE.match(text) and os.name != "nt":
        return False
    try:
        return Path(text).resolve().is_relative_to(Path(root).resolve())
    except (OSError, ValueError):
        return False


def task_path_problems(tasks: list[dict] | None = None,
                       root: Path | None = None) -> list[str]:
    """Tasks whose script or start-in folder is not inside this repository.

    A moved checkout leaves the schedule pointing at a directory that no longer
    exists, and Task Scheduler reports that as a numeric HRESULT on a screen
    nobody reads.  This is the check that would have caught it.
    """
    root = root or config.ORC_ROOT
    tasks = local_tasks() if tasks is None else tasks
    if not tasks:
        return []
    bad = []
    for t in tasks:
        name = t.get("name", "?")
        for part in [p for p in str(t.get("workdir") or "").split("|") if p.strip()]:
            if not _same_tree(part, root):
                bad.append(f"{name}: 시작 폴더 `{part}` 가 {root} 안이 아닙니다")
        for part in [p.strip(' "') for p in str(t.get("arguments") or "").split("|")]:
            # Only arguments that look like a path into the repo are checked; a
            # switch such as -Force is not one.
            if part.lower().endswith((".vbs", ".ps1", ".py")) \
                    and not _same_tree(part, root):
                bad.append(f"{name}: 스크립트 `{part}` 가 {root} 안이 아닙니다")
    return bad


def task_result_note(result) -> tuple[str, str]:
    """(severity, prose) for a LastTaskResult.  Severity is 'ok'|'warn'|'bad'."""
    try:
        rc = int(result)
    except (TypeError, ValueError):
        return "warn", f"결과 코드 불명 ({result})"
    if rc in BENIGN_RESULTS:
        return "ok", BENIGN_RESULTS[rc]
    if rc == TASK_TERMINATED:
        return "warn", ("마지막 실행이 강제 종료됐음 — 시간 제한에 걸렸거나 "
                        "사람이 멈췄습니다")
    if rc in LAUNCH_FAILURES:
        return "bad", f"실행되지 못했음 — {LAUNCH_FAILURES[rc]}"
    if rc == 1:
        return "warn", "종료 코드 1 — 스크립트가 거부했거나 실패했음 (로그 확인)"
    return "warn", f"마지막 결과 {rc}"


# ---------------------------------------------------------------------------
# may the reasoning layer run
# ---------------------------------------------------------------------------
def evidence_fingerprint() -> str:
    """A hash of everything the reasoning layer is allowed to reason from.

    Section 9 of the constitution says the pass reads reports/CYCLE_REPORT.md
    and nothing else, and what decides whether a family is still open is the
    registry and configs/closed/.  Two passes over an identical fingerprint
    would ask the same question twice and register two batches against one
    piece of evidence, which is the only thing the old date stamp was really
    protecting against.
    """
    h = hashlib.sha256()
    rep = config.REPORTS / "CYCLE_REPORT.md"
    h.update(rep.read_bytes().replace(b"\r\n", b"\n") if rep.exists() else b"-")
    try:
        from orc.ledger.trials import Ledger
        with Ledger() as led:
            h.update(f"|{led.total_trials()}|{led.newest_trial_utc()}".encode())
    except Exception:                                              # noqa: BLE001
        h.update(b"|ledger-unavailable")
    for d in (config.CONFIGS / "closed", config.REGISTRY):
        h.update(("|" + ",".join(sorted(p.name for p in d.glob("*.json")))
                  if d.exists() else "|-").encode())
    return h.hexdigest()


def last_reasoning() -> dict:
    """What the last completed pass was made against.  {} when unknown.

    A file written by the version that stored a bare date is deliberately read
    as unknown rather than migrated: the fingerprint it was made against cannot
    be recovered, and treating that as "already done" would keep the pass shut
    for a day for no measurable reason.
    """
    try:
        raw = LAST_REASONING.read_text(encoding="utf-8-sig").strip()
    except OSError:
        return {}
    try:
        rec = json.loads(raw)
    except ValueError:
        return {"legacy": raw}
    return rec if isinstance(rec, dict) else {}


def stamp_reasoning(fingerprint: str | None = None) -> dict:
    rec = {"utc": datetime.now(timezone.utc).isoformat(),
           "fingerprint": fingerprint or evidence_fingerprint()}
    LAST_REASONING.parent.mkdir(parents=True, exist_ok=True)
    LAST_REASONING.write_text(json.dumps(rec), encoding="utf-8")
    return rec


def registrations_last_24h(now: datetime | None = None) -> list[str]:
    """Hypotheses registered in the last rolling 24 hours.

    Read from the registry's own `registered_utc`, which is written by
    Hypothesis.register() at the moment the claim and the grid are hashed -- the
    moment of no return.  A killed proposal is deliberately not counted: it
    cost a file in configs/killed/ and zero rows in the ledger, so it is not
    the thing the budget exists to ration.
    """
    now = now or datetime.now(timezone.utc)
    out = []
    for p in sorted(config.REGISTRY.glob("*.json")) if config.REGISTRY.exists() else []:
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        t = _utc(rec.get("registered_utc"))
        if t is not None and (now - t) < timedelta(hours=24):
            out.append(rec.get("hypothesis_id", p.stem))
    return out


def reasoning_due(now: datetime | None = None) -> tuple[bool, str]:
    """May a reasoning pass run?  (due, one-line reason either way).

    The order of these checks is the whole design.

    1. A non-empty queue means the last batch has not been answered yet.  Asking
       again now spends registrations on a report the worker has not updated,
       and registration is irreversible.  This is a stronger guard than a
       calendar day AND it never blocks a pass that has something new to read.
    2. A proposal held for an unreachable adversary is judged before anything
       new is asked for, so a pass is due while one is waiting.
    3. Otherwise: due exactly when the evidence has changed since the last
       completed pass.  New results, a closed family, a grown N -- any of them
       is a new question to ask.  None of them is a reason to re-ask the old one.
    """
    now = now or datetime.now(timezone.utc)
    queued = sorted(config.QUEUE.glob("*.json")) if config.QUEUE.exists() else []
    if queued:
        return False, (f"큐에 {len(queued)}개가 답을 기다립니다 "
                       f"({', '.join(p.stem for p in queued)}) — "
                       "워커가 가져가기 전에는 새로 묻지 않습니다")

    # A rate limit, not a budget.  The pass itself makes eight to ten model
    # calls and takes tens of minutes; without this the supervisor would start
    # a second one on top of the first the moment a proposal was killed, since
    # a kill is new information and the branch below would say so forever.
    passes = reasoning_passes(1)
    last_pass = _utc(passes[0].get("utc")) if passes else \
        _utc(last_reasoning().get("utc"))
    if last_pass is not None and (now - last_pass) < timedelta(
            minutes=MIN_REASONING_INTERVAL_MIN):
        return False, (f"마지막 패스가 {ago(last_pass, now)}입니다 — "
                       f"패스 간 최소 {MIN_REASONING_INTERVAL_MIN}분을 둡니다")

    proposed = config.CONFIGS / "proposed"
    held = sorted(proposed.glob("*.json")) if proposed.exists() else []
    if held:
        return True, f"심사 대기 제안 {len(held)}건이 있어 먼저 판정합니다"

    # The budget.  Proposing is free in N and registration is not, and the
    # continuous loop is only safe because this line is the thing it cannot
    # spend past.  Checked before the evidence branches, so a day of fresh
    # reports cannot talk it into a fifth registration.
    booked = registrations_last_24h(now)
    if len(booked) >= config.MAX_REGISTRATIONS_PER_DAY:
        return False, (f"24시간 등록 예산 소진 "
                       f"({len(booked)}/{config.MAX_REGISTRATIONS_PER_DAY}: "
                       f"{', '.join(booked)}) — 제안은 공짜지만 등록은 N을 "
                       "영구히 올립니다")

    fp = evidence_fingerprint()
    prev = last_reasoning()
    if prev.get("fingerprint") and prev.get("fingerprint") != fp:
        return True, f"마지막 패스({kst(prev.get('utc'))}) 이후 증거가 바뀌었습니다"
    if not prev.get("fingerprint"):
        return True, "이 저장소에서 지문이 기록된 패스가 없습니다"

    # The evidence is unchanged, and that used to end it.  But a pass whose
    # proposals were all killed has produced something the next pass does not
    # have: the adversary's reasons.  H0009 was killed as a finer grid over
    # closed H0007 and H0010 for misreading a metric; a proposer that gets to
    # read those two verdicts is asking a better question than one that waits
    # six hours for a report with a new timestamp in it.  Registering nothing
    # costs zero rows, so this branch cannot raise N -- only the budget above
    # can, and it is already spent-checked.
    if passes and not passes[0].get("registered"):
        return True, (f"마지막 패스({kst(passes[0].get('utc'))})는 아무것도 "
                      "등록하지 못했습니다 — 적대자의 기각 사유가 다음 제안이 "
                      "가진 새 정보입니다")
    return False, (f"마지막 패스({kst(prev.get('utc'))}) 이후 증거가 "
                   "그대로이고 그 패스는 등록에 성공했습니다 — 같은 리포트에 "
                   "두 번 등록하지 않습니다")


# ---------------------------------------------------------------------------
# the one-line answer
# ---------------------------------------------------------------------------
RUNNING, QUEUED, WORKING, IDLE, STALLED, STOPPED = (
    "RUNNING", "QUEUED", "WORKING", "IDLE", "STALLED", "STOPPED")
MARK = {RUNNING: "🟢", QUEUED: "🟢", WORKING: "🟢",
        IDLE: "🟡", STALLED: "🟠", STOPPED: "🔴"}
HEADLINE = {
    RUNNING: "**지금 백테스트가 돌고 있습니다.**",
    QUEUED: "**살아 있습니다** — 질문이 등록돼 다음 워커 발화에서 평가됩니다.",
    WORKING: "**24시간 감독자가 살아 있고 지금도 일하고 있습니다.**",
    IDLE: "**감독자가 떠 있지 않습니다** — 예약된 추론 발화까지 아무것도 하지 않습니다.",
    STALLED: "**멈춰 가고 있습니다** — 워커는 돌지만 새로 묻는 것이 없습니다.",
    STOPPED: "**멈췄습니다.** 사람이 고쳐야 다시 돕니다.",
}


def activity(now: datetime | None = None, tasks: list[dict] | None = None) -> dict:
    """Durable answer to "is research happening", with the facts behind it.

    Deliberately does NOT probe GitHub.  This is written into a file that is
    read hours later, and "a run was live when this was generated" is exactly
    the sentence that made every screen green through a day in which nothing
    was researched.  health.py keeps the live probe for the question it is
    actually good for.
    """
    now = now or datetime.now(timezone.utc)
    facts: dict = {"now_utc": now.isoformat()}

    runs = research_runs(1)
    attempts = cycle_attempts(1)
    facts["last_new_trial"] = runs[0] if runs else None
    facts["last_attempt"] = attempts[0] if attempts else None
    if not attempts:
        summary = config.REPORTS / "CYCLE_SUMMARY.json"
        if summary.exists():
            try:
                facts["last_attempt"] = json.loads(summary.read_text(encoding="utf-8"))
            except ValueError:
                pass
    facts["next_worker_slot"] = next_worker_slot(now).isoformat()
    facts["queued"] = [p.stem for p in sorted(config.QUEUE.glob("*.json"))] \
        if config.QUEUE.exists() else []

    try:
        import contextlib
        import io

        from orc.orchestrator.spec import load_registry
        with contextlib.redirect_stdout(io.StringIO()):
            facts["open_families"] = [h.hypothesis_id for h in load_registry()]
    except Exception as exc:                                       # noqa: BLE001
        facts["open_families"] = None
        facts["registry_error"] = f"{type(exc).__name__}: {exc}"

    tasks = local_tasks() if tasks is None else tasks
    facts["tasks"] = tasks
    facts["task_path_problems"] = task_path_problems(tasks) if tasks else []
    facts["reasoning_task"] = next(
        (t for t in (tasks or []) if "Reasoning" in str(t.get("name", ""))), None)
    facts["reasoning_due"] = reasoning_due(now)
    facts["supervisor"] = supervisor(now)
    facts["registrations_24h"] = registrations_last_24h(now)
    facts["registration_budget"] = config.MAX_REGISTRATIONS_PER_DAY
    facts["last_activity"] = (activities(1) or [None])[0]
    try:
        facts["next_action"] = next_action(now)
    except Exception as exc:                                       # noqa: BLE001
        facts["next_action"] = ("unknown", f"{type(exc).__name__}: {exc}")

    try:
        sys.path.insert(0, str(config.ORC_ROOT / "scripts"))
        import findings
        facts["blocking"] = [f["id"] for f in findings.blocking()]
    except Exception:                                              # noqa: BLE001
        facts["blocking"] = None

    # --- classify.  Worst mechanical break first: a loop that cannot ask a new
    # question is stopped even while the worker keeps producing reports.
    reasons: list[str] = []
    status = IDLE

    if facts["task_path_problems"]:
        status = STOPPED
        reasons.append("추론 계층이 **실행조차 되지 못합니다** — "
                       + "; ".join(facts["task_path_problems"])
                       + ".  `python scripts/schedule.py --repair` 로 고칩니다")
    rt = facts["reasoning_task"]
    if rt is not None:
        sev, note = task_result_note(rt.get("result"))
        if sev == "bad" and facts["task_path_problems"]:
            status = STOPPED
            reasons.append(f"`{rt.get('name')}`: {note}")
        elif sev == "bad":
            # LastTaskResult holds the code from before a repair until the task
            # fires again.  A launch failure against paths that are now correct
            # is history; calling it a stop would send someone to fix a thing
            # that is already fixed.
            reasons.append(f"`{rt.get('name')}`의 마지막 결과는 실행 실패였지만 "
                           "경로는 지금 정상입니다 — 다음 발화에서 지워집니다")
    if facts["blocking"]:
        status = STOPPED
        reasons.append(f"high 결함 {len(facts['blocking'])}건이 열려 있어 "
                       "모든 추론 패스가 스스로 거부합니다 "
                       f"({', '.join(facts['blocking'])})")
    if facts["open_families"] == [] and not facts["queued"]:
        status = STOPPED
        reasons.append("열린 가족도 대기 중인 질문도 없습니다 — "
                       "다음 패스가 새 메커니즘을 명명하지 않으면 "
                       "루프는 할 일이 없습니다")

    newest = _utc(runs[0]["last_utc"] if runs else None)
    stale_h = None if newest is None else (now - newest).total_seconds() / 3600
    facts["hours_since_new_trial"] = stale_h

    if status != STOPPED:
        started = _utc((facts["last_attempt"] or {}).get("started_utc"))
        finished = _utc((facts["last_attempt"] or {}).get("finished_utc"))
        if started and not finished:
            status = RUNNING
            reasons.append(f"워커 실행 중 — {ago(started, now)} 시작")
        elif facts["queued"]:
            status = QUEUED
            reasons.append(f"질문 {len(facts['queued'])}개가 등록돼 있고 "
                           f"다음 워커 발화({kst(facts['next_worker_slot'])}, "
                           f"{until(facts['next_worker_slot'], now)})에 "
                           "평가됩니다")
        elif facts["supervisor"]["alive"]:
            # The supervisor decides what to do on every tick, and only
            # sometimes is that a new hypothesis.  An empty queue with a live
            # supervisor is not idling: it is scouting, reviewing the kernel,
            # re-running the robustness gate -- work that costs zero ledger
            # rows, which is why it can run around the clock.
            status = WORKING
            act, why = facts["next_action"]
            last = facts["last_activity"] or {}
            reasons.append(f"감독자 살아 있음 (pid {facts['supervisor']['pid']}, "
                           f"박동 {ago(facts['supervisor']['heartbeat_utc'], now)}). "
                           f"지금 할 일: **{act}** — {why}")
            if last:
                reasons.append(f"마지막으로 한 일: {last.get('action')} "
                               f"({ago(last.get('utc'), now)}) — "
                               f"{str(last.get('detail'))[:140]}")
            reasons.append(f"24시간 등록 예산 "
                           f"{len(facts['registrations_24h'])}/"
                           f"{facts['registration_budget']} 사용 — 제안과 검토는 "
                           "공짜고, N을 올리는 것은 등록뿐입니다")
        elif stale_h is None or stale_h > STALE_HOURS:
            status = STALLED
            reasons.append(f"신규 시행이 {ago(newest, now)}로 멈춰 있고 "
                           "대기 중인 질문도 없습니다 — 워커는 돌지만 "
                           "새로 묻는 것이 없습니다")
        else:
            reasons.append(f"마지막 신규 시행 {ago(newest, now)}, 큐는 비었고 "
                           "감독자도 떠 있지 않습니다 — "
                           "`python scripts/forever.py` 또는 "
                           "`python scripts/schedule.py --install`")

    facts["status"] = status
    facts["mark"] = MARK[status]
    facts["headline"] = HEADLINE[status]
    facts["reasons"] = reasons
    return facts


# ---------------------------------------------------------------------------
# what to do right now
# ---------------------------------------------------------------------------
# Work that costs ZERO ledger rows, with how stale each is allowed to get.
#
# This table is what makes "never idle" a true statement rather than a faster
# poll.  Before it, the only thing the loop knew how to do was ask a new
# question, so a day in which the adversary rejected every proposal -- which is
# the adversary working -- was a day the machine sat still.  Every entry here
# is real research that cannot raise N:
#
#   scout      goes to the web for a payer this repository has no way to hear
#              about.  The proposer's tools are Read/Glob/Grep/Write, which is
#              why it re-derived closed H0007 as H0009.
#   kernel     an adversarial read of the evaluators.  Six silent defects were
#              found in one day, one of them putting sealed funding data into
#              the development window.  A defect here voids every result in the
#              project, so this is the highest-value zero-N work there is, and
#              weekly was a schedule chosen for a machine that had other things
#              to do.
#   robustness re-asks whether a recorded number survives cost stress, a walk
#              forward and a regime split.  Cheap, and it reads the ledger
#              rather than adding to it.
#   execution  re-runs one cell on minute bars, which is where the hourly
#              panel's "adverse first" and "one fill" assumptions get tested.
#   survivorship KT-3 is INCONCLUSIVE and blocks every alt-basket hypothesis
#              until the delisted sample is large enough.  Enlarging it is
#              fact-gathering, not a hypothesis, and it unblocks a whole branch.
#
# The numbers are minutes, and they are a judgement about what is worth a model
# call rather than a measurement.  The scout is the one worth stating: at 90
# minutes it would run sixteen times a day against two providers, and it
# dedupes on the payer, so once the notebook is fed most of those calls return
# "0 new, N already known" -- effort spent, nothing gained.  Three hours feeds
# it and does not grind it.  Being wrong here costs model calls and not N,
# which is why it is a tunable and not a threshold; reports/ACTIVITY.jsonl
# shows what each scout actually added, so the cadence can be judged from
# evidence later instead of guessed at again.
ZERO_N_WORK = {
    "scout": 180,
    "kernel_review": 60 * 24,
    "robustness": 60 * 6,
    "execution_realism": 60 * 12,
    "survivorship": 60 * 24 * 3,
}

ACTIVITY_LOG = config.REPORTS / "ACTIVITY.jsonl"


# How long after a FAILED attempt the same action may be tried again.  A
# transient failure -- a 404 refreshing a model list, a call that returned
# nothing, a network blip -- must not cost the action its whole allowance: the
# scout's is 90 minutes, so one bad minute would have meant no scouting for an
# hour and a half.  Nor may it be retried instantly, or a permanently broken
# provider becomes a hot loop.
FAILURE_COOLDOWN_MIN = 12


def record_activity(action: str, detail: str, seconds: float | None = None,
                    path: Path | None = None, ok: bool = True) -> None:
    """One line per thing the supervisor actually did.

    The claim "it never rests" has to be checkable, and this is the file that
    would fail if it were false: a gap in it is a gap in the work.

    `ok` separates two clocks that were the same clock and should not be.  The
    staleness clock -- "when was this last DONE" -- may only be moved by a run
    that worked; a failed attempt moves the cooldown instead.
    """
    _append(path or ACTIVITY_LOG,
            {"utc": datetime.now(timezone.utc).isoformat(), "action": action,
             "detail": detail[:400], "ok": bool(ok),
             "seconds": None if seconds is None else round(seconds, 1)})


def activities(limit: int = 20, path: Path | None = None) -> list[dict]:
    return _read_jsonl(path or ACTIVITY_LOG, limit, "utc")


def last_activity_at(action: str, path: Path | None = None,
                     ok_only: bool = True) -> datetime | None:
    """When this action last ran.  By default only a run that WORKED counts.

    A failed attempt used to reset the staleness clock, so one transient
    provider error bought the scout ninety minutes of silence -- the action
    looked freshly done because it had freshly not worked.  Rows written before
    this field existed have no `ok`, and are read as successes: they were
    recorded by a supervisor that only wrote a line after running something.
    """
    for r in _read_jsonl(path or ACTIVITY_LOG, 2000, "utc"):
        if r.get("action") != action:
            continue
        if ok_only and r.get("ok") is False:
            continue
        return _utc(r.get("utc"))
    return None


# The supervisor's heartbeat.  Machine-local and gitignored: it says whether a
# process is alive on THIS workstation, which is meaningless in a checkout
# anywhere else.
SUPERVISOR_LOCK = config.ORC_ROOT / "logs" / "forever.lock"

# Older than this and the lock is a corpse, not a supervisor.  forever.py beats
# it once per tick, and its longest tick is a reasoning pass.
SUPERVISOR_STALE_MIN = 30


def supervisor(now: datetime | None = None) -> dict:
    """Is the 24-hour supervisor alive, and what did it last do?

    Read from the lock rather than from a process table: the lock is what
    forever.py itself uses to refuse a second copy, so this asks exactly the
    question that matters and cannot disagree with the answer the supervisor
    acted on.
    """
    now = now or datetime.now(timezone.utc)
    out: dict = {"alive": False, "pid": None, "heartbeat_utc": None}
    try:
        rec = json.loads(SUPERVISOR_LOCK.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return out
    beat = _utc(rec.get("heartbeat_utc"))
    out["pid"] = rec.get("pid")
    out["heartbeat_utc"] = rec.get("heartbeat_utc")
    out["alive"] = beat is not None and (now - beat) < timedelta(
        minutes=SUPERVISOR_STALE_MIN)
    return out


def next_action(now: datetime | None = None,
                skip: set[str] | None = None) -> tuple[str, str]:
    """The single most useful thing to do at this instant, and why.

    Ordered by what would be wasted by doing something else first.  A blocking
    finding comes first because every number computed on top of it is void; the
    queue comes next because a registered question already costs N and leaving
    it unanswered is the one form of idling that has already been paid for.

    `skip` names actions THIS caller cannot perform, and the answer is then the
    best of what remains rather than a refusal.  The GitHub runner is the
    caller that needs it: it has no model provider, so `reason`, `scout` and
    `kernel_review` are not available to it, and a supervisor that simply
    declined the top answer would sit through its whole budget being told to do
    the one thing it cannot -- idling for the most literal reason there is.
    """
    now = now or datetime.now(timezone.utc)
    skip = skip or set()

    try:
        sys.path.insert(0, str(config.ORC_ROOT / "scripts"))
        import findings
        blocking = findings.blocking()
    except Exception:                                              # noqa: BLE001
        blocking = []
    if blocking:
        # Not a full stop.  Research on code known to be wrong is forbidden,
        # but reading that code harder is exactly the right response, so the
        # kernel review is the one action allowed through.
        due = last_activity_at("kernel_review")
        if "kernel_review" not in skip and (
                due is None
                or (now - due) > timedelta(minutes=ZERO_N_WORK["kernel_review"])):
            return "kernel_review", (
                f"high 결함 {len(blocking)}건이 열려 있어 연구는 멈춥니다 — "
                "그 코드를 더 읽는 것만 허용됩니다")
        return "blocked", (
            f"high 결함 {len(blocking)}건: {', '.join(f['id'] for f in blocking)}. "
            "사람이 고치거나 findings.py 로 결정을 기록해야 합니다")

    queued = [p.stem for p in sorted(config.QUEUE.glob("*.json"))] \
        if config.QUEUE.exists() else []
    # The owner's stop condition, ahead of the queue and ahead of the next
    # question.  A cell that already meets it changes what is useful: another
    # registration would only raise the multiple-testing bar the candidate
    # itself has to clear, while the checks that would confirm or kill it cost
    # zero ledger rows.  Read from the ledger rather than from
    # reports/TARGET.json on purpose -- a decision to stop the project must not
    # be able to rest on a report a failed cycle left stale.
    try:
        from orc import target as target_mod
        tgt = target_mod.state()
    except Exception:                                              # noqa: BLE001
        tgt = None
    if tgt is not None and tgt["state"] == target_mod.COMPLETE:
        return "done", tgt["headline"]
    if tgt is not None and tgt["state"] == target_mod.CANDIDATE_UNVERIFIED:
        for check, action in (("robustness", "robustness"),
                              ("execution", "execution_realism")):
            if action in skip:
                continue
            if any(check in c["unmeasured"] for c in tgt["candidates"]):
                return action, (f"목표 수치를 만족하는 후보가 있는데 {check} "
                                f"검증이 비어 있습니다 — {tgt['headline']}")

    if queued:
        # The worker evaluates on GitHub, so the workstation is free.  Fall
        # through to zero-N work rather than waiting on it.
        pass

    due, why = reasoning_due(now)
    if due and "reason" not in skip:
        return "reason", why

    for action, max_age_min in sorted(ZERO_N_WORK.items(),
                                      key=lambda kv: kv[1]):
        if action in skip:
            continue
        # A failed attempt gets a short cooldown instead of the action's whole
        # allowance, so a transient provider error costs minutes and a broken
        # one still cannot become a hot loop.
        tried = last_activity_at(action, ok_only=False)
        if tried is not None and (now - tried) < timedelta(
                minutes=FAILURE_COOLDOWN_MIN):
            done = last_activity_at(action)
            if done is None or done < tried:
                continue
        at = last_activity_at(action)
        if at is None:
            return action, (f"{action}: 성공한 실행이 없습니다"
                            if tried is not None else
                            f"{action}: 이 저장소에서 한 번도 실행되지 않았습니다")
        age = now - at
        if age > timedelta(minutes=max_age_min):
            return action, (f"{action}: 마지막 성공 {ago(at, now)} "
                            f"(허용 {max_age_min}분)")

    # Everything is fresh and no question is due.  Say which clock will expire
    # first, so a supervisor tick that does nothing still explains itself.
    available = {a: m for a, m in ZERO_N_WORK.items() if a not in skip}
    if not available:
        return "rest", ("이 감독자가 할 수 있는 zero-N 작업이 없습니다 "
                        f"(제외: {', '.join(sorted(skip))})")
    soonest = min(
        ((a, (last_activity_at(a) or now) + timedelta(minutes=m))
         for a, m in available.items()), key=lambda kv: kv[1])
    return "rest", (f"모든 zero-N 작업이 최신이고 새 질문도 예정에 없습니다. "
                    f"다음은 {soonest[0]}, {until(soonest[1], now)}. "
                    f"게이트: {why}")


def main(argv: list[str]) -> int:
    """`--due` is the gate the scheduled reasoning cycle asks before running.

    Exit 0 due, 10 not due, so a shell can branch on it.  10 rather than 1
    because 1 is what the pipeline itself returns when it refuses, and a
    scheduler that retries on failure must be able to tell the two apart.

    The reconfigure is not cosmetic and it belongs here rather than at import,
    which would impose a console policy on every caller.  The reasons this
    prints are Korean prose with em dashes, a cp949 console raises on one, and
    the raise exits 1 -- which the scheduled cycle reads as "the gate could not
    be evaluated" and aborts on.  A skip message would have stopped the loop.
    """
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, OSError):                              # pragma: no cover
        pass
    if "--stamp" in argv:
        rec = stamp_reasoning()
        print(f"stamped {rec['fingerprint'][:12]} at {rec['utc']}")
        return 0
    if "--due" in argv:
        due, why = reasoning_due()
        record_gate(due, why)
        print(("DUE: " if due else "SKIP: ") + why)
        return 0 if due else 10
    if "--next" in argv:
        action, why = next_action()
        print(f"{action}: {why}")
        return 0
    a = activity()
    print(f"{a['mark']} {a['status']}  {a['headline']}")
    for r in a["reasons"]:
        print(f"  - {r}")
    return 0


if __name__ == "__main__":                                         # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
