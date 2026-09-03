"""ORC | The supervisor: what it may spend, and that it always has work.

The loop used to have exactly one way to make progress -- fire the reasoning
layer, once a day, ask a new question -- and two idle states built in around
it.  On 2026-09-03 the project sat in both: the adversary killed both proposals
(H0009 as a finer grid over closed H0007, H0010 for misreading a metric, both
correct), the day's single registration slot was spent, and the worker went on
firing every six hours inserting zero rows.

Running continuously is only safe because of one line -- MAX_REGISTRATIONS_PER_
DAY -- so that is what most of this file is about.  Proposing is free: a killed
proposal is a file in configs/killed/ and zero rows in the ledger.  REGISTERING
is irreversible and raises the multiple-testing bar for every result the
project will ever produce, and with the queue-empty rule alone the rate would
be bounded only by how fast the worker can clear a queue -- about thirty a day.

The rest of this file asserts the other half of the claim: that "never idle" is
true because there is always zero-N work available, and that every action the
supervisor can choose is one it can actually execute.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from orc import config, runstate
from orc.orchestrator.spec import Hypothesis

UTC = timezone.utc
ZERO_N_LONGEST = max(runstate.ZERO_N_WORK.values())


@pytest.fixture(autouse=True)
def never_touch_the_real_machine(tmp_path, monkeypatch):
    """Autouse, because being careful per-test was not enough.

    An earlier draft of test_an_inapplicable_action_still_resets_its_clock
    called forever.tick() without pinning next_action.  next_action chose
    `reason`, tick() ran the real pipeline for 8.9 minutes, and it pulled,
    committed and pushed -- from inside `pytest`.  It registered nothing, so
    the damage was a stray commit rather than a stray hypothesis, but the same
    accident one branch over spends a registration slot and raises N forever.

    So the two ways out of a test are closed here for every test in the file:
    subprocess.run cannot be reached, and the supervisor's log cannot be
    written to the real logs/ directory.
    """
    import forever
    monkeypatch.setattr(forever, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(forever, "LOCK", tmp_path / "logs" / "forever.lock")

    def _refuse(*a, **k):
        raise AssertionError(
            f"a test tried to run a subprocess: {a[:1]}. Pin what you are "
            "testing; the suite must not be able to start a research pass.")
    monkeypatch.setattr(forever.subprocess, "run", _refuse)
    yield


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    """A private tree.  The real configs/queue/ must never be touched by a
    test: a stray file there registers a hypothesis."""
    for name, rel in (("REPORTS", "reports"), ("CONFIGS", "configs"),
                      ("QUEUE", "configs/queue"), ("REGISTRY", "configs/registry")):
        p = tmp_path / rel
        p.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(config, name, p)
    (tmp_path / "configs" / "closed").mkdir(parents=True, exist_ok=True)
    (tmp_path / "configs" / "proposed").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "LEDGER_DB", tmp_path / "trials.sqlite")
    monkeypatch.setattr(runstate, "LAST_REASONING", tmp_path / ".last_cycle")
    monkeypatch.setattr(runstate, "SUPERVISOR_LOCK", tmp_path / "forever.lock")
    monkeypatch.setattr(runstate, "CYCLE_LOG", tmp_path / "reports" / "CYCLE_LOG.jsonl")
    monkeypatch.setattr(runstate, "REASONING_LOG",
                        tmp_path / "reports" / "REASONING_LOG.jsonl")
    monkeypatch.setattr(runstate, "ACTIVITY_LOG",
                        tmp_path / "reports" / "ACTIVITY.jsonl")
    (tmp_path / "reports" / "CYCLE_REPORT.md").write_text("v1", encoding="utf-8")
    return tmp_path


def _register(hid: str, when: datetime) -> None:
    h = Hypothesis(hypothesis_id=hid, family=f"fam_{hid}", claim="c",
                   kill_condition="k", universe=["BTCUSDT"],
                   grid={"n_contributions": [52, 104, 156]},
                   fixed={"contribution": 100.0})
    h.register()
    p = config.REGISTRY / f"{hid}.json"
    h.save(p)
    rec = json.loads(p.read_text(encoding="utf-8"))
    rec["registered_utc"] = when.isoformat()
    p.write_text(json.dumps(rec), encoding="utf-8")


def _pass(when: datetime, registered: list[str]) -> None:
    runstate.append_reasoning_log(
        {"utc": when.isoformat(),
         "steps": {"adversary": [{"file": f, "verdict": "REGISTER"}
                                 for f in registered]}})


# --------------------------------------------------------------------------
# the budget is the only thing standing between 24h and an inflated N
# --------------------------------------------------------------------------
def test_only_recent_registrations_count(sandbox):
    now = datetime.now(UTC)
    _register("H0001", now - timedelta(hours=1))
    _register("H0002", now - timedelta(hours=23, minutes=59))
    _register("H0003", now - timedelta(hours=25))
    assert sorted(runstate.registrations_last_24h(now)) == ["H0001", "H0002"]


def test_a_killed_proposal_does_not_spend_the_budget(sandbox):
    """The asymmetry the whole design rests on.  A kill costs a file in
    configs/killed/ and zero ledger rows, so rationing it would ration the one
    step that widens the search."""
    now = datetime.now(UTC)
    (config.CONFIGS / "killed").mkdir(parents=True, exist_ok=True)
    for hid in ("H0009", "H0010", "H0011", "H0012", "H0013"):
        (config.CONFIGS / "killed" / f"{hid}.json").write_text("{}", encoding="utf-8")
    assert runstate.registrations_last_24h(now) == []


def test_the_gate_refuses_once_the_budget_is_spent(sandbox):
    now = datetime.now(UTC)
    for i in range(config.MAX_REGISTRATIONS_PER_DAY):
        _register(f"H000{i + 1}", now - timedelta(hours=i + 1))
    # Old enough not to be rate limited, and it registered something, so only
    # the budget can be the reason.
    _pass(now - timedelta(hours=2), ["H0001.json"])
    (config.REPORTS / "CYCLE_REPORT.md").write_text("changed", encoding="utf-8")
    due, why = runstate.reasoning_due(now)
    assert not due
    assert "예산 소진" in why


def test_one_slot_under_the_budget_still_opens(sandbox):
    now = datetime.now(UTC)
    for i in range(config.MAX_REGISTRATIONS_PER_DAY - 1):
        _register(f"H000{i + 1}", now - timedelta(hours=i + 1))
    _pass(now - timedelta(hours=2), ["H0001.json"])
    runstate.stamp_reasoning("stale-fingerprint")
    assert runstate.reasoning_due(now)[0] is True


# --------------------------------------------------------------------------
# proposing again is allowed; hammering is not
# --------------------------------------------------------------------------
def test_a_pass_that_registered_nothing_earns_another_try(sandbox):
    """The adversary's reasons ARE new evidence.  H0009 was killed as a re-skin
    of closed H0007 and H0010 for misreading a metric; a proposer that reads
    those two verdicts asks a better question than one that waits six hours for
    a report with a new timestamp in it.  It costs zero rows, because only the
    budget above can raise N."""
    now = datetime.now(UTC)
    _pass(now - timedelta(minutes=runstate.MIN_REASONING_INTERVAL_MIN + 5), [])
    runstate.stamp_reasoning()                  # evidence unchanged
    due, why = runstate.reasoning_due(now)
    assert due
    assert "등록하지 못했습니다" in why


def test_a_successful_pass_does_not_earn_another_try_on_the_same_evidence(sandbox):
    now = datetime.now(UTC)
    _pass(now - timedelta(hours=3), ["H0009.json"])
    runstate.stamp_reasoning()
    due, why = runstate.reasoning_due(now)
    assert not due
    assert "두 번 등록하지 않습니다" in why


def test_the_gate_rate_limits_back_to_back_passes(sandbox):
    """Without a floor the supervisor would start a second pass the instant the
    adversary rejected one, because the branch above says a kill is new
    information -- forever."""
    now = datetime.now(UTC)
    _pass(now - timedelta(minutes=5), [])
    due, why = runstate.reasoning_due(now)
    assert not due
    assert f"{runstate.MIN_REASONING_INTERVAL_MIN}분" in why


# --------------------------------------------------------------------------
# there is always something to do
# --------------------------------------------------------------------------
def test_an_untouched_repository_has_zero_n_work_waiting(sandbox):
    """The claim that makes "never idle" true rather than a faster poll.  With
    no question due, the answer must still be real work."""
    now = datetime.now(UTC)
    _pass(now - timedelta(hours=3), ["H0009.json"])
    runstate.stamp_reasoning()
    assert runstate.reasoning_due(now)[0] is False
    action, why = runstate.next_action(now)
    assert action in runstate.ZERO_N_WORK, (action, why)


def test_work_is_taken_in_order_of_staleness(sandbox):
    now = datetime.now(UTC)
    _pass(now - timedelta(hours=3), ["H0009.json"])
    runstate.stamp_reasoning()
    # Everything just inside its allowance: nothing is due.
    for action, age_min in runstate.ZERO_N_WORK.items():
        runstate._append(runstate.ACTIVITY_LOG, {
            "utc": (now - timedelta(minutes=age_min - 10)).isoformat(),
            "action": action, "detail": "x"})
    assert runstate.next_action(now)[0] == "rest"

    # An action's freshness is its NEWEST run, so an old row cannot make a
    # recently-run action look stale -- push the newest one past its allowance
    # instead.
    runstate._append(runstate.ACTIVITY_LOG, {
        "utc": (now - timedelta(minutes=ZERO_N_LONGEST + 1)).isoformat(),
        "action": "robustness", "detail": "x"})
    assert runstate.next_action(now)[0] == "rest", \
        "an older row must not un-freshen an action"
    runstate.ACTIVITY_LOG.write_text("", encoding="utf-8")
    for action, age_min in runstate.ZERO_N_WORK.items():
        age = age_min - 10 if action != "robustness" else age_min + 10
        runstate._append(runstate.ACTIVITY_LOG, {
            "utc": (now - timedelta(minutes=age)).isoformat(),
            "action": action, "detail": "x"})
    assert runstate.next_action(now)[0] == "robustness"


def test_a_blocking_finding_stops_research_but_not_reading_the_code(sandbox,
                                                                   monkeypatch):
    """Research on code known to be wrong is forbidden -- a number computed on
    it looks like evidence and is not.  Reading that code harder is the correct
    response, so the kernel review is the one action allowed through."""
    import findings
    monkeypatch.setattr(findings, "blocking",
                        lambda: [{"id": "deadbeef1234", "file": "orc/eval/x.py",
                                  "severity": "high", "what": "wrong"}])
    action, why = runstate.next_action(datetime.now(UTC))
    assert action == "kernel_review"
    assert "연구는 멈춥니다" in why

    runstate.record_activity("kernel_review", "just ran")
    action, why = runstate.next_action(datetime.now(UTC))
    assert action == "blocked"
    assert "deadbeef1234" in why


def test_a_failed_attempt_does_not_count_as_the_action_being_done(sandbox):
    """The scout's allowance is 90 minutes.  A failed attempt used to reset the
    same clock as a successful one, so one transient provider error -- a 404
    refreshing a model list, which happened on the supervisor's first scout --
    bought an hour and a half of silence, and the action looked freshly done
    because it had freshly not worked."""
    now = datetime.now(UTC)
    # No question is due, so the answer must come from the zero-N table.
    _pass(now - timedelta(hours=3), ["H0009.json"])
    runstate.stamp_reasoning()
    assert runstate.reasoning_due(now)[0] is False
    runstate.record_activity("scout", "exit 1: both providers skipped", 4.0,
                             ok=False)
    assert runstate.last_activity_at("scout") is None
    assert runstate.last_activity_at("scout", ok_only=False) is not None

    # Inside the cooldown it is passed over, so a broken provider cannot become
    # a hot loop...
    assert runstate.next_action(now)[0] != "scout"
    # ...and once the cooldown is past, it is due again -- minutes, not the
    # whole allowance.
    later = now + timedelta(minutes=runstate.FAILURE_COOLDOWN_MIN + 1)
    action, why = runstate.next_action(later)
    assert action == "scout", (action, why)
    assert "성공한 실행이 없습니다" in why


def test_a_row_written_before_the_ok_field_existed_counts_as_success(sandbox):
    """The activity log is append-only and already has rows in it.  Reading a
    row with no `ok` as a failure would make every action look never-done."""
    now = datetime.now(UTC)
    runstate._append(runstate.ACTIVITY_LOG, {
        "utc": (now - timedelta(minutes=5)).isoformat(),
        "action": "robustness", "detail": "exit 0: fine"})
    assert runstate.last_activity_at("robustness") is not None


def test_an_activity_is_recorded_and_found(sandbox):
    """"It never rests" is a claim, and reports/ACTIVITY.jsonl is the file that
    would fail if it were false."""
    assert runstate.last_activity_at("scout") is None
    runstate.record_activity("scout", "2 new payers", 41.5)
    at = runstate.last_activity_at("scout")
    assert at is not None
    rows = runstate.activities(5)
    assert rows[0]["action"] == "scout"
    assert rows[0]["seconds"] == 41.5


# --------------------------------------------------------------------------
# every action the supervisor can choose is one it can run
# --------------------------------------------------------------------------
def test_every_action_has_a_command_and_a_timeout():
    """Mechanical, because the failure is silent: an action in the table with
    no plan() branch would be selected on every tick, do nothing, never reset
    its clock, and starve every other action for the life of the project."""
    import forever
    for action in list(runstate.ZERO_N_WORK) + ["reason"]:
        assert action in forever.TIMEOUTS_S, action
        cmd = forever.plan(action)
        # None is allowed only for an action that is genuinely inapplicable
        # right now; the script it would run must exist either way.
        if cmd is None:
            assert action == "execution_realism", action
            continue
        assert Path(cmd[1]).exists(), cmd


def test_an_inapplicable_action_still_resets_its_clock(sandbox, monkeypatch):
    """execution_realism is a Track B tool and the only open family is Track A.
    If an inapplicable action left its clock untouched, next_action would pick
    it again on the very next tick and nothing else would ever run.

    next_action is pinned rather than derived here.  A tick that is free to
    choose would choose `reason`, and this test would then launch the real
    pipeline -- eight to ten model calls -- from the suite.
    """
    import forever
    monkeypatch.setattr(forever, "track_b_cell", lambda: None)
    monkeypatch.setattr(runstate, "next_action",
                        lambda now=None: ("execution_realism", "pinned"))
    # A guard, not decoration: if the pinning above ever stops working, this
    # turns a 40-minute model run into an immediate failure.
    monkeypatch.setattr(forever, "run", lambda *a, **k: pytest.fail(
        "tick() tried to execute a command in a unit test"))
    assert forever.plan("execution_realism") is None
    action, nap = forever.tick()
    assert action == "execution_realism"
    assert runstate.last_activity_at("execution_realism") is not None
    assert nap == forever.WORKED_SLEEP_S


def test_only_one_supervisor_may_hold_the_lock(sandbox, monkeypatch, tmp_path):
    """Two supervisors would each read the registration budget per tick, so
    both could see three booked and make the fifth and sixth."""
    import forever
    monkeypatch.setattr(forever, "LOCK", tmp_path / "forever.lock")
    monkeypatch.setattr(forever, "LOG_DIR", tmp_path)
    assert forever.claim_lock() is True
    assert forever.claim_lock() is False        # a live heartbeat holds it
    stale = datetime.now(UTC) - timedelta(minutes=forever.LOCK_STALE_MIN + 1)
    forever.LOCK.write_text(json.dumps(
        {"pid": 1, "heartbeat_utc": stale.isoformat()}), encoding="utf-8")
    assert forever.claim_lock() is True         # a dead one is broken
    forever.release_lock()
    assert not forever.LOCK.exists()


def test_the_heartbeat_outlives_the_longest_action(monkeypatch, tmp_path):
    """Beating only between ticks was not enough: a reasoning pass is allowed
    three hours, so the lock would go stale WHILE the supervisor was working --
    reported dead in the briefing, and broken by the hourly watchdog trigger,
    which is how a second supervisor gets started on top of the first."""
    import forever
    assert forever.HEARTBEAT_S * 3 < forever.LOCK_STALE_MIN * 60,         "a couple of missed beats must not make the lock look like a corpse"
    assert max(forever.TIMEOUTS_S.values()) > forever.LOCK_STALE_MIN * 60,         "if no action can outlive the stale window, this thread is pointless"

    monkeypatch.setattr(forever, "HEARTBEAT_S", 0.05)
    forever.beat_lock()
    first = json.loads(forever.LOCK.read_text(encoding="utf-8"))["heartbeat_utc"]
    stop = forever.start_heartbeat()
    try:
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            now = json.loads(forever.LOCK.read_text(encoding="utf-8"))["heartbeat_utc"]
            if now != first:
                break
            time.sleep(0.05)
        else:
            pytest.fail("the heartbeat thread never beat the lock")
    finally:
        stop.set()


def test_a_research_verdict_is_not_read_as_a_failure():
    """FAIL is the product here -- the deliverable is a map of where rules
    break -- so several of these scripts return non-zero to report a VERDICT.
    execution_realism returns 1 when a cell does not survive minute bars
    (H0002/BTCUSDT drifts 53.9% between clocks and returns 1), and
    kernel_review returns 1 when it FOUND a high finding.  Reading either as a
    failure puts it in the 12-minute cooldown and retries it forever, so the
    one action whose answer is already known becomes all the supervisor does."""
    import forever
    assert 1 in forever.DONE_EXIT_CODES["execution_realism"]
    assert 1 in forever.DONE_EXIT_CODES["kernel_review"]
    # And where non-zero really does mean nothing was collected, it must not be
    # mistaken for work.
    assert forever.DONE_EXIT_CODES["scout"] == (0,)
    assert forever.DONE_EXIT_CODES["reason"] == (0,)
    for action in list(runstate.ZERO_N_WORK) + ["reason"]:
        assert action in forever.DONE_EXIT_CODES, action
        assert 0 in forever.DONE_EXIT_CODES[action], action


def test_the_commit_paths_name_files_and_never_a_wildcard():
    """Section 10: never stage by wildcard.  AGENTS.md arrived in a commit that
    way -- 193 lines written into the tree by a step documented as read-only."""
    import forever
    for action, paths in forever.COMMIT_PATHS.items():
        assert paths, action
        for p in paths:
            assert "*" not in p and "?" not in p, (action, p)
            assert p.startswith("reports/"), (action, p)
    assert "reason" not in forever.COMMIT_PATHS, \
        "reasoning.py commits and pushes its own registration"


# --------------------------------------------------------------------------
# the scout may not carry this project's numbers to the proposer
# --------------------------------------------------------------------------
def test_a_candidate_carrying_a_performance_figure_is_refused():
    """Section 9 keeps the proposing step away from the ledger because hunting
    a maximum across every trial is the selection bias the protocol exists to
    contain.  An outside notebook does not violate that -- external literature
    cannot be tainted by ORC's results -- but a notebook carrying ORC's returns
    would reach the proposer by the back door."""
    import scout
    ok = {"payer": "a fund that must flatten before its NAV strike",
          "why_they_keep_paying": "the mandate is written down",
          "what_would_end_it": "the mandate changes",
          "observable": "a repeating imbalance at one minute of the day",
          "confidence": "medium", "distinct_from": "not a funding payer"}
    assert scout.reject(ok) is None
    for bad, expect in (
            ({**ok, "why_they_keep_paying": "its Sharpe is 2.1"}, "performance"),
            ({**ok, "confidence": "quite sure"}, "high/medium/low"),
            ({**ok, "payer": ""}, "missing payer"),
            ({**ok, "observable": "  "}, "missing observable")):
        why = scout.reject(bad)
        assert why is not None and expect in why, (bad, why)


def test_two_wordings_of_one_payer_are_the_same_candidate():
    import scout
    a = scout._slug("A market maker who must flatten inventory at settlement")
    b = scout._slug("the market maker that must flatten inventory at settlement")
    assert a == b


def test_the_closed_digest_handed_to_the_scout_carries_no_metric():
    """It is told what NOT to bring back, and it must learn that without
    learning any of this project's numbers."""
    import scout
    text = scout.closed_mechanisms()
    assert "funding" in text                    # it must know the closed family
    assert scout.PERFORMANCE_WORDS.search(text) is None, text
