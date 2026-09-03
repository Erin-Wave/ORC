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

# SCHED_S_TASK_HAS_NOT_RUN: registered, never yet due.  Not a failure.
NEVER_RAN = 267011


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


def _same_tree(path: str, root: Path) -> bool:
    try:
        return Path(path).resolve().is_relative_to(root.resolve())
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
    if rc == 0:
        return "ok", "마지막 실행 성공"
    if rc == NEVER_RAN:
        return "ok", "등록됐고 아직 발화 시각이 오지 않았음"
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
    queued = sorted(config.QUEUE.glob("*.json")) if config.QUEUE.exists() else []
    if queued:
        return False, (f"큐에 {len(queued)}개가 답을 기다립니다 "
                       f"({', '.join(p.stem for p in queued)}) — "
                       "워커가 가져가기 전에는 새로 묻지 않습니다")
    proposed = config.CONFIGS / "proposed"
    held = sorted(proposed.glob("*.json")) if proposed.exists() else []
    if held:
        return True, f"심사 대기 제안 {len(held)}건이 있어 먼저 판정합니다"
    fp = evidence_fingerprint()
    prev = last_reasoning()
    if prev.get("fingerprint") == fp:
        return False, (f"마지막 패스({kst(prev.get('utc'))}) 이후 증거가 "
                       "그대로입니다 — 같은 리포트에 두 번 등록하지 않습니다")
    if prev.get("fingerprint"):
        return True, f"마지막 패스({kst(prev.get('utc'))}) 이후 증거가 바뀌었습니다"
    return True, "이 저장소에서 지문이 기록된 패스가 없습니다"


# ---------------------------------------------------------------------------
# the one-line answer
# ---------------------------------------------------------------------------
RUNNING, QUEUED, IDLE, STALLED, STOPPED = (
    "RUNNING", "QUEUED", "IDLE", "STALLED", "STOPPED")
MARK = {RUNNING: "🟢", QUEUED: "🟢", IDLE: "🟡", STALLED: "🟠", STOPPED: "🔴"}
HEADLINE = {
    RUNNING: "**지금 백테스트가 돌고 있습니다.**",
    QUEUED: "**살아 있습니다** — 질문이 등록돼 다음 워커 발화에서 평가됩니다.",
    IDLE: "**살아 있지만 지금은 유휴입니다** — 다음 추론 패스가 질문을 만듭니다.",
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
        elif stale_h is None or stale_h > STALE_HOURS:
            status = STALLED
            reasons.append(f"신규 시행이 {ago(newest, now)}로 멈춰 있고 "
                           "대기 중인 질문도 없습니다 — 워커는 돌지만 "
                           "새로 묻는 것이 없습니다")
        else:
            reasons.append(f"마지막 신규 시행 {ago(newest, now)}, 큐는 비었고 "
                           "다음 추론 패스가 새 질문을 만들 차례입니다")

    facts["status"] = status
    facts["mark"] = MARK[status]
    facts["headline"] = HEADLINE[status]
    facts["reasons"] = reasons
    return facts


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
    a = activity()
    print(f"{a['mark']} {a['status']}  {a['headline']}")
    for r in a["reasons"]:
        print(f"  - {r}")
    return 0


if __name__ == "__main__":                                         # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
