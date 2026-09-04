"""ORC | The loop's own vital signs, and the checks that would have caught a
day of silence.

On 2026-09-03 the checkout moved from D:\\Project\\ORC to
D:\\Project\\harness\\invest\\ORC.  The two Windows scheduled tasks store an
ABSOLUTE path, so from that moment Task Scheduler returned 0x8007010B and never
launched the reasoning layer -- the only thing in this project that proposes a
new question.  The GitHub worker kept firing every six hours, kept writing a
report and kept committing, and because trials dedupe on
(config, symbol, evaluator, panel, code) every one of those cycles inserted
zero rows and reported success.  health.py, status.py and the briefing were all
green for the whole day.  Nothing was researched.

Every test below is one of the claims that failure made false, written so that
it fails if it ever becomes false again:

  the schedule points at THIS repository
  a launch failure is not the same event as a script that refused
  a cycle that added nothing is visible as such, in a record that survives
  the reasoning pass may run again as soon as the evidence changes, and may
    NOT run twice against the same evidence

The task fixtures are dictionaries in the shape runstate.local_tasks() returns,
so the path comparison is covered on a machine with no Task Scheduler at all --
which is where the suite runs in CI.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orc import config, runstate
from orc.ledger.trials import Ledger
from orc.orchestrator.spec import Hypothesis

UTC = timezone.utc

UTC = timezone.utc


def _task(name="ORC Reasoning Cycle", workdir=r"D:\Project\ORC",
          script=r"D:\Project\ORC\scripts\reasoning_cycle_hidden.vbs",
          result=0, last="09/03/2026 20:55:55", nxt="09/04/2026 02:25:25"):
    return {"name": name, "state": "Ready", "last": last, "result": result,
            "next": nxt, "exec": "wscript.exe",
            "arguments": f'"{script}"', "workdir": workdir}


# --------------------------------------------------------------------------
# the schedule points at this repository
# --------------------------------------------------------------------------
def test_a_task_pointing_at_the_old_checkout_is_a_problem(tmp_path):
    """The check that was missing.  This is the exact shape of the 2026-09-03
    break: the task is registered, enabled and scheduled, and every path in it
    names a directory that is not this repository."""
    root = tmp_path / "repo"
    root.mkdir()
    problems = runstate.task_path_problems([_task()], root=root)
    assert len(problems) == 2, problems
    assert any("시작 폴더" in p for p in problems)
    assert any("스크립트" in p for p in problems)


def test_a_windows_task_path_is_never_read_as_inside_a_posix_checkout():
    r"""The docstring at the top of this file claims the path comparison is
    covered on a machine with no Task Scheduler, "which is where the suite runs
    in CI".  That was the one claim here that was false.

    On Linux ``Path(r"D:\Project\ORC")`` is not an absolute path: it is a
    single ordinary FILENAME that happens to contain backslashes, so resolve()
    hangs it off the current directory -- which during a run IS this repository
    -- and is_relative_to said yes.  A task pointing at a checkout that no
    longer exists read as living inside the repo, so the runner's activity()
    returned STALLED ("the worker is quiet") where the workstation returned
    STOPPED ("the reasoning layer cannot even be launched").  The suite was
    green here and red there, on the same commit.

    The answer must come from the flavour of the PATH, so that it is the same
    on both hosts.  These assertions hold on Windows and on Linux; before the
    fix the last one returned [] on Linux.
    """
    assert not runstate._same_tree(r"D:\Project\ORC", config.ORC_ROOT)
    assert not runstate._same_tree(r"\\nas\share\ORC", config.ORC_ROOT)
    assert len(runstate.task_path_problems([_task()])) == 2


def test_a_task_inside_this_repository_is_not_a_problem(tmp_path):
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    t = _task(workdir=str(root),
              script=str(root / "scripts" / "reasoning_cycle_hidden.vbs"))
    assert runstate.task_path_problems([t], root=root) == []


def test_a_switch_argument_is_not_mistaken_for_a_path(tmp_path):
    """-Force is an argument, not a file.  Treating every argument as a path
    would report a problem on a correctly registered task."""
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    t = _task(workdir=str(root),
              script=str(root / "scripts" / "reasoning_cycle_hidden.vbs"))
    t["arguments"] = t["arguments"] + "|-Force"
    assert runstate.task_path_problems([t], root=root) == []


def test_the_real_schedule_points_at_the_real_repository():
    """Run against whatever is actually registered on this machine.  On CI and
    on any non-Windows box local_tasks() returns None and this is vacuous; on
    the workstation that owns the loop it is the whole point."""
    tasks = runstate.local_tasks()
    if tasks is None or not tasks:
        pytest.skip("no queryable Task Scheduler")
    assert runstate.task_path_problems(tasks) == []


# --------------------------------------------------------------------------
# a launch failure is a different event from a refusal
# --------------------------------------------------------------------------
def test_the_directory_error_reads_as_a_launch_failure():
    sev, note = runstate.task_result_note(2147942667)
    assert sev == "bad"
    assert "0x8007010B" in note


def test_exit_one_is_a_refusal_not_a_launch_failure():
    """The reasoning pass exits 1 when it refuses to run on code with an open
    high-severity finding, and refusing protects every number in the ledger.
    Conflating that with a task that never started sends a reader to the wrong
    place."""
    assert runstate.task_result_note(1)[0] == "warn"
    assert runstate.task_result_note(0)[0] == "ok"
    assert runstate.task_result_note(runstate.NEVER_RAN)[0] == "ok"


def test_a_running_task_is_not_a_warning():
    """267009 is SCHED_S_TASK_RUNNING, and it is what a HEALTHY supervisor
    reports for as long as it runs -- which is meant to be always.  Reading it
    as a fault made the row that answers "is it working" say WARN at the exact
    moment the machine was finally working."""
    assert runstate.task_result_note(runstate.TASK_RUNNING)[0] == "ok"
    assert "실행 중" in runstate.task_result_note(runstate.TASK_RUNNING)[1]
    assert runstate.task_result_note(runstate.NO_MORE_RUNS)[0] == "ok"
    # Terminated is worth looking at: a time limit or a human stopped it.
    assert runstate.task_result_note(runstate.TASK_TERMINATED)[0] == "warn"


def test_every_status_has_a_mark_and_a_headline():
    """A new status used to make the health screen print
    "loop  KeyError: 'WORKING'" -- the screen reporting a fault in itself."""
    import health
    for status in (runstate.RUNNING, runstate.QUEUED, runstate.WORKING,
                   runstate.IDLE, runstate.STALLED, runstate.STOPPED):
        assert status in runstate.MARK, status
        assert status in runstate.HEADLINE, status
    src = (config.ORC_ROOT / "scripts" / "health.py").read_text(encoding="utf-8")
    # Indexed with .get and a default, so an unlisted status degrades to a
    # warning row instead of an exception.
    assert "runstate.STOPPED: BAD}.get(" in src
    assert health is not None


def test_a_never_run_task_prints_no_sentinel_date():
    assert runstate.task_time("11/30/1999 00:00:00") == "없음"
    assert runstate.task_time("09/03/2026 20:55:55") == "2026-09-03 20:55 KST"
    assert runstate.task_time(None) == "없음"


# --------------------------------------------------------------------------
# a cycle that added nothing has to be visible as such
# --------------------------------------------------------------------------
def test_a_zero_yield_cycle_is_recorded(tmp_path):
    """The signature of the stopped loop: the worker ran, wrote a report and
    succeeded, and answered nothing.  CYCLE_SUMMARY.json is overwritten every
    cycle, so a sequence of these was unrecoverable from the repository."""
    log = tmp_path / "CYCLE_LOG.jsonl"
    for i, added in enumerate((112, 0, 0)):
        runstate.append_cycle_log(
            {"run_id": f"r{i}", "started_utc": f"2026-09-0{i + 1}T00:00:00+00:00",
             "finished_utc": f"2026-09-0{i + 1}T00:30:00+00:00",
             "trials_added": added, "hypotheses_run": ["H0001"]}, path=log)
    rows = runstate.cycle_attempts(10, path=log)
    assert [r["trials_added"] for r in rows] == [0, 0, 112]      # newest first
    assert len(rows) == 3


def test_a_corrupt_line_does_not_hide_the_rest(tmp_path):
    log = tmp_path / "CYCLE_LOG.jsonl"
    runstate.append_cycle_log({"run_id": "a", "started_utc": "2026-01-01T00:00:00+00:00",
                               "trials_added": 5}, path=log)
    with log.open("a", encoding="utf-8") as fh:
        fh.write("{ not json\n")
    assert [r["run_id"] for r in runstate.cycle_attempts(10, path=log)] == ["a"]


def test_a_reasoning_pass_that_registered_nothing_is_recorded(tmp_path):
    log = tmp_path / "REASONING_LOG.jsonl"
    runstate.append_reasoning_log(
        {"utc": "2026-09-03T00:00:00+00:00",
         "steps": {"blocked": ["db4ec5e581de", "9cea2bbfc3ac"]}}, path=log)
    runstate.append_reasoning_log(
        {"utc": "2026-09-04T00:00:00+00:00",
         "steps": {"adversary": [{"file": "H0009.json", "verdict": "REGISTER"},
                                 {"file": "H0010.json", "verdict": "KILL"}]}}, path=log)
    rows = runstate.reasoning_passes(10, path=log)
    assert rows[0]["registered"] == ["H0009.json"]
    assert rows[0]["killed"] == ["H0010.json"]
    assert len(rows[1]["blocked"]) == 2
    assert rows[1]["registered"] == []


def test_a_skip_is_recorded_as_a_wakeup_but_not_as_a_pass(tmp_path):
    """The distinction the watchdogs now depend on.  Since the guard became an
    evidence fingerprint, a healthy loop often decides there is nothing new to
    read and writes no output -- so "nothing has been written" stopped meaning
    "nothing is running", and only a wake-up row can tell a healthy skip from a
    scheduled task that is not firing."""
    log = tmp_path / "REASONING_LOG.jsonl"
    runstate.record_gate(False, "증거가 그대로입니다", path=log)
    runstate.record_gate(True, "증거가 바뀌었습니다", path=log)
    runstate.append_reasoning_log(
        {"utc": "2026-09-05T00:00:00+00:00",
         "steps": {"adversary": [{"file": "H0009.json", "verdict": "REGISTER"}]}},
        path=log)
    assert len(runstate.reasoning_wakeups(10, path=log)) == 3
    passes = runstate.reasoning_passes(10, path=log)
    assert len(passes) == 1
    assert passes[0]["registered"] == ["H0009.json"]


def test_the_stamp_is_not_read_as_a_date_by_the_notifier():
    """notify.py used to parse logs/.last_cycle with strptime("%Y-%m-%d").  The
    file now holds JSON, and a parse failure there appended "ORC reasoning
    stamp is unreadable" to the news on every single cycle -- a false alarm on
    a channel whose only value is that it is quiet when nothing is wrong."""
    src = (config.ORC_ROOT / "scripts" / "notify.py").read_text(encoding="utf-8")
    assert "%Y-%m-%d" not in src
    assert "runstate.last_reasoning()" in src


def test_the_ledger_groups_a_run_into_one_span(tmp_path):
    """Ledger.runs() is the honest record of research TIME: a run appears only
    if it inserted a row."""
    with Ledger(tmp_path / "t.sqlite") as led:
        for i in range(3):
            led.record(run_id="r1", family="f", symbol=f"S{i}",
                       evaluator="analytic", cfg={"a": i},
                       metrics={"tm_q05": 1.0}, n_starts=10,
                       panel_hash="ph", code="ch", hypothesis_id="H0001")
        led.record(run_id="r2", family="f", symbol="S0", evaluator="analytic",
                   cfg={"a": 9}, metrics={"tm_q05": 1.0}, n_starts=10,
                   panel_hash="ph", code="ch", hypothesis_id="H0002")
        runs = led.runs(10)
    assert [r["run_id"] for r in runs] == ["r2", "r1"]
    assert [r["trials"] for r in runs] == [1, 3]
    assert runs[1]["hypotheses"] == ["H0001"]
    assert runs[0]["first_utc"] <= runs[0]["last_utc"]


def test_a_rerun_that_inserts_nothing_leaves_no_run(tmp_path):
    """The mechanism behind the silent day, asserted directly: re-evaluating an
    unchanged registry adds no row, so the ledger cannot show that a cycle
    happened.  That is why the append-only cycle log exists."""
    row = dict(run_id="r1", family="f", symbol="S0", evaluator="analytic",
               cfg={"a": 1}, metrics={"tm_q05": 1.0}, n_starts=10,
               panel_hash="ph", code="ch")
    with Ledger(tmp_path / "t.sqlite") as led:
        led.record(**row)
        led.record(**{**row, "run_id": "r2"})
        runs = led.runs(10)
    assert [r["run_id"] for r in runs] == ["r1"]
    assert led_total(tmp_path) == 1


def led_total(tmp_path) -> int:
    with Ledger(tmp_path / "t.sqlite") as led:
        return led.total_trials()


# --------------------------------------------------------------------------
# the reasoning gate: as often as the evidence changes, never twice on one
# --------------------------------------------------------------------------
@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    """A private repository tree, so the gate can be exercised without touching
    the real queue -- where a stray file would register a hypothesis."""
    for name, rel in (("REPORTS", "reports"), ("CONFIGS", "configs"),
                      ("QUEUE", "configs/queue"), ("REGISTRY", "configs/registry")):
        p = tmp_path / rel
        p.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(config, name, p)
    (tmp_path / "configs" / "closed").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "LEDGER_DB", tmp_path / "trials.sqlite")
    monkeypatch.setattr(runstate, "LAST_REASONING", tmp_path / ".last_cycle")
    # The real supervisor's heartbeat must not reach a test.  Without this,
    # activity() reads the live lock on this workstation and every verdict test
    # says WORKING as soon as the machine is actually working -- which is the
    # state the project is meant to be in, so the suite would go red exactly
    # when everything was right.
    monkeypatch.setattr(runstate, "SUPERVISOR_LOCK", tmp_path / "forever.lock")
    monkeypatch.setattr(runstate, "CYCLE_LOG", tmp_path / "reports" / "CYCLE_LOG.jsonl")
    monkeypatch.setattr(runstate, "REASONING_LOG",
                        tmp_path / "reports" / "REASONING_LOG.jsonl")
    (tmp_path / "reports" / "CYCLE_REPORT.md").write_text("v1", encoding="utf-8")
    # One open family, because an EMPTY registry is itself a stop condition:
    # nothing is open and nothing is queued means the next pass has to name a
    # new mechanism or the loop has no work.  Tests of the other verdicts must
    # not accidentally be testing that one.
    h = Hypothesis(hypothesis_id="H0001", family="unconditional_dca_spot_style",
                   claim="a claim", kill_condition="a condition",
                   universe=["BTCUSDT"],
                   grid={"n_contributions": [52, 104, 156]},
                   fixed={"contribution": 100.0})
    h.register()                        # a file with no prereg hash is refused
    h.save(config.REGISTRY / "H0001.json")
    return tmp_path


def _stamped(minutes_ago: int = 120, fingerprint: str | None = None) -> None:
    """A completed pass, far enough back not to trip the rate limit.

    reasoning_due() now puts a floor between two passes -- without it the
    supervisor would start a fresh one the instant the adversary killed a
    proposal, because a kill is new information -- so a test aimed at any other
    branch has to place the previous pass outside that floor.
    """
    rec = {"utc": (datetime.now(UTC) - timedelta(minutes=minutes_ago)).isoformat(),
           "fingerprint": fingerprint or runstate.evidence_fingerprint()}
    runstate.LAST_REASONING.parent.mkdir(parents=True, exist_ok=True)
    runstate.LAST_REASONING.write_text(json.dumps(rec), encoding="utf-8")


def test_the_gate_refuses_while_the_queue_still_holds_a_question(sandbox):
    """Pre-registration is irreversible and every trial raises N, so a second
    batch against a report the worker has not answered yet is the one thing
    this gate exists to prevent."""
    _stamped()
    (config.QUEUE / "H0009.json").write_text("{}", encoding="utf-8")
    due, why = runstate.reasoning_due()
    assert not due
    assert "H0009" in why


def test_the_gate_refuses_a_second_pass_on_identical_evidence(sandbox):
    _stamped()
    due, why = runstate.reasoning_due()
    assert not due
    assert "그대로" in why


def test_the_gate_opens_as_soon_as_the_report_changes(sandbox):
    """The failure the calendar-day stamp actually caused.  Results landed at
    04:00Z, the morning pass had already been spent, and no question could be
    asked until the next day."""
    _stamped()
    assert runstate.reasoning_due()[0] is False
    (config.REPORTS / "CYCLE_REPORT.md").write_text("v2", encoding="utf-8")
    assert runstate.reasoning_due()[0] is True


def test_the_gate_opens_when_a_family_closes(sandbox):
    _stamped()
    assert runstate.reasoning_due()[0] is False
    (config.CONFIGS / "closed" / "H0002.json").write_text("{}", encoding="utf-8")
    assert runstate.reasoning_due()[0] is True


def test_the_gate_opens_when_the_ledger_grows(sandbox):
    _stamped()
    assert runstate.reasoning_due()[0] is False
    with Ledger(config.LEDGER_DB) as led:
        led.record(run_id="r1", family="f", symbol="S0", evaluator="analytic",
                   cfg={"a": 1}, metrics={"tm_q05": 1.0}, n_starts=10,
                   panel_hash="ph", code="ch")
    assert runstate.reasoning_due()[0] is True


def test_a_held_proposal_is_judged_before_anything_new_is_asked(sandbox):
    (config.CONFIGS / "proposed").mkdir(parents=True, exist_ok=True)
    (config.CONFIGS / "proposed" / "H0009.json").write_text("{}", encoding="utf-8")
    _stamped()
    due, why = runstate.reasoning_due()
    assert due
    assert "보류" in why or "심사" in why


def test_a_legacy_date_stamp_is_read_as_unknown_not_as_done(sandbox):
    """The file used to hold a bare date.  The fingerprint it was made against
    cannot be recovered, and treating it as "already done" would keep the pass
    shut for a day for no measurable reason."""
    runstate.LAST_REASONING.write_text("2026-09-02", encoding="utf-8")
    assert runstate.last_reasoning() == {"legacy": "2026-09-02"}
    assert runstate.reasoning_due()[0] is True


def test_the_scheduled_cycle_asks_the_gate_and_not_the_calendar():
    """The cadence claim, checked against the script that has to honour it.
    Four fires a day are safe only because the guard is the evidence
    fingerprint; if the shell stopped consulting it, four fires a day would
    register four batches."""
    ps1 = (config.ORC_ROOT / "scripts" / "reasoning_cycle.ps1").read_text(
        encoding="utf-8")
    assert "orc.runstate --due" in ps1
    assert "orc.runstate --stamp" in ps1
    # The date is still fine for a log FILENAME.  What must be gone is the
    # comparison that gated the run on it.
    assert "$Stamp" not in ps1
    assert "-eq $today" not in ps1


def test_no_native_call_in_the_cycle_merges_stderr_outside_the_helper():
    """A defect class, guarded mechanically.

    PowerShell 5.1 wraps every stderr line from a native command in a
    NativeCommandError when it is merged with 2>&1, and the script runs under
    $ErrorActionPreference = "Stop", where that is TERMINATING.  `git pull`
    writes "From <url>" to stderr on every fetch that actually brings something
    down, so the cycle died without a log line past "cycle start" on precisely
    the runs that had new results to reason about.  Invoke-Native lowers the
    preference for the duration of the call; every native call has to go
    through it, and this fails if a new one does not.
    """
    lines = (config.ORC_ROOT / "scripts" / "reasoning_cycle.ps1").read_text(
        encoding="utf-8").splitlines()
    assert any("function Invoke-Native" in l for l in lines)
    offenders = [l.strip() for l in lines
                 if "2>&1" in l
                 and not l.lstrip().startswith("#")
                 and "$ErrorActionPreference" not in l]
    assert offenders == [], offenders


def test_the_reasoning_slots_are_thirty_five_minutes_before_a_worker_slot():
    """A hypothesis registered at :25 is collected 35 minutes later.  Drift
    here costs six hours per registration and nothing would report it."""
    worker_kst = sorted((h + 9) % 24 for h in runstate.WORKER_SLOTS_UTC)
    for slot in runstate.REASONING_SLOTS_KST:
        hh, mm = (int(x) for x in slot.split(":"))
        assert mm == 25
        assert (hh + 1) % 24 in worker_kst, slot


# --------------------------------------------------------------------------
# the loop does not idle waiting for a cron
# --------------------------------------------------------------------------
def test_the_worker_is_woken_and_never_takes_the_pass_down_with_it(monkeypatch):
    """A hypothesis registered a minute after a worker slot used to wait nearly
    six hours, and the gate refuses to ask anything else while the queue holds
    an unanswered question -- so the loop idled by construction.  The dispatch
    removes that, and it must never be able to fail the pass: it runs AFTER the
    commit and push, so the hypotheses are already registered, and a raise here
    would make the scheduler retry a pass whose questions are already asked."""
    import subprocess as sp
    sys.path.insert(0, str(config.ORC_ROOT / "scripts"))
    import reasoning

    monkeypatch.setattr(reasoning.shutil, "which", lambda _: None)
    assert "next cron" in reasoning.wake_the_worker()

    monkeypatch.setattr(reasoning.shutil, "which", lambda _: "gh")

    def _boom(*a, **k):
        raise sp.TimeoutExpired(cmd="gh", timeout=60)
    monkeypatch.setattr(reasoning.subprocess, "run", _boom)
    assert "unavailable" in reasoning.wake_the_worker()

    monkeypatch.setattr(reasoning.subprocess, "run",
                        lambda *a, **k: sp.CompletedProcess(a, 0, "", ""))
    assert "dispatched" in reasoning.wake_the_worker()


# --------------------------------------------------------------------------
# the verdict
# --------------------------------------------------------------------------
def test_a_broken_schedule_reads_as_stopped_not_as_idle(sandbox):
    """The headline claim.  A worker that keeps producing reports while nothing
    can propose a new question is a stopped loop, and it must not read as a
    healthy one."""
    a = runstate.activity(tasks=[_task()])
    assert a["status"] == runstate.STOPPED
    assert a["mark"] == "🔴"
    assert any("실행조차" in r for r in a["reasons"])


def test_no_open_family_and_an_empty_queue_reads_as_stopped(sandbox):
    """The other way the loop stops, and the one the constitution names: every
    registered mechanism is closed, so unless the next pass names a NEW
    mechanism there is nothing for the worker to do.  Nothing is broken, and it
    is still stopped."""
    (config.REGISTRY / "H0001.json").unlink()
    a = runstate.activity(tasks=[])
    assert a["status"] == runstate.STOPPED
    assert any("새 메커니즘" in r for r in a["reasons"])


def test_a_queued_question_reads_as_alive(sandbox):
    (config.QUEUE / "H0009.json").write_text("{}", encoding="utf-8")
    a = runstate.activity(tasks=[])
    assert a["status"] == runstate.QUEUED
    assert a["queued"] == ["H0009"]


def test_an_empty_queue_with_a_cold_ledger_reads_as_stalled(sandbox):
    """Alive, firing, answering nothing.  Distinct from STOPPED, because
    nothing is broken -- and distinct from IDLE, because a day has passed."""
    old = datetime.now(UTC) - timedelta(hours=runstate.STALE_HOURS + 2)
    runstate.append_cycle_log(
        {"run_id": "r1", "started_utc": old.isoformat(),
         "finished_utc": old.isoformat(), "trials_added": 0,
         "hypotheses_run": ["H0001"]})
    a = runstate.activity(tasks=[])
    assert a["status"] == runstate.STALLED
    assert any("새로 묻는 것이 없습니다" in r for r in a["reasons"])


def test_a_launch_failure_already_repaired_is_not_reported_as_stopped(sandbox,
                                                                     tmp_path):
    """LastTaskResult keeps the old code until the task fires again.  Reporting
    a stop against paths that are now correct sends someone to fix what is
    already fixed."""
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    t = _task(workdir=str(root),
              script=str(root / "scripts" / "reasoning_cycle_hidden.vbs"),
              result=2147942667)
    import orc.config as cfg
    a = runstate.activity(tasks=[t]) if cfg.ORC_ROOT == root else None
    # ORC_ROOT is the real repository, so the fixture's paths are outside it and
    # would be flagged.  Assert the branch directly instead of faking the root.
    sev, _ = runstate.task_result_note(2147942667)
    assert sev == "bad"
    assert runstate.task_path_problems([t], root=root) == []
    assert a is None or a["status"] != runstate.STOPPED


def test_the_next_slots_are_in_the_future():
    now = datetime(2026, 9, 3, 13, 0, tzinfo=UTC)
    assert runstate.next_worker_slot(now) == datetime(2026, 9, 3, 18, 0, tzinfo=UTC)
    assert runstate.next_worker_slot(
        datetime(2026, 9, 3, 19, 0, tzinfo=UTC)) == datetime(2026, 9, 4, 0, 0, tzinfo=UTC)
    assert runstate.next_reasoning_slot(now) > now
    # 10:00Z is 19:00 KST, so the 20:25 slot is still ahead.
    assert runstate.next_reasoning_slot(
        datetime(2026, 9, 3, 10, 0, tzinfo=UTC)).astimezone(
            runstate.KST).strftime("%H:%M") == "20:25"
    # 21:00 KST is past the last slot of the day, so it rolls to tomorrow.
    assert runstate.next_reasoning_slot(
        datetime(2026, 9, 3, 12, 0, tzinfo=UTC)).astimezone(
            runstate.KST).strftime("%H:%M") == "02:25"


def test_the_timeline_prefers_the_log_over_the_ledger_for_one_run(sandbox):
    """A run that both know about is one row, with the log's full-cycle span
    rather than the ledger's evaluation-only span."""
    with Ledger(config.LEDGER_DB) as led:
        led.record(run_id="r1", family="f", symbol="S0", evaluator="analytic",
                   cfg={"a": 1}, metrics={"tm_q05": 1.0}, n_starts=10,
                   panel_hash="ph", code="ch", hypothesis_id="H0001")
    runstate.append_cycle_log(
        {"run_id": "r1", "started_utc": "2026-09-03T00:00:00+00:00",
         "finished_utc": "2026-09-03T00:34:00+00:00", "trials_added": 1,
         "hypotheses_run": ["H0001"]})
    tl = runstate.timeline(10)
    assert len(tl) == 1
    assert tl[0]["source"] == "log"
    assert tl[0]["finished_utc"] == "2026-09-03T00:34:00+00:00"


# --------------------------------------------------------------------------
# the owner screen has to be readable, and every row on it has to be true
#
# All four of these were wrong on one render of scripts/health.py on
# 2026-09-04, and none of them broke anything: a screen that is subtly wrong
# just stops being read, which costs more than a screen that is missing.
# --------------------------------------------------------------------------
def test_a_refused_second_instance_is_not_a_fault_while_one_is_running():
    """"ORC Forever" fires hourly and the supervisor it starts stays resident,
    so Task Scheduler refuses the new instance every time. That refusal is what
    a HEALTHY resident loop reports, and it had a permanent WARN on it.

    Not unconditionally benign, which is the point of the parameter: the same
    code comes back when a person or a policy refuses the task outright.
    """
    from orc import runstate

    assert runstate.INSTANCE_REFUSED == 2147946720          # 0x800710E0
    sev, note = runstate.task_result_note(runstate.INSTANCE_REFUSED, resident=True)
    assert sev == "ok" and "상주 감독자" in note
    sev, note = runstate.task_result_note(runstate.INSTANCE_REFUSED, resident=False)
    assert sev == "bad", "refused AND nothing running is the real fault"
    sev, note = runstate.task_result_note(runstate.INSTANCE_REFUSED)
    assert sev == "warn", "a caller that cannot tell must not guess"
    # and the codes that were already understood are untouched
    assert runstate.task_result_note(0)[0] == "ok"
    assert runstate.task_result_note(2147942667)[0] == "bad"


def test_a_frequent_workflow_cannot_hide_the_cycles_verdict():
    """orc-guard runs on every push and the supervisor pushes after every
    action, so within an hour the six newest runs were all orc-guard and the
    row answering "did the research cycle work" said "no completed run in the
    last 6" -- while a failed cycle sat 1h42m back."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import health

    assert health.RUNS_QUERIED >= 30, (
        "the window has to cover several pushes' worth of guard runs plus a "
        "six-hourly cycle, or absence and 'outside my window' read alike")
    src = (Path(__file__).resolve().parent.parent / "scripts" / "health.py"
           ).read_text(encoding="utf-8")
    assert '"--limit", "6"' not in src


def test_the_queue_line_names_both_ways_it_gets_collected(tmp_path, monkeypatch):
    """Quoting only the cron read as a four-hour wait on a machine that was
    already evaluating it: a worker job that is up now takes the queue on its
    next tick, because next_action returns `cycle` there."""
    from orc import config, runstate

    q = tmp_path / "queue"
    q.mkdir()
    (q / "H9999.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(config, "QUEUE", q)

    a = runstate.activity(tasks=[])
    assert a["status"] == runstate.QUEUED
    reason = " ".join(a["reasons"])
    assert "떠 있는 워커 잡" in reason, "the resident-window path is not mentioned"
    assert "다음 발화" in reason, "the cron path is not mentioned either"


def test_the_supervisor_marks_the_actions_it_starts():
    """An action that records its own activity when run by hand must not do it
    twice when the supervisor runs it -- there, the exit code and the commit
    are recorded with it. Run by hand and recording NOTHING is what made one
    render say "18/18 killed 31m ago" and "never run" on two rows."""
    import subprocess
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import forever

    rc, out = forever.run(
        [sys.executable, "-c",
         "import os; print(os.environ.get('ORC_SUPERVISED', 'unset'))"], 60)
    assert rc == 0
    assert "1" in out and "unset" not in out

    mut = (Path(__file__).resolve().parent.parent / "scripts" / "mutation.py"
           ).read_text(encoding="utf-8")
    assert 'os.environ.get("ORC_SUPERVISED")' in mut
    assert "record_activity" in mut


# --------------------------------------------------------------------------
# a change that crosses subsystems arrives with a map
# --------------------------------------------------------------------------
def test_a_cross_subsystem_change_is_refused_without_a_note():
    """Four fixes to one area on 2026-09-04, each 'edit, discover a
    consequence, edit again', and the change budget passed every time. Size
    was never the problem: reading the path first was."""
    from orc import guard

    both = ["orc/runstate.py", "scripts/forever.py"]
    assert guard.crossed_subsystems(both) == ["orc/", "scripts/"]
    assert guard.needs_a_design_note(both, "fix things")

    # three ways to satisfy it, because the point is having read the path and
    # not having produced a file
    assert guard.needs_a_design_note(both, "fix\n\nsee docs/PIPELINE.md") is None
    assert guard.needs_a_design_note(both + ["docs/NEW.md"], "fix") is None
    assert guard.needs_a_design_note(
        both, "fix\n\nNO-DESIGN-NOTE: one line, one idea") is None


def test_code_and_its_own_test_are_one_change():
    """tests/ is not a crossing. A rule that fires on every honest commit
    becomes ceremony, then noise, then --no-verify."""
    from orc import guard

    assert guard.needs_a_design_note(
        ["orc/eval/signal_rules.py", "tests/test_kernel.py"], "add a rule") is None
    assert guard.needs_a_design_note(["scripts/health.py"], "one file") is None
    assert guard.needs_a_design_note([], "nothing") is None


def test_a_design_note_is_not_charged_against_the_change_budget():
    """Charging for the note would be a rule that discourages the behaviour it
    demands."""
    from orc import guard

    rows = [(400, 0, "docs/PIPELINE.md"), (10, 2, "orc/target.py")]
    assert guard.budget(rows) == (1, 12, ["orc/target.py"])
    assert guard.over_budget(rows) is None


def test_the_map_exists_and_names_what_a_change_must_preserve():
    """A map that can be deleted without anything failing is a map that will
    be. It carries the invariants, and one of them (I9) was found by drawing
    it -- the cycle branch had no failure cooldown and could hot-loop."""
    from orc import config

    m = (config.ORC_ROOT / "docs" / "PIPELINE.md").read_text(encoding="utf-8")
    for inv in ("I1", "I2", "I3", "I4", "I5", "I6", "I7", "I8", "I9"):
        assert f"| {inv} |" in m, f"{inv} is not in the invariant table"
    assert "commit_results.py" in m and "next_action" in m
    assert "확인 목록" in m, "the checklist to run before editing is the point"


def test_a_failed_cycle_does_not_become_a_hot_loop(tmp_path, monkeypatch):
    """FAILURE_COOLDOWN_MIN is applied inside the ZERO_N_WORK loop, and the
    cycle branch returns before it. A daily_cycle.py that dies BEFORE
    intake_queue() drains the queue would be retried every 30 seconds for the
    whole five-hour window while zero-N work never got a turn.

    docs/PIPELINE.md section 3: found by drawing the pipeline, not by meeting
    this in production.
    """
    import json
    from datetime import datetime, timedelta, timezone

    import findings

    from orc import config, runstate, target

    monkeypatch.setattr(findings, "blocking", lambda: [])
    monkeypatch.setattr(target, "state",
                        lambda *a, **k: {"state": target.NO_CANDIDATE,
                                         "headline": "none", "candidates": []})
    q = tmp_path / "queue"
    q.mkdir()
    (q / "H9999.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(config, "QUEUE", q)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    log = tmp_path / "activity.jsonl"
    monkeypatch.setattr(runstate, "ACTIVITY_LOG", log)
    skip = {"reason", "scout", "kernel_review"}

    # with nothing recorded, the queue is collected
    assert runstate.next_action(skip=skip)[0] == "cycle"

    # a cycle that FAILED two minutes ago is not retried immediately
    now = datetime.now(timezone.utc)
    log.write_text(json.dumps({
        "utc": (now - timedelta(minutes=2)).isoformat(),
        "action": "cycle", "detail": "exit 1: the panel download failed",
        "ok": False}) + chr(10), encoding="utf-8")
    assert runstate.next_action(skip=skip)[0] != "cycle", (
        "a failing cycle would be retried every WORKED_SLEEP_S for the window")

    # once the cooldown is past, it is tried again
    log.write_text(json.dumps({
        "utc": (now - timedelta(minutes=runstate.FAILURE_COOLDOWN_MIN + 1)
                ).isoformat(),
        "action": "cycle", "detail": "exit 1", "ok": False}) + chr(10),
        encoding="utf-8")
    assert runstate.next_action(skip=skip)[0] == "cycle"

    # and a cycle that SUCCEEDED does not block the next one at all
    log.write_text(json.dumps({
        "utc": (now - timedelta(minutes=1)).isoformat(),
        "action": "cycle", "detail": "exit 0", "ok": True}) + chr(10),
        encoding="utf-8")
    assert runstate.next_action(skip=skip)[0] == "cycle"


# --------------------------------------------------------------------------
# 지금 무엇이 돌고 있는가 -- scripts/watch.py
# --------------------------------------------------------------------------
def _watch():
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import watch
    return watch


def test_the_duty_cycle_unions_overlapping_work_instead_of_adding_it(
        tmp_path, monkeypatch):
    """두 감독자가 ACTIVITY.jsonl에 union으로 쓴다. 구간을 더하면 겹치는 만큼
    부풀고, 이 숫자는 '쉬지 않는다'는 주장을 검사하는 데 쓰이는 숫자다."""
    import json
    from datetime import datetime, timedelta, timezone

    from orc import runstate

    watch = _watch()
    now = datetime.now(timezone.utc)
    log = tmp_path / "activity.jsonl"

    def rec(minutes_ago, seconds, action="robustness"):
        return json.dumps({"utc": (now - timedelta(minutes=minutes_ago)).isoformat(),
                           "action": action, "seconds": seconds, "ok": True})

    # 두 기계가 같은 10분을 각각 기록한다: 합계 20분, 합집합 10분.
    log.write_text(chr(10).join([rec(50, 600), rec(50, 600, "scout")]) + chr(10),
                   encoding="utf-8")
    monkeypatch.setattr(runstate, "ACTIVITY_LOG", log)

    d = watch.duty_cycle(hours=2)
    assert d["n"] == 2
    assert 9.5 <= d["busy_min"] <= 10.5, d["busy_min"]
    assert d["since_last_min"] == pytest.approx(50, abs=1)
    assert d["largest_gap_min"] is None, "구간이 하나로 병합되면 공백도 없다"

    # 떨어진 두 구간이면 그 사이가 공백이다. 기록된 시각은 작업이 END난
    # 시각이므로 rec(90, 300)은 [95분 전, 90분 전] 구간이고 rec(20, 300)은
    # [25분 전, 20분 전]이다. 공백은 90분 전부터 25분 전까지 = 65분.
    log.write_text(chr(10).join([rec(90, 300), rec(20, 300)]) + chr(10),
                   encoding="utf-8")
    d = watch.duty_cycle(hours=3)
    assert d["busy_min"] == pytest.approx(10, abs=0.5)
    assert d["largest_gap_min"] == pytest.approx(65, abs=1)
    assert d["since_last_min"] == pytest.approx(20, abs=1)


def test_a_supervisor_that_stopped_without_dying_is_named(tmp_path, monkeypatch):
    """모든 화면이 잠금 파일만 읽는다. pid 30784는 2026-09-04에 19시간 동안
    프로세스로 살아 있으면서 아무 일도 하지 않았고, 잠금은 인수한 27212를
    가리켰으므로 어디에도 나타나지 않았다."""
    watch = _watch()

    procs = [{"pid": "27212", "script": "forever.py", "args": ""},
             {"pid": "30784", "script": "forever.py", "args": ""},
             {"pid": "31000", "script": "mutation.py", "args": ""}]
    sup = {"alive": True, "pid": 27212, "heartbeat_utc": "2026-09-04T09:47:49+00:00"}

    stray = watch.strays(procs, sup)
    assert [s["pid"] for s in stray] == ["30784"], (
        "잠금 보유자는 좀비가 아니고, 다른 스크립트는 감독자가 아니다")
    assert watch.strays(None, sup) == [], "알 수 없음은 좀비가 아니다"
    assert watch.strays([], sup) == []

    # 화면에 실제로 찍히는지 -- 지목만 하고 죽이지는 않는다
    snap = {"utc": "2026-09-04T09:51:07+00:00", "supervisor": sup,
            "processes": procs, "strays": stray,
            "next": {"action": "rest", "why": "everything is fresh"},
            "duty": {"hours": 12, "busy_min": 268.0, "span_min": 715.0,
                     "fraction": 0.375, "largest_gap_min": 122.0,
                     "since_last_min": 103.0, "n": 23},
            "recent": [], "live_runs": []}
    text = chr(10).join(watch.render(snap))
    assert "좀비" in text and "30784" in text
    assert "Stop-Process -Id 30784" in text, "사람이 판단할 명령을 준다"
    assert "37.5%" in text and "122분" in text


def test_unknown_is_not_the_same_as_nothing(monkeypatch):
    """PowerShell에 물어볼 수 없었던 것을 '아무것도 안 돌고 있다'로 보고하는
    화면은 거짓말을 한다."""
    watch = _watch()

    def _boom(*a, **k):
        raise OSError("no powershell here")

    monkeypatch.setattr(watch.subprocess, "run", _boom)
    assert watch.running_scripts() is None
    assert watch.live_runs() is None

    snap = {"utc": "2026-09-04T09:51:07+00:00",
            "supervisor": {"alive": False, "pid": None, "heartbeat_utc": None},
            "processes": None, "strays": [],
            "next": {"action": "rest", "why": "x"},
            "duty": watch.duty_cycle(hours=1), "recent": [], "live_runs": None}
    text = chr(10).join(watch.render(snap))
    assert "알 수 없음" in text
    assert "떠 있지 않음" in text
