"""ORC | Protocol enforcement.

These tests are not about arithmetic.  They check that the parts of the system
whose whole job is to say NO actually say no: the append-only ledger, the
pre-registration hash, and the sealed holdout.  A protocol that is only a
convention is not a protocol once the loop runs unattended.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orc import config, holdout
from orc.ledger.trials import Ledger, canonical_hash
from orc.orchestrator.spec import Hypothesis, TrialConfig


@pytest.fixture()
def led(tmp_path):
    with Ledger(tmp_path / "t.sqlite") as l:
        yield l


def _row(**kw):
    base = dict(run_id="r1", family="f", symbol="BTCUSDT", evaluator="analytic",
                cfg={"a": 1}, metrics={"tm_q05": 1.0}, n_starts=10,
                panel_hash="ph", code="ch")
    base.update(kw)
    return base


# --------------------------------------------------------------------------
# the ledger counts N, and cannot be rewritten
# --------------------------------------------------------------------------
def test_identical_trial_does_not_inflate_n(led):
    id1, new1 = led.record(**_row())
    id2, new2 = led.record(**_row())
    assert new1 and not new2 and id1 == id2
    assert led.total_trials() == 1


def test_any_change_creates_a_new_trial(led):
    led.record(**_row())
    led.record(**_row(cfg={"a": 2}))            # different config
    led.record(**_row(code="other"))            # different kernel
    led.record(**_row(panel_hash="other"))      # different data
    assert led.total_trials() == 4


def test_config_hash_ignores_key_order():
    assert canonical_hash({"a": 1, "b": 2}) == canonical_hash({"b": 2, "a": 1})


def test_ledger_rejects_update(led):
    led.record(**_row())
    with pytest.raises(sqlite3.IntegrityError):
        led.conn.execute("UPDATE trials SET family='rewritten'")


def test_ledger_rejects_delete(led):
    led.record(**_row())
    with pytest.raises(sqlite3.IntegrityError):
        led.conn.execute("DELETE FROM trials")


def test_best_ranks_by_a_metric_inside_the_json(led):
    led.record(**_row(cfg={"a": 1}, metrics={"tm_q05": 0.5}))
    led.record(**_row(cfg={"a": 2}, metrics={"tm_q05": 2.5}))
    led.record(**_row(cfg={"a": 3}, metrics={"other": 9.0}))
    top = led.best("f", "tm_q05", limit=5)
    assert [t["tm_q05"] for t in top] == [2.5, 0.5]


# --------------------------------------------------------------------------
# pre-registration
# --------------------------------------------------------------------------
def _hyp(**kw):
    base = dict(hypothesis_id="H9999", family="fam", claim="c", kill_condition="k",
                universe=["BTCUSDT"], grid={"stride_days": [1.0, 7.0]})
    base.update(kw)
    return Hypothesis(**base)


def test_unregistered_hypothesis_cannot_run():
    with pytest.raises(ValueError, match="never registered"):
        _hyp().verify()


def test_editing_the_grid_after_registration_is_refused():
    h = _hyp().register()
    h.verify()
    h.grid["stride_days"].append(30.0)
    with pytest.raises(ValueError, match="changed after registration"):
        h.verify()


def test_editing_the_claim_after_registration_is_refused():
    h = _hyp().register()
    h.claim = "a more flattering story"
    with pytest.raises(ValueError, match="changed after registration"):
        h.verify()


def test_registration_survives_a_round_trip(tmp_path):
    h = _hyp().register()
    p = h.save(tmp_path / "H9999.json")
    again = Hypothesis.load(p)
    assert again.prereg_hash == h.prereg_hash


def test_expansion_is_exhaustive_and_deterministic():
    h = _hyp(universe=["BTCUSDT", "ETHUSDT"],
             grid={"stride_days": [1.0, 7.0], "n_contributions": [52, 104]}).register()
    a, b = h.expand(), h.expand()
    assert len(a) == h.size() == 8
    assert [c.to_dict() for c in a] == [c.to_dict() for c in b]


def test_analytic_routing_is_exact_about_what_it_can_express():
    assert TrialConfig(symbol="X", include_funding=False).uses_analytic
    assert not TrialConfig(symbol="X", leverage=3.0).uses_analytic
    assert not TrialConfig(symbol="X", gate="dip:0.1:30").uses_analytic
    assert not TrialConfig(symbol="X", take_profit=0.4).uses_analytic


def test_a_funded_position_is_not_sent_where_ruin_cannot_be_expressed():
    """The closed form keeps charging funding to an account it will take
    negative, and writes liquidation_rate 0.0 beside the result. H0001's funded
    ADAUSDT cell reported tm_q05 -0.4988 -- an unlevered long owing more than it
    deposited -- with a liquidation rate nobody had measured."""
    assert not TrialConfig(symbol="X", include_funding=True).uses_analytic, (
        "funding is part of the shape, not a detail of it")
    assert TrialConfig(symbol="X", include_funding=False).uses_analytic, (
        "unlevered and unfunded is the shape the two evaluators agree on")


# --------------------------------------------------------------------------
# the sealed holdout
# --------------------------------------------------------------------------
def _frame():
    return pl.DataFrame({"ts": [
        datetime(2020, 1, 1), datetime(2023, 1, 1),
        datetime(2024, 1, 1), datetime(2025, 1, 1)]})


def test_development_slice_stops_at_the_seal():
    d = holdout.development_slice(_frame())
    assert d.height == 3
    assert d["ts"].max() < datetime.combine(config.HOLDOUT_START, datetime.min.time())


def test_sealed_slice_is_the_complement():
    assert (holdout.development_slice(_frame()).height
            + holdout.sealed_slice(_frame()).height == _frame().height)


def test_assert_development_only_catches_a_leak():
    with pytest.raises(holdout.HoldoutViolation):
        holdout.assert_development_only(_frame())
    holdout.assert_development_only(holdout.development_slice(_frame()))


def test_final_test_refuses_without_a_hand_written_token(monkeypatch, tmp_path):
    monkeypatch.setattr(holdout, "TOKEN_FILE", tmp_path / "TOKEN")
    monkeypatch.setattr(holdout, "LOG_FILE", tmp_path / "log.jsonl")
    with pytest.raises(holdout.HoldoutViolation, match="no FINAL_TEST_TOKEN"):
        holdout.open_final_test({"id": "x"}, "trying it on")


def test_final_test_rejects_a_wrong_token(monkeypatch, tmp_path):
    tok = tmp_path / "TOKEN"
    tok.write_text("sure whatever", encoding="utf-8")
    monkeypatch.setattr(holdout, "TOKEN_FILE", tok)
    monkeypatch.setattr(holdout, "LOG_FILE", tmp_path / "log.jsonl")
    with pytest.raises(holdout.HoldoutViolation, match="does not match"):
        holdout.open_final_test({"id": "x"}, "trying it on")


def test_final_test_consumes_the_token_and_is_capped(monkeypatch, tmp_path):
    tok, log = tmp_path / "TOKEN", tmp_path / "log.jsonl"
    monkeypatch.setattr(holdout, "TOKEN_FILE", tok)
    monkeypatch.setattr(holdout, "LOG_FILE", log)

    for i in range(holdout.MAX_FINAL_TESTS):
        tok.write_text(holdout.TOKEN_TEXT, encoding="utf-8")
        rec = holdout.open_final_test({"id": i}, "a real final test")
        assert rec["opening"] == i + 1
        assert not tok.exists(), "the token must be consumed on use"

    tok.write_text(holdout.TOKEN_TEXT, encoding="utf-8")
    with pytest.raises(holdout.HoldoutViolation, match="spent"):
        holdout.open_final_test({"id": "one too many"}, "no")


def test_every_opening_is_logged_with_a_hash(monkeypatch, tmp_path):
    tok, log = tmp_path / "TOKEN", tmp_path / "log.jsonl"
    monkeypatch.setattr(holdout, "TOKEN_FILE", tok)
    monkeypatch.setattr(holdout, "LOG_FILE", log)
    tok.write_text(holdout.TOKEN_TEXT, encoding="utf-8")
    holdout.open_final_test({"cfg": "candidate A"}, "because")
    rec = json.loads(log.read_text(encoding="utf-8").strip())
    assert rec["candidate"] == {"cfg": "candidate A"}
    assert len(rec["candidate_sha256"]) == 64


def test_funding_past_the_panel_end_is_not_charged():
    """A settlement with no bar to land on must be dropped, not folded onto the last one.

    searchsorted answers 'the last bar' for anything past the end, so the naive
    mapping silently accumulated every later settlement on the final bar.  On a
    BTCUSDT panel truncated at the seal that put 0.163990 into a single hour --
    the exact sum of the 2742 sealed settlements -- which is both an absurd
    funding charge and sealed data inside the development window.
    """
    import polars as pl
    from orc.facts.fetch_vision import funding_rate_per_bar

    bars = pl.Series("ts", [datetime(2024, 1, 1, h) for h in range(24)])
    funding = pl.DataFrame({
        "ts": [datetime(2024, 1, 1, 8),      # inside the panel
               datetime(2024, 1, 1, 23, 59),  # inside the final bar
               datetime(2024, 1, 2, 0),       # first bar past the end
               datetime(2026, 8, 1)],         # long past the end
        "funding_rate": [0.0001, 0.0002, 5.0, 7.0],
    })
    fr, settled = funding_rate_per_bar(bars, funding)

    assert fr[8] == pytest.approx(0.0001)
    assert fr[23] == pytest.approx(0.0002), "a settlement inside the last bar still counts"
    assert fr.sum() == pytest.approx(0.0003), "nothing past the end may be charged"
    assert settled.tolist().count(True) == 2, "two settlements landed, and only two"
    assert settled[8] and settled[23]


# --------------------------------------------------------------------------
# what counts as a finding
#
# One rule, shared by the status screen and the notifier, because the copy that
# drifts is always the one that decides whether to wake somebody up.
# --------------------------------------------------------------------------
def _cell(value, shape="PLATEAU", paths=40.0):
    return {"best_value": value,
            "shape_diagnostic": {"shape": shape},
            "independent_paths_best": paths}


# A search test that a cell passed, for the cases whose point is a different check.
_PASSED_SEARCH = {"status": "ok", "survives_search": True, "p_value": 0.005}


def test_a_losing_cell_is_never_a_finding():
    from orc.orchestrator import verdict

    s = _PASSED_SEARCH
    assert verdict.disqualifiers(_cell(0.7677), "tm_q05", 0.1, s)[0] == "at or below 1"
    assert verdict.disqualifiers(_cell(-0.29), "calmar", 0.1, s)[0] == "at or below 0"
    assert verdict.disqualifiers(_cell(1.4), "tm_q05", 0.1, s) == []
    assert verdict.disqualifiers(_cell(0.31), "calmar", 0.1, s) == []


def test_every_disqualifier_is_reported_not_just_the_first():
    from orc.orchestrator import verdict

    why = verdict.disqualifiers(_cell(0.5, shape="SPIKE", paths=1.02), "calmar", 0.8,
                                _PASSED_SEARCH)
    assert why == ["spike", "1.02 paths", "PBO 0.80"]


def test_a_spike_is_not_a_finding_however_large():
    from orc.orchestrator import verdict

    assert "spike" in verdict.disqualifiers(_cell(9.99, shape="SPIKE"), "tm_q05", None,
                                            _PASSED_SEARCH)


def test_survivors_reads_the_report_metric_not_a_default():
    from orc.orchestrator import verdict

    report = {"metric": "calmar",
              "pbo": {"AAA": {"status": "ok", "pbo": 0.1,
                              "covers_reported_best": True},
                      "BBB": {"status": "ok", "pbo": 0.1,
                              "covers_reported_best": True}},
              "search_test": {"AAA": _PASSED_SEARCH, "BBB": _PASSED_SEARCH},
              "surfaces": {"AAA": _cell(0.4), "BBB": _cell(-0.1)}}
    assert [s for s, _ in verdict.survivors(report)] == ["AAA"]


# --------------------------------------------------------------------------
# the robustness gate
# --------------------------------------------------------------------------
def test_an_unmeasured_check_is_not_a_pass_and_not_a_failure():
    from orc.orchestrator import robustness

    v = robustness.verdict([{"check": "cost", "passed": True},
                            {"check": "regime", "passed": None}])
    assert v["passed"] is False
    assert v["failed"] == []
    assert v["unmeasured"] == ["regime"]


def test_blocks_too_short_to_judge_are_refused():
    from orc.orchestrator import robustness

    with pytest.raises(ValueError, match="would not be evidence"):
        robustness.walk_forward_blocks(1000, n_blocks=4)


def test_walk_forward_blocks_are_contiguous_and_do_not_overlap():
    from orc.orchestrator import robustness

    blocks = robustness.walk_forward_blocks(40_000, n_blocks=4)
    assert blocks[0][0] == 0 and blocks[-1][1] == 40_000
    for (_, end), (start, _) in zip(blocks, blocks[1:]):
        assert end == start


def test_the_regime_label_never_looks_forward():
    """A bar's label must depend only on bars at or before it."""
    import numpy as np
    from orc.orchestrator import robustness

    close = np.concatenate([np.linspace(100, 200, 500), np.linspace(200, 50, 500)])
    a = robustness.regime_split(close, window_bars=100)
    bumped = close.copy()
    bumped[700:] = 1e6
    b = robustness.regime_split(bumped, window_bars=100)
    assert np.array_equal(a[:700], b[:700])


def test_a_pbo_that_was_never_computed_is_not_a_pass():
    """Found by the kernel review: None read as clearance, so any cell outside
    the top three could be announced as clearing PBO with PBO never run."""
    from orc.orchestrator import verdict

    assert verdict.disqualifiers(_cell(1.4), "tm_q05", None,
                                 _PASSED_SEARCH) == ["PBO unmeasured"]
    report = {"metric": "calmar", "pbo": {},
              "search_test": {"AAA": _PASSED_SEARCH},
              "surfaces": {"AAA": _cell(0.4)}}
    assert verdict.survivors(report) == []


def test_the_code_hash_covers_everything_that_writes_a_number():
    """A metric corrected in the orchestrator must start a new trial, not be
    discarded by INSERT OR IGNORE while the run reports 'new 0'."""
    from orc import config
    from orc.ledger.trials import code_hash

    base = code_hash()
    runner = config.ORC_ROOT / "orc" / "orchestrator" / "runner.py"
    original = runner.read_bytes()
    try:
        runner.write_bytes(original + b"\n# a change to how a metric is computed\n")
        assert code_hash() != base
    finally:
        runner.write_bytes(original)
    assert code_hash() == base


def test_a_shape_that_was_never_computed_is_not_a_pass():
    """plateau_score returns no shape on a grid whose axes all have two levels,
    and reading that absence as 'not a spike' let a cell clear the structural
    check by never facing it."""
    from orc.orchestrator import verdict

    blind = {"best_value": 1.34, "shape_diagnostic": {"peak": 1.34,
                                                      "plateau_ratio": float("nan")},
             "independent_paths_best": 19.0}
    assert verdict.disqualifiers(blind, "calmar", 0.29,
                                 _PASSED_SEARCH) == ["shape unmeasured"]


def test_plateau_score_cannot_see_a_two_level_grid():
    import numpy as np

    from orc.kernel.inference import plateau_score

    g = np.arange(8.0).reshape(2, 2, 2)
    assert "shape" not in plateau_score(g, [False, False, False])
    fine = np.arange(27.0).reshape(3, 3, 3)
    assert "shape" in plateau_score(fine, [True, True, True])


def test_walk_forward_needs_the_edge_to_survive_not_just_its_sign():
    """Found by the post-mortem: 1.790 in-sample to 0.159 out was recorded as
    passing because both numbers were positive."""
    from orc.orchestrator import robustness

    class Cell:
        def to_dict(self):
            return {}

    panel = type("P", (), {"__len__": lambda self: 40_000})()
    scores = {(0, 10_000): 2.0, (10_000, 20_000): 1.58,
              (20_000, 30_000): 0.16, (30_000, 40_000): 0.16}

    def score(cell, p, lo, hi):
        return scores[(lo, hi)]

    r = robustness.walk_forward(score, [Cell()], panel)
    assert r["in_sample"] > 0 and r["out_of_sample"] > 0
    assert r["retention"] < robustness.MIN_OOS_RETENTION
    assert r["passed"] is False


def test_a_surface_whose_best_cell_still_loses_gets_no_shape():
    """Dividing one negative by another turned a collapse into a plateau: a peak
    of -0.04 beside neighbours at -1.0 reported a ratio of 25 and PLATEAU."""
    import numpy as np

    from orc.kernel.inference import plateau_score

    g = np.full((3, 3), -1.0)
    g[1, 1] = -0.04
    d = plateau_score(g, [True, True])
    assert "shape" not in d
    assert np.isnan(d["plateau_ratio"])


def test_a_best_a_random_search_matches_is_not_a_finding():
    """The question N exists to answer, and never asked until now: given that
    this many configurations were tried, how surprising is the best of them?"""
    from orc.orchestrator import verdict

    beaten = {"status": "ok", "survives_search": False, "p_value": 0.42}
    assert verdict.disqualifiers(_cell(1.4), "tm_q05", 0.1, beaten) == [
        "p=0.420 vs a random search"]
    assert verdict.disqualifiers(_cell(1.4), "tm_q05", 0.1, None) == [
        "search test unmeasured"]


# --------------------------------------------------------------------------
# an id is a promise: what is behind it cannot be swapped out
# --------------------------------------------------------------------------
def test_reusing_a_registered_id_for_different_content_is_refused(tmp_path):
    """The surface report selects trials WHERE hypothesis_id=?.  Overwriting a
    registered id does not replace its trials, it adopts them."""
    first = _hyp().register()
    first.save(tmp_path / "H9999.json")

    second = _hyp(family="a different family", claim="a different story").register()
    with pytest.raises(ValueError, match="already registered"):
        second.save(tmp_path / "H9999.json")


def test_re_registering_the_identical_hypothesis_is_not_an_edit(tmp_path):
    """A rebase can put the same queue file back; that is not a changed grid."""
    h = _hyp().register()
    h.save(tmp_path / "H9999.json")
    again = Hypothesis(**json.loads((tmp_path / "H9999.json").read_text(encoding="utf-8")))
    again.save(tmp_path / "H9999.json")          # must not raise
    assert again.prereg_hash == h.prereg_hash


def test_the_next_id_skips_one_that_was_proposed_and_killed(tmp_path):
    """A killed proposal is filed under its id.  Reissuing the id overwrites
    the record of why it was rejected."""
    from orc.orchestrator.spec import next_hypothesis_id
    registry, killed = tmp_path / "registry", tmp_path / "killed"
    registry.mkdir(); killed.mkdir()
    (registry / "H0001.json").write_text("{}", encoding="utf-8")
    (killed / "H0002.json").write_text("{}", encoding="utf-8")

    assert next_hypothesis_id(registry) == "H0002"        # registry alone is blind
    import orc.config as cfg
    old = (cfg.REGISTRY, cfg.QUEUE, cfg.CONFIGS)
    cfg.REGISTRY, cfg.QUEUE, cfg.CONFIGS = registry, tmp_path / "queue", tmp_path
    try:
        assert next_hypothesis_id() == "H0003"
    finally:
        cfg.REGISTRY, cfg.QUEUE, cfg.CONFIGS = old


# --------------------------------------------------------------------------
# N can only grow, so what one hypothesis may add to it is capped
# --------------------------------------------------------------------------
def test_a_grid_beyond_the_ceiling_is_refused_whole(tmp_path, monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import daily_cycle

    queue, registry = tmp_path / "queue", tmp_path / "registry"
    queue.mkdir(); registry.mkdir()
    monkeypatch.setattr(config, "QUEUE", queue)
    monkeypatch.setattr(config, "REGISTRY", registry)
    # Both ceilings: an untested family gets the probe one, and this family has
    # no rows in the ledger, so that is the one that has to bind here.
    monkeypatch.setattr(config, "MAX_CONFIGURATIONS_PER_HYPOTHESIS", 10)
    monkeypatch.setattr(config, "MAX_PROBE_CONFIGURATIONS", 10)

    big = _hyp(grid={"stride_days": list(range(1, 12))})
    (queue / "H9999.json").write_text(
        json.dumps({k: v for k, v in big.__dict__.items()}), encoding="utf-8")

    assert daily_cycle.intake_queue() == []
    assert not (registry / "H9999.json").exists()
    assert (queue / "rejected" / "H9999.json").exists()


def test_a_grid_inside_the_ceiling_still_registers(tmp_path, monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import daily_cycle

    queue, registry = tmp_path / "queue", tmp_path / "registry"
    queue.mkdir(); registry.mkdir()
    monkeypatch.setattr(config, "QUEUE", queue)
    monkeypatch.setattr(config, "REGISTRY", registry)
    monkeypatch.setattr(config, "MAX_CONFIGURATIONS_PER_HYPOTHESIS", 10)

    small = _hyp(grid={"stride_days": [1.0, 7.0, 30.0]})
    (queue / "H9999.json").write_text(
        json.dumps({k: v for k, v in small.__dict__.items()}), encoding="utf-8")

    got = daily_cycle.intake_queue()
    assert [h.hypothesis_id for h in got] == ["H9999"]
    assert (registry / "H9999.json").exists()


# --------------------------------------------------------------------------
# the loop can die without anything failing
# --------------------------------------------------------------------------
def test_a_ledger_that_stopped_growing_is_news(tmp_path, monkeypatch):
    """Every other signal in the notifier stays green while the research is
    over: the cycle is fresh, the stamp is fresh, the queue is empty."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import notify

    reports, queue, logs = tmp_path / "reports", tmp_path / "queue", tmp_path / "logs"
    for d in (reports, queue, logs):
        d.mkdir()
    now = datetime.now(timezone.utc)
    (reports / "CYCLE_SUMMARY.json").write_text(
        json.dumps({"finished_utc": now.isoformat(), "results": []}), encoding="utf-8")
    (logs / ".last_cycle").write_text(now.strftime("%Y-%m-%d"), encoding="utf-8")

    db = tmp_path / "t.sqlite"
    monkeypatch.setattr(config, "REPORTS", reports)
    monkeypatch.setattr(config, "QUEUE", queue)
    monkeypatch.setattr(config, "ORC_ROOT", tmp_path)
    monkeypatch.setattr(config, "LEDGER_DB", db)

    with Ledger(db) as l:
        l.record(**_row())
        stale = (now - timedelta(days=9)).isoformat()
        l.conn.execute("DROP TRIGGER trials_no_update")   # append-only, so age it by hand
        l.conn.execute("UPDATE trials SET created_utc=?", (stale,))
        l.conn.commit()

    assert any("idle" in n for n in notify.collect())

    with Ledger(db) as l:
        l.record(**_row(cfg={"a": 2}))
    assert not any("idle" in n for n in notify.collect())


# --------------------------------------------------------------------------
# a proposal that could not be judged waits -- but not forever
# --------------------------------------------------------------------------
def _reasoning(tmp_path, monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import reasoning
    proposed, killed = tmp_path / "proposed", tmp_path / "killed"
    proposed.mkdir(); killed.mkdir()
    monkeypatch.setattr(reasoning, "PROPOSED", proposed)
    monkeypatch.setattr(reasoning, "KILLED", killed)
    return reasoning, proposed, killed


def test_a_held_proposal_is_judged_before_a_new_one_is_asked_for(tmp_path, monkeypatch):
    """Unreviewed is not approved, so it waits.  Deleting it would spend the
    day's registration slot twice on the same report."""
    reasoning, proposed, _ = _reasoning(tmp_path, monkeypatch)
    (proposed / "H9999.json").write_text('{"hypothesis_id": "H9999"}', encoding="utf-8")

    def _must_not_be_called(*a, **k):
        raise AssertionError("asked the model for a new batch with one still unjudged")
    monkeypatch.setattr(reasoning.llm, "ask", _must_not_be_called)

    assert [p.name for p in reasoning.propose()] == ["H9999.json"]


def test_a_proposal_nothing_can_review_does_not_wedge_the_pipeline(tmp_path, monkeypatch):
    """A reply the adversary can never parse would otherwise be handed back
    every cycle forever, and no new question would ever be asked again."""
    import os
    import time
    reasoning, proposed, killed = _reasoning(tmp_path, monkeypatch)
    stuck = proposed / "H9999.json"
    stuck.write_text('{"hypothesis_id": "H9999"}', encoding="utf-8")
    old = time.time() - (reasoning.HELD_PROPOSAL_MAX_DAYS + 1) * 86400
    os.utime(stuck, (old, old))

    monkeypatch.setattr(reasoning.llm, "ask", lambda *a, **k: "wrote nothing")
    assert reasoning.propose() == []
    assert not stuck.exists()
    verdict = json.loads((killed / "H9999.json").read_text(encoding="utf-8"))["verdict"]
    assert verdict["killed_by"] == "held_too_long"


# --------------------------------------------------------------------------
# a family that cannot be judged must not be allowed to cost N
# --------------------------------------------------------------------------
def test_the_intake_and_the_diagnostic_agree_on_what_an_ordinal_axis_is():
    from orc.orchestrator.spec import ordinal_axis
    assert ordinal_axis([1.0, 7.0, 30.0])
    assert ordinal_axis([7.0, 30.0, 90.0, None])      # None is off, the rest order
    assert not ordinal_axis([1.0, 7.0])               # no cell either side
    assert not ordinal_axis([True, False])            # a switch, not a step
    assert not ordinal_axis(["none", "sma:20", "sma:50", "sma:100", "sma:200"])


def test_the_predicate_matches_what_the_reports_actually_got():
    """H0006 and H0007 reported shape "?" on all nine symbols. If the check
    disagreed with the reports it would be enforcing a different rule."""
    import json

    from orc.orchestrator.spec import Hypothesis
    for hid, measurable in (("H0001", True), ("H0002", True),
                            ("H0006", False), ("H0007", False)):
        reg = config.REGISTRY / f"{hid}.json"
        rep = config.REPORTS / f"{hid}_SURFACE.json"
        if not (reg.exists() and rep.exists()):
            pytest.skip(f"{hid} not present in this checkout")
        h = Hypothesis(**json.loads(reg.read_text(encoding="utf-8")))
        assert h.shape_is_measurable() is measurable, hid
        got_a_shape = any("shape" in s["shape_diagnostic"]
                          for s in json.loads(
                              rep.read_text(encoding="utf-8"))["surfaces"].values())
        if not measurable:
            assert not got_a_shape, f"{hid} was judged unmeasurable but got a shape"


def test_a_grid_that_can_never_be_shape_checked_is_refused(tmp_path, monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import daily_cycle

    queue, registry = tmp_path / "queue", tmp_path / "registry"
    queue.mkdir(); registry.mkdir()
    monkeypatch.setattr(config, "QUEUE", queue)
    monkeypatch.setattr(config, "REGISTRY", registry)

    # five levels, all strings: reads as ordered, measures as five labels
    blind = _hyp(grid={"gate": ["none", "sma:20", "sma:50", "sma:100", "sma:200"],
                       "include_funding": [True, False]})
    (queue / "H9999.json").write_text(
        json.dumps({k: v for k, v in blind.__dict__.items()}), encoding="utf-8")

    assert daily_cycle.intake_queue() == []
    assert not (registry / "H9999.json").exists()
    assert (queue / "rejected" / "H9999.json").exists()


def test_a_pbo_measured_on_other_cells_does_not_clear_this_one():
    """H0001: the horizon subset excluded every symbol's best cell -- BTCUSDT
    was judged at stride_days 30 by a PBO computed on stride_days 1 -- and the
    number cleared it anyway."""
    from orc.orchestrator import verdict

    report = {"metric": "tm_q05",
              "search_test": {"AAA": _PASSED_SEARCH},
              "surfaces": {"AAA": _cell(2.0)}}

    report["pbo"] = {"AAA": {"status": "ok", "pbo": 0.1,
                             "covers_reported_best": True}}
    assert [s for s, _ in verdict.survivors(report)] == ["AAA"]

    report["pbo"] = {"AAA": {"status": "ok", "pbo": 0.1,
                             "covers_reported_best": False}}
    assert verdict.survivors(report) == []
    assert "PBO unmeasured" in verdict.disqualifiers(
        _cell(2.0), "tm_q05", None, _PASSED_SEARCH)


def test_an_unmeasured_path_count_is_not_a_pass_either():
    """112 ledger rows predate the span figure and carry no path count. The
    shape and the PBO either side of this check both fail closed; this one
    did not."""
    from orc.orchestrator import verdict

    cell = _cell(2.0)
    cell["independent_paths_best"] = None
    assert "path count unmeasured" in verdict.disqualifiers(
        cell, "tm_q05", 0.1, _PASSED_SEARCH)
    cell["independent_paths_best"] = 9.0
    assert verdict.disqualifiers(cell, "tm_q05", 0.1, _PASSED_SEARCH) == []


def test_a_settlement_that_cost_nothing_is_still_a_settlement():
    """4,276 settlements in the archive print exactly 0.0 -- 43.9 percent of
    BNBUSDT's. The rate array cannot tell them from a bar with no settlement,
    so the mask has to, or the per-settlement mean is divided by the wrong n."""
    import polars as pl
    from orc.facts.fetch_vision import funding_rate_per_bar

    bars = pl.Series("ts", [datetime(2024, 1, 1, h) for h in range(24)])
    funding = pl.DataFrame({"ts": [datetime(2024, 1, 1, 0),
                                   datetime(2024, 1, 1, 8),
                                   datetime(2024, 1, 1, 16)],
                            "funding_rate": [0.0003, 0.0, 0.0003]})
    fr, settled = funding_rate_per_bar(bars, funding)

    assert fr.sum() == pytest.approx(0.0006)
    assert settled.sum() == 3, "the 0.0 settlement is one of them"
    assert (fr != 0.0).sum() == 2, "and the rate array cannot see it"


def test_the_per_settlement_mean_counts_the_zero_rate_ones(tmp_path):
    """The same window read two ways: 1.5x apart, and the pre-registered
    threshold 0.0001 sits between them."""
    import numpy as np
    from orc.eval.signal_rules import _trailing_settlement_mean

    n = 240
    rate = np.zeros(n)
    settled = np.zeros(n, dtype=bool)
    settled[::8] = True                      # every eighth bar settles
    rate[::24] = 0.00012                     # one settlement in three is priced

    m = _trailing_settlement_mean(rate, 240, settled)
    assert m[-1] == pytest.approx(0.00012 * 10 / 30), "30 settlements, 10 priced"

    wrong = _trailing_settlement_mean(rate, 240, rate != 0.0)
    assert wrong[-1] == pytest.approx(0.00012), "counting non-zero rates triples it"
    assert m[-1] < 0.0001 < wrong[-1], (
        "the old count put this window on the other side of enter_rate")


def test_sealed_bars_are_refused_outside_a_final_test():
    """The counter used to record how many times someone filled in the form,
    not how many times the sealed period was read."""
    from orc.facts import panel as panel_mod

    assert not holdout.sealed_reads_permitted()
    with pytest.raises(holdout.HoldoutViolation, match="no final test is open"):
        panel_mod.load("BTCUSDT", "1h", development_only=False)


def test_one_opening_cannot_quietly_cover_a_whole_grid(monkeypatch, tmp_path):
    """A logged opening said 1 while the loop behind it read the sealed period
    972 times. The reads are now counted against the opening."""
    monkeypatch.setattr(holdout, "TOKEN_FILE", tmp_path / "tok")
    monkeypatch.setattr(holdout, "LOG_FILE", tmp_path / "log.jsonl")
    monkeypatch.setattr(holdout, "READS_FILE", tmp_path / "reads.jsonl")
    holdout.TOKEN_FILE.write_text(holdout.TOKEN_TEXT, encoding="utf-8")

    with holdout.final_test({"id": "H0002"}, "final") as rec:
        assert holdout.sealed_reads_permitted()
        for i in range(5):
            holdout.note_sealed_read(f"SYM{i}/1h")
    assert rec["opening"] == 1
    assert not holdout.sealed_reads_permitted()

    line = json.loads(holdout.READS_FILE.read_text(encoding="utf-8").strip())
    assert line["n_sealed_reads"] == 5, "one opening, five measurements, said so"


def test_the_permit_is_dropped_even_when_the_final_test_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(holdout, "TOKEN_FILE", tmp_path / "tok")
    monkeypatch.setattr(holdout, "LOG_FILE", tmp_path / "log.jsonl")
    monkeypatch.setattr(holdout, "READS_FILE", tmp_path / "reads.jsonl")
    holdout.TOKEN_FILE.write_text(holdout.TOKEN_TEXT, encoding="utf-8")

    with pytest.raises(RuntimeError):
        with holdout.final_test({"id": "X"}, "final"):
            holdout.note_sealed_read("SYM/1h")
            raise RuntimeError("the measurement blew up")
    assert not holdout.sealed_reads_permitted(), "a crash must not leave the door open"


def test_the_spend_count_is_the_ordinal_not_the_line_count(monkeypatch, tmp_path):
    """A log that loses a line would otherwise restore an opening and reissue
    an ordinal already spent."""
    log = tmp_path / "log.jsonl"
    monkeypatch.setattr(holdout, "LOG_FILE", log)
    log.write_text(chr(10).join([json.dumps({"opening": 1}),
                                 json.dumps({"opening": 3}), ""]),
                   encoding="utf-8")
    assert holdout.openings_used() == 3, "two lines, but three are spent"


def test_the_code_hash_covers_the_module_that_routes_and_prices_a_trial():
    """spec.py defines effective_fee_bps, uses_analytic and grid expansion.
    Change any of them and every metric moves while config_hash, panel_hash and
    evaluator all stay put, so INSERT OR IGNORE drops the corrected row."""
    from orc.ledger.trials import code_hash

    spec_py = config.ORC_ROOT / "orc" / "orchestrator" / "spec.py"
    base = code_hash()
    original = spec_py.read_bytes()
    try:
        spec_py.write_bytes(original + b"# a change that moves every fee" + chr(10).encode())
        assert code_hash() != base, "a change in spec.py must start a new trial"
    finally:
        spec_py.write_bytes(original)
    assert code_hash() == base


def test_a_non_finite_funding_rate_cannot_make_a_path_immortal():
    """NaN <= maintenance_margin is False, so one bad rate reports every path
    that touches it as a survivor and understates liquidation_rate."""
    import numpy as np
    from orc.eval.simulate import SimSpec, simulate

    close = np.full(40, 100.0)
    low = close.copy()
    fr = np.zeros(40)
    fr[5] = np.nan
    with pytest.raises(ValueError, match="non-finite"):
        simulate(close, low, np.array([0]),
                 SimSpec(contribution=100.0, stride_bars=1, n_contributions=3),
                 funding_rate=fr)


def test_a_final_test_can_ask_for_the_sealed_span_alone():
    """The gated door originally offered only the two spans concatenated --
    64.6 % of a BTCUSDT full panel is development history -- so the one
    irreversible measurement would be taken mostly in-sample."""
    from orc.facts import panel as panel_mod

    assert not holdout.sealed_reads_permitted()
    with pytest.raises(holdout.HoldoutViolation, match="no final test is open"):
        panel_mod.load("BTCUSDT", "1h", sealed_only=True)
    with pytest.raises(ValueError, match="different measurements"):
        panel_mod.load("BTCUSDT", "1h", development_only=False, sealed_only=True)


# --------------------------------------------------------------------------
# a closed family stays closed, and a known-bad kernel books no trials
# --------------------------------------------------------------------------
def test_a_closed_family_is_not_handed_back_for_evaluation(tmp_path):
    """Closing H0002 cost 972 trials because it did not stop anything.

    The registry file is the pre-registration and must survive -- section 3
    forbids editing or deleting it -- so the marker in configs/closed/ is the
    only thing that can say "answered".  load_registry() has to read it.
    """
    from orc.orchestrator.spec import closed_families, load_registry

    reg, closed = tmp_path / "registry", tmp_path / "closed"
    reg.mkdir(); closed.mkdir()
    _hyp(hypothesis_id="H9001").register().save(reg / "H9001.json")
    _hyp(hypothesis_id="H9002").register().save(reg / "H9002.json")

    assert {h.hypothesis_id for h in load_registry(reg, include_closed=True)} == {
        "H9001", "H9002"}

    (closed / "H9002.json").write_text(json.dumps(
        {"hypothesis_id": "H9002", "family": "fam", "reason": "the kill condition was met"}),
        encoding="utf-8")
    import orc.config as cfg
    real = cfg.CONFIGS
    try:
        cfg.CONFIGS = tmp_path
        assert set(closed_families()) == {"H9002"}
        assert [h.hypothesis_id for h in load_registry(reg)] == ["H9001"]
        # An id named by hand is still reachable: re-measuring a closed family
        # on minute bars is what produced the number that closed H0002.
        assert len(load_registry(reg, include_closed=True)) == 2
    finally:
        cfg.CONFIGS = real


def test_the_marker_outlives_the_postmortem_that_documents_it():
    """reasoning.py used to unlink the marker as soon as it had written the
    post-mortem, which is why H0002 was re-run 972 times the same evening."""
    src = (Path(__file__).resolve().parents[1] / "scripts" / "reasoning.py"
           ).read_text(encoding="utf-8")
    body = src.split("print(\"postmortem\")", 1)[1]
    assert "f.unlink()" not in body
    assert '"postmortem"' in body


def test_a_cycle_refuses_to_book_trials_while_a_high_finding_is_open(monkeypatch):
    """The reasoning layer has refused since yesterday; the step that writes
    to the ledger did not, and it is the half that cannot be undone."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import daily_cycle
    import findings as ledger

    monkeypatch.setattr(ledger, "load", lambda: {"findings": {
        "deadbeef1234": {"id": "deadbeef1234", "status": "open", "severity": "high",
                         "file": "orc/eval/signal.py", "line": 219,
                         "what": "a wipeout is recorded as an ordinary exit"}}})
    assert [f["id"] for f in daily_cycle.blocked_by_findings()] == ["deadbeef1234"]

    out = daily_cycle.run_cycle()
    assert out["status"] == "BLOCKED"
    assert out["blocked_by"] == ["deadbeef1234"]
    assert "trials_added" not in out          # nothing was evaluated


# --------------------------------------------------------------------------
# the null has to be the same search as the one it is a null for
# --------------------------------------------------------------------------
def _panel_for(close, rate=None):
    """A minimal Panel over a given path -- the search test's null is handed
    exactly this: a synthetic close, and the real panel for everything else."""
    from orc.facts.panel import Panel
    n = close.size
    fr = np.zeros(n) if rate is None else rate
    return Panel(symbol="BTCUSDT", clock="1h",
                 ts=np.datetime64("2020-01-01") + np.arange(n) * np.timedelta64(1, "h"),
                 open=close, high=close, low=close, close=close,
                 volume=np.ones(n), funding_rate=fr,
                 funding_settled=fr != 0.0,
                 holdout_state="development", panel_hash="ph")


def test_the_search_test_null_runs_the_shape_it_is_a_null_for():
    """It did not.  Every cell was scored by a hand-built AnalyticSpec, so the
    null for H0007 -- a gated, funded DCA -- was an unconditional unfunded one:
    it carried neither the mechanism nor the width of the search whose p-value
    it was being used to produce.  Each of the four axes below compared EQUAL
    under the old scorer, which is how a null can be run and mean nothing.
    """
    from orc.orchestrator.runner import tm_q05_on_path

    n = 24 * 400
    t = np.arange(n)
    close = 100.0 * (1.0 + 0.4 * np.sin(t / (24 * 45.0)))     # deep, repeated dips
    rate = np.zeros(n)
    rate[::8] = 0.0005                                        # a real funding tax
    p = _panel_for(close, rate)

    def cell(**kw):
        params = dict(include_funding=False)
        params.update(kw)
        return tm_q05_on_path(
            TrialConfig(symbol="BTCUSDT", contribution=100.0, stride_days=7.0,
                        n_contributions=52, **params), p, close)

    base = cell()
    assert np.isfinite(base)
    # a gate defers deposits, so it cannot leave the outcome untouched
    assert cell(gate="dip:0.10:30") != pytest.approx(base)
    # funding is a real cost on a perpetual and the grid carries it as an axis
    assert cell(include_funding=True) != pytest.approx(base)
    # leverage and a stop are the difference between a DCA and a liquidation
    assert cell(leverage=2.0) != pytest.approx(base)
    assert cell(stop_loss=0.2) != pytest.approx(base)


def test_the_null_routes_a_cell_the_way_a_real_trial_does():
    """Same decision, same evaluator: whatever the closed form may express, the
    null must use it there and the simulator everywhere else."""
    from orc.orchestrator.runner import tm_q05_on_path

    n = 24 * 300
    close = 100.0 * np.exp(np.cumsum(np.full(n, 0.00002)))
    p = _panel_for(close)
    plain = TrialConfig(symbol="BTCUSDT", contribution=100.0, stride_days=7.0,
                        n_contributions=40, include_funding=False)
    assert plain.uses_analytic
    levered = TrialConfig(symbol="BTCUSDT", contribution=100.0, stride_days=7.0,
                          n_contributions=40, include_funding=False, leverage=2.0)
    assert not levered.uses_analytic
    # On a straight line at 1x the two evaluators agree, which is the invariant
    # test_analytic_matches_simulator guards; the point here is that both routes
    # produce a number rather than the analytic one being taken for both.
    assert np.isfinite(tm_q05_on_path(plain, p, close))
    assert np.isfinite(tm_q05_on_path(levered, p, close))
    assert tm_q05_on_path(levered, p, close) > tm_q05_on_path(plain, p, close)


# --------------------------------------------------------------------------
# a second vendor gets a veto and nothing else
# --------------------------------------------------------------------------
def test_an_unverified_provider_is_never_called(monkeypatch):
    """A CLI whose flags have not been checked would report a usage error on
    stderr and a non-zero exit, which LLMUnavailable is right to raise on --
    but a provider that half-works could return help text and have it parsed
    as a verdict. It is not called at all until it is marked verified."""
    from orc import llm

    monkeypatch.setattr(llm, "providers", lambda: {
        "claude": dict(llm.BUILTIN_PROVIDERS["claude"]),
        "codex": {**llm.BUILTIN_PROVIDERS["codex"], "verified": False}})
    with pytest.raises(llm.LLMUnavailable, match="not marked verified"):
        llm.ask("anything", provider="codex")
    state = llm.availability()["codex"]
    assert "unverified" in state or "unavailable" in state


def test_a_second_adversary_can_only_kill(monkeypatch, tmp_path):
    """The asymmetry is the whole design. A second opinion that can only veto
    can only slow the growth of N; a second PROPOSER would raise it, and N is
    the denominator of every correction this project will ever apply."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import reasoning
    from orc import llm

    p = tmp_path / "H9100.json"
    p.write_text(json.dumps({"hypothesis_id": "H9100", "family": "f", "claim": "c",
                             "kill_condition": "k", "universe": ["BTCUSDT"],
                             "grid": {"stride_days": [1.0, 7.0, 30.0]}}), encoding="utf-8")

    monkeypatch.setattr(llm, "availability", lambda: {"claude": "ready", "codex": "ready"})
    monkeypatch.setattr(llm, "load_prompt", lambda *a, **k: "prompt")

    answers = {"claude": {"verdict": "REGISTER", "reason": "the payer is real"},
               "codex": {"verdict": "REGISTER", "reason": "agreed"}}
    # The batch call, because that is what review() makes: the veto is
    # unanimous-to-register, so every provider has to be asked either way and
    # asking them one after another cost the sum of two model calls.
    monkeypatch.setattr(llm, "ask_json_many",
                        lambda prompt, names, **kw: ({n: answers[n] for n in names}, {}))
    v = reasoning.review(p)
    assert v["verdict"] == "REGISTER"
    assert v["reviewed_by"] == ["claude", "codex"]
    assert "[codex] agreed" in v["reason"]

    # One veto is enough, whichever vendor casts it, and the record says who.
    answers["codex"] = {"verdict": "KILL", "reason": "nobody is structurally paying"}
    v = reasoning.review(p)
    assert v["verdict"] == "KILL"
    assert v["killed_by"] == "adversary:codex"
    assert "nobody is structurally paying" in v["reason"]

    # A provider that cannot be reached is skipped, never counted as agreeing.
    # ask_json_many reports it in the second return value rather than raising,
    # which is the same rule the serial loop kept and the one that matters:
    # silence is not a vote.
    def one_down(prompt, names, **kw):
        return ({"claude": {"verdict": "REGISTER", "reason": "the payer is real"}},
                {"codex": "not on PATH"})

    monkeypatch.setattr(llm, "ask_json_many", one_down)
    v = reasoning.review(p)
    assert v["verdict"] == "REGISTER"
    assert v["reviewed_by"] == ["claude"]
    assert "codex" in v["not_reviewed_by"]

    # None reachable is not approval.
    monkeypatch.setattr(llm, "availability", lambda: {"claude": "unavailable: x"})
    with pytest.raises(llm.LLMUnavailable):
        reasoning.review(p)


def test_the_handoff_lists_only_fields_the_evaluator_has():
    """Three of the first five proposals named parameters the config types do
    not have. The hand-off carries the real field names for exactly that
    reason, so it must be generated from the dataclasses, never typed out."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import handoff
    from orc.orchestrator.spec import SignalTrialConfig, TrialConfig

    a, b = handoff._axes(TrialConfig), handoff._axes(SignalTrialConfig)
    assert "stride_days" in a and "gate" in a and "symbol" not in a
    assert "enter_rate" in b and "lookback_days" in b and "symbol" not in b
    # the axes that killed H0003, H0004 and H0005
    for ghost in ("side", "spread_enter", "gate_rate", "oi_lookback_days"):
        assert ghost not in a and ghost not in b


def test_an_untested_mechanism_gets_a_probe_not_an_enumeration(monkeypatch):
    """73.4 % of N went to H0002: 972 cells on the first and only test its
    mechanism ever got, now closed. H0006 answered its question with 72 and
    H0007 with 54. Width is not what buys an answer, and spending it before a
    mechanism has survived anything is how one guess ends up owning the
    multiple-testing denominator for the life of the project."""
    from orc import config as cfg
    from orc.orchestrator.spec import probe_ceiling

    tested = {"already_probed"}
    assert probe_ceiling("brand_new_mechanism", tested) == cfg.MAX_PROBE_CONFIGURATIONS
    assert probe_ceiling("already_probed", tested) == cfg.MAX_CONFIGURATIONS_PER_HYPOTHESIS
    # calibration: what H0002 was, against what H0006 and H0007 already were
    assert 972 > cfg.MAX_PROBE_CONFIGURATIONS >= 72


def test_intake_refuses_a_wide_grid_on_an_untested_mechanism(tmp_path, monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import reasoning

    monkeypatch.setattr("orc.orchestrator.spec.probe_ceiling",
                        lambda family, tested=None: 96)
    wide = tmp_path / "H9200.json"
    wide.write_text(json.dumps({
        "hypothesis_id": "H9200", "family": "never_tested", "claim": "c",
        "kill_condition": "k", "universe": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        "grid": {"stride_days": [1.0, 7.0, 30.0], "n_contributions": [26, 52, 104, 156],
                 "hold_days": [0.0, 30.0, 90.0], "include_funding": [True, False],
                 "leverage": [1.0, 2.0]}}), encoding="utf-8")
    why = reasoning.expandable(wide)
    assert why and "PROBE" in why and "H0002" in why

    narrow = tmp_path / "H9201.json"
    narrow.write_text(json.dumps({
        "hypothesis_id": "H9201", "family": "never_tested", "claim": "c",
        "kill_condition": "k", "universe": ["BTCUSDT", "ETHUSDT"],
        "grid": {"stride_days": [1.0, 7.0, 30.0], "n_contributions": [52, 104, 156]}}),
        encoding="utf-8")
    assert reasoning.expandable(narrow) is None


# --------------------------------------------------------------------------
# a review step may read and answer; it may not change the repository
# --------------------------------------------------------------------------
def test_the_agent_pointer_is_not_a_second_constitution():
    """AGENTS.md exists because the Codex CLI reads it the way Claude Code
    reads CLAUDE.md. It was briefly a verbatim 193-line copy of the
    constitution, written by an adversary review that was supposed to be
    read-only. Two copies of a protocol document is how a protocol rots: one
    gets an amendment and nothing tells the other."""
    root = Path(__file__).resolve().parents[1]
    agents = root / "AGENTS.md"
    if not agents.exists():
        return
    a = agents.read_text(encoding="utf-8")
    c = (root / "CLAUDE.md").read_text(encoding="utf-8")
    assert len(a) < len(c) / 4, "AGENTS.md has grown into a copy of the constitution"
    assert "CLAUDE.md" in a, "AGENTS.md must point at the constitution"
    # the section headings that make it a constitution rather than a pointer
    for heading in ("## 1. Clean room", "## 4. Metrics", "## 9. What a reasoning"):
        assert heading not in a


def test_a_read_only_call_that_dirties_the_tree_is_recorded(monkeypatch, tmp_path):
    """--allowedTools enforces this for one vendor. A second vendor has its own
    flags and its own idea of a sandbox, and codex wrote to the tree under
    `--sandbox read-only`, so the promise needed enforcing rather than
    restating. Nothing is reverted: deleting a file the project did not expect
    is a worse failure than reporting one."""
    from orc import llm

    monkeypatch.setattr(llm, "providers", lambda: {
        "toy": {"binary": "toy", "argv": [], "stdin": True, "verified": True}})
    monkeypatch.setattr(llm, "_binary", lambda provider="toy": "toy")

    states = iter([" M orc/eval/signal.py\n",
                   " M orc/eval/signal.py\n?? AGENTS.md\n"])
    monkeypatch.setattr(llm, "tree_fingerprint", lambda cwd=None: next(states))

    class R:
        returncode, stdout, stderr = 0, "a verdict", ""
    monkeypatch.setattr(llm.subprocess, "run", lambda *a, **k: R())

    llm.ask.tree_violations.clear()
    assert llm.ask("prompt", cwd=tmp_path, provider="toy") == "a verdict"
    assert llm.ask.tree_violations == [{"provider": "toy", "files": ["AGENTS.md"]}]

    # A call that leaves the tree alone records nothing.
    same = iter([" M orc/eval/signal.py\n", " M orc/eval/signal.py\n"])
    monkeypatch.setattr(llm, "tree_fingerprint", lambda cwd=None: next(same))
    llm.ask.tree_violations.clear()
    llm.ask("prompt", cwd=tmp_path, provider="toy")
    assert llm.ask.tree_violations == []


def test_the_providers_are_asked_at_once_and_not_in_turn(monkeypatch):
    """The veto is unanimous-to-register and the close vote needs every ballot,
    so both steps ask every provider whatever the first one says.  Asked in
    turn they cost the SUM of two model calls -- the scout paid 483s on the run
    that found three payers -- for two questions that do not depend on each
    other.

    The barrier is the check.  Each fake call blocks until the OTHER one has
    also arrived, so this passes only if the two are genuinely in flight
    together; a serial loop reaches it one at a time and the wait expires."""
    import threading

    from orc import llm

    monkeypatch.setattr(llm, "providers", lambda: {
        name: {"binary": name, "argv": [], "stdin": True, "verified": True}
        for name in ("alpha", "beta")})
    monkeypatch.setattr(llm, "_binary", lambda provider=None: str(provider))

    both_inside = threading.Barrier(2, timeout=30)

    class R:
        returncode, stderr = 0, ""
        stdout = '{"verdict": "REGISTER"}'

    def fake_run(cmd, **kw):
        both_inside.wait()
        return R()

    monkeypatch.setattr(llm.subprocess, "run", fake_run)

    replies, errors = llm.ask_many("prompt", ["alpha", "beta"])
    assert errors == {}
    assert sorted(replies) == ["alpha", "beta"]


def test_a_provider_that_could_not_answer_is_reported_and_never_a_yes(monkeypatch):
    """Both callers read the batch as ballots: `review` registers only if no
    verdict objects, `close_votes` closes only on agreement.  A provider that
    was never reached, or that answered in prose, must therefore land in the
    ERRORS half -- silently dropping it from both halves turns an absent
    adversary into consent, which is the one failure mode of a unanimous
    veto."""
    from orc import llm

    monkeypatch.setattr(llm, "providers", lambda: {
        "alpha": {"binary": "alpha", "argv": [], "stdin": True, "verified": True},
        "prosy": {"binary": "prosy", "argv": [], "stdin": True, "verified": True},
        "beta": {"binary": "beta", "argv": [], "stdin": True, "verified": False}})
    monkeypatch.setattr(llm, "_binary", lambda provider=None: str(provider))

    bodies = {"alpha": '{"verdict": "REGISTER"}',
              "prosy": "I think this one is fine, honestly."}

    def fake_run(cmd, **kw):
        class R:
            returncode, stderr = 0, ""
            stdout = bodies[cmd[0]]
        return R()

    monkeypatch.setattr(llm.subprocess, "run", fake_run)

    # "gamma" is not in the registry at all; "beta" is there but unverified.
    verdicts, unreachable = llm.ask_json_many(
        "prompt", ["alpha", "prosy", "beta", "gamma"])

    assert list(verdicts) == ["alpha"]
    assert verdicts["alpha"] == {"verdict": "REGISTER"}
    # every provider asked is accounted for in exactly one of the two halves
    assert set(verdicts) | set(unreachable) == {"alpha", "prosy", "beta", "gamma"}
    assert set(verdicts) & set(unreachable) == set()
    assert "no JSON object" in unreachable["prosy"]
    assert "not marked verified" in unreachable["beta"]


def test_a_concurrent_batch_that_dirties_the_tree_names_everyone_who_was_running(
        monkeypatch, tmp_path):
    """`ask` fingerprints the tree per call so an edit is attributed to whoever
    made it.  Two calls in one directory would each see the other's edits and
    name the wrong provider, so the batch takes the fingerprint ONCE around the
    whole thing and records the set that was in flight.  That is a weaker
    attribution than the serial path gives; the alternative is a confident and
    wrong one."""
    from orc import llm

    monkeypatch.setattr(llm, "providers", lambda: {
        name: {"binary": name, "argv": [], "stdin": True, "verified": True}
        for name in ("alpha", "beta")})
    monkeypatch.setattr(llm, "_binary", lambda provider=None: str(provider))

    class R:
        returncode, stderr = 0, ""
        stdout = "a verdict"
    monkeypatch.setattr(llm.subprocess, "run", lambda *a, **k: R())

    states = iter([" M orc/eval/signal.py\n",
                   " M orc/eval/signal.py\n?? AGENTS.md\n"])
    monkeypatch.setattr(llm, "tree_fingerprint", lambda cwd=None: next(states))

    llm.ask.tree_violations.clear()
    replies, errors = llm.ask_many("prompt", ["beta", "alpha"], cwd=tmp_path)
    assert errors == {} and len(replies) == 2

    assert len(llm.ask.tree_violations) == 1
    v = llm.ask.tree_violations[0]
    assert v["provider"] == "alpha+beta"     # sorted, and nobody is singled out
    assert v["files"] == ["AGENTS.md"]
    assert "cannot be attributed" in v["note"]

    # A batch that leaves the tree alone records nothing.
    same = iter([" M orc/eval/signal.py\n", " M orc/eval/signal.py\n"])
    monkeypatch.setattr(llm, "tree_fingerprint", lambda cwd=None: next(same))
    llm.ask.tree_violations.clear()
    llm.ask_many("prompt", ["alpha", "beta"], cwd=tmp_path)
    assert llm.ask.tree_violations == []


def test_the_scout_merges_in_turn_even_though_it_asks_at_once(monkeypatch, tmp_path):
    """The merge dedupes each candidate payer against the notebook on disk.
    Asking is what got parallelised; merging did not, because two appends racing
    would each miss what the other had just written and record the same payer
    twice -- and a duplicate payer is a mechanism the proposer thinks is two."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import scout

    nb = tmp_path / "SCOUT.jsonl"
    monkeypatch.setattr(scout, "NOTEBOOK", nb)
    monkeypatch.setattr(scout, "closed_mechanisms", lambda: "")
    monkeypatch.setattr(scout, "reject", lambda rec: None)

    body = json.dumps([{"payer": "the market maker quoting into a funding flip",
                        "why_they_keep_paying": "inventory it cannot refuse",
                        "observable": "funding_rate", "test": "carry side"}])

    first = scout.scout_once("alpha", notebook=nb, text=body)
    assert len(first["added"]) == 1

    # The identical payer from the second provider is merged AFTER the first,
    # sees it on disk, and is a duplicate rather than a second mechanism.
    second = scout.scout_once("beta", notebook=nb, text=body)
    assert second["added"] == []
    assert len(second["duplicates"]) == 1
    assert len(nb.read_text(encoding="utf-8").strip().splitlines()) == 1

    # A provider the batch could not reach is that provider's error, and does
    # not stop the others from being merged.
    dead = scout.scout_once("gamma", notebook=nb, error="exit 1: not on PATH")
    assert dead["error"] == "exit 1: not on PATH"
    assert dead["added"] == []


def test_closing_a_family_needs_agreement_and_a_split_closes_nothing(monkeypatch, tmp_path):
    """Section 9 step 2 was being decided by the proposer in prose -- one model,
    one paragraph, no cross-check -- on the decision that matters most. A family
    closed too early is a question abandoned; one left open is re-enumerated
    every six hours, which is how H0002 came to hold 73 % of N."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import reasoning
    from orc import config as cfg
    from orc import llm

    reg, closed, reports = tmp_path / "reg", tmp_path / "closed", tmp_path / "rep"
    for d in (reg, closed, reports):
        d.mkdir()
    h = _hyp(hypothesis_id="H9300", kill_condition="Closed if PBO is at or above 0.5.")
    h.register().save(reg / "H9300.json")
    (reports / "H9300_SURFACE.json").write_text(json.dumps(
        {"metric": "tm_q05", "pbo": {"BTCUSDT": {"pbo": 0.82}}, "surfaces": {}}),
        encoding="utf-8")

    monkeypatch.setattr(cfg, "REGISTRY", reg)
    monkeypatch.setattr(cfg, "CONFIGS", tmp_path)
    monkeypatch.setattr(cfg, "REPORTS", reports)
    monkeypatch.setattr(reasoning, "CLOSED", closed)
    monkeypatch.setattr(llm, "availability", lambda: {"claude": "ready", "codex": "ready"})
    monkeypatch.setattr(llm, "load_prompt", lambda *a, **k: "prompt")

    say = {"claude": {"verdict": "CLOSE", "clause": "PBO at or above 0.5",
                      "clause_met": True, "reason": "0.82"},
           "codex": {"verdict": "CLOSE", "clause": "PBO at or above 0.5",
                     "clause_met": True, "reason": "0.82 on BTCUSDT"}}
    monkeypatch.setattr(llm, "ask_json_many",
                        lambda prompt, names, **kw: ({n: say[n] for n in names}, {}))
    out = reasoning.close_votes()
    assert out["families"]["H9300"]["decision"] == "CLOSE"
    assert (closed / "H9300.json").exists()
    rec = json.loads((closed / "H9300.json").read_text(encoding="utf-8"))
    assert rec["closed_by"] == "close_vote:claude,codex"
    assert "[codex]" in rec["reason"] and "[claude]" in rec["reason"]

    # A split closes nothing. Two models reading one pre-registered sentence
    # differently is a fact about the sentence, and the owner should see it.
    (closed / "H9300.json").unlink()
    say["codex"] = {"verdict": "CONTINUE", "clause": "PBO at or above 0.5",
                    "clause_met": False, "reason": "only one symbol was computable"}
    out = reasoning.close_votes()
    assert out["families"]["H9300"]["decision"] == "SPLIT"
    assert not (closed / "H9300.json").exists()

    # A vote that says CONTINUE while reporting a met clause contradicts itself
    # and is not counted, so one coherent CLOSE vote stands alone.
    say["codex"] = {"verdict": "CONTINUE", "clause": "PBO", "clause_met": True,
                    "reason": "self-contradictory"}
    out = reasoning.close_votes()
    assert out["families"]["H9300"]["votes"]["codex"]["broken"]
    assert out["families"]["H9300"]["decision"] == "CLOSE"


def test_the_proposer_is_no_longer_asked_to_close_a_family():
    """Two closing paths is one too many: the vote is the authority now."""
    txt = (Path(__file__).resolve().parents[1] / "scripts" / "reasoning_prompt.txt"
           ).read_text(encoding="utf-8")
    assert "Do NOT decide whether a family should close" in txt
    assert "write configs/closed/" not in txt


def test_a_split_close_vote_is_raised_as_news(tmp_path, monkeypatch):
    """It closes nothing, so without this it sits in a JSON file nobody opens
    while the family is re-enumerated every six hours."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import notify
    from orc import config as cfg
    from datetime import datetime, timezone

    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "CYCLE_SUMMARY.json").write_text(json.dumps(
        {"finished_utc": datetime.now(timezone.utc).isoformat(), "results": []}),
        encoding="utf-8")
    (reports / "CLOSE_VOTES.json").write_text(json.dumps({"families": {
        "H9400": {"family": "split_family", "decision": "SPLIT",
                  "votes": {"claude": {"verdict": "CONTINUE"},
                            "codex": {"verdict": "CLOSE"}}},
        "H9401": {"family": "agreed_family", "decision": "CLOSE",
                  "votes": {"claude": {"verdict": "CLOSE"}}}}}), encoding="utf-8")
    monkeypatch.setattr(cfg, "REPORTS", reports)
    monkeypatch.setattr(cfg, "QUEUE", tmp_path / "queue")

    news = notify.collect()
    split = [n for n in news if "SPLIT" in n]
    assert len(split) == 1
    assert "H9400" in split[0] and "claude=CONTINUE" in split[0] and "codex=CLOSE" in split[0]
    assert not any("H9401" in n for n in news)     # agreement is not news


# --------------------------------------------------------------------------
# two machines write the ledger, so a conflict must union rather than choose
# --------------------------------------------------------------------------
def test_a_ledger_conflict_unions_and_never_picks_a_side(tmp_path):
    """Run #19 computed 112 trials over 39 minutes and lost every one: the
    ledger is a binary SQLite file, two machines write it, and the rebase
    stopped on a conflict. Rows are the one thing here that cannot be resolved
    by choosing -- N is the denominator of every correction, and taking one
    side's file discards the other side's questions with nothing to say so."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import merge_ledger
    from orc.ledger.trials import Ledger

    def build(path, run, n, shared):
        with Ledger(path) as led:
            for i in range(shared):
                led.record(run_id="shared", family="f", symbol="BTCUSDT",
                           evaluator="analytic", cfg={"a": i},
                           metrics={"tm_q05": 1.0}, n_starts=10,
                           panel_hash="ph", code="ch")
            for i in range(n):
                led.record(run_id=run, family="f", symbol="BTCUSDT",
                           evaluator="analytic", cfg={"only": f"{run}{i}"},
                           metrics={"tm_q05": 1.0}, n_starts=10,
                           panel_hash="ph", code="ch")

    ours, theirs = tmp_path / "ours.sqlite", tmp_path / "theirs.sqlite"
    build(ours, "workstation", 7, 20)
    build(theirs, "worker", 112, 20)

    n_a, n_b, total = merge_ledger.union(ours, theirs, ours)
    assert (n_a, n_b) == (27, 132)
    assert total == 20 + 7 + 112       # the shared twenty are one experiment
    with Ledger(ours) as led:
        got = dict(led.conn.execute(
            "SELECT run_id, COUNT(*) FROM trials GROUP BY run_id"))
    assert got["workstation"] == 7 and got["worker"] == 112 and got["shared"] == 20


def test_the_merge_driver_refuses_rather_than_shrink_the_ledger(tmp_path):
    """N can only grow. A union that returns fewer rows than one side had is a
    bug, and a silent one is a deleted experiment."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import merge_ledger

    empty_a, empty_b = tmp_path / "a.sqlite", tmp_path / "b.sqlite"
    empty_a.write_bytes(b"")
    empty_b.write_bytes(b"")
    with pytest.raises(SystemExit, match="readable ledger"):
        merge_ledger.union(empty_a, empty_b, empty_a)

    # A side with no ledger at all contributes nothing and does not abort:
    # having recorded no trials is a fact, not an error.
    from orc.ledger.trials import Ledger
    real = tmp_path / "real.sqlite"
    with Ledger(real) as led:
        led.record(run_id="r", family="f", symbol="BTCUSDT", evaluator="analytic",
                   cfg={"a": 1}, metrics={"tm_q05": 1.0}, n_starts=1,
                   panel_hash="ph", code="ch")
    assert merge_ledger.union(real, tmp_path / "absent.sqlite", real)[2] == 1


def test_the_ledger_is_pointed_at_the_union_driver():
    """A driver nothing routes to is a driver that never runs."""
    ga = (Path(__file__).resolve().parents[1] / ".gitattributes"
          ).read_text(encoding="utf-8")
    assert "ledger/trials.sqlite merge=orcledger" in ga
    assert "reports/*.json merge=ours" in ga
    wf = (Path(__file__).resolve().parents[1] / ".github" / "workflows"
          / "orc-cycle.yml").read_text(encoding="utf-8")
    assert "merge.orcledger.driver" in wf and "merge_ledger.py" in wf
    assert "merge.ours.driver" in wf


def test_the_surface_takes_the_newest_row_by_time_not_by_rowid():
    """A union re-assigns trial_id by insertion order, so rows that arrived
    from another machine carry ids that say nothing about when they were
    computed. 'The last write wins by construction' stopped being true of the
    surrogate key the moment the ledger acquired a merge driver."""
    src = (Path(__file__).resolve().parents[1] / "orc" / "orchestrator"
           / "surface.py").read_text(encoding="utf-8")
    # Table alias tolerated: the query joins trial_hypotheses, so the columns
    # are qualified.  What must not change is ordering by TIME rather than by
    # the surrogate key.
    import re as _re
    assert _re.search(r"ORDER BY\s+(?:\w+\.)?created_utc,\s*(?:\w+\.)?trial_id", src)
    assert "ORDER BY trial_id" not in src


def test_the_precommit_guard_is_installed_and_refuses_what_it_says():
    """The guard exists because six defects in one session were all the same
    habit: claiming a thing was done without checking it. A guard that is
    documented but not installed is that habit again."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import precommit

    root = Path(__file__).resolve().parents[1]
    hook = root / ".git" / "hooks" / "pre-commit"
    if hook.exists():
        assert "precommit.py" in hook.read_text(encoding="utf-8")

    # a new top-level file is where a tool writing into the tree lands
    assert precommit.check_new_files([("A", "SOMETHING_WROTE_THIS.md")])
    assert not precommit.check_new_files([("A", "orc/eval/new_module.py")])
    assert not precommit.check_new_files([("M", "SOMETHING_WROTE_THIS.md")])
    assert not precommit.check_new_files([("A", "CLAUDE.md")])
    # and a file outside the tree's shape
    assert precommit.check_new_files([("A", "vendor/somelib/thing.py")])


def test_the_constitution_carries_the_rule_the_guard_enforces():
    """A guard whose reason lives only in a commit message is a guard the next
    session removes."""
    s = (Path(__file__).resolve().parents[1] / "CLAUDE.md").read_text(encoding="utf-8")
    assert "## 10. A claim is checked before it is written down" in s
    assert "Never stage by wildcard" in s
    assert "goes into the findings ledger, not into a" in s


def test_health_reports_every_section_without_touching_anything(monkeypatch, capsys):
    """The one screen an owner can check between sessions. It must be readable
    with no network, no scheduler and no gh, and it must never write."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import health

    # No gh, no PowerShell, no test run: the screen still has to render.
    monkeypatch.setattr(health.subprocess, "run",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("absent")))
    worst = health.render(run_tests=False)
    out = capsys.readouterr().out
    assert "MACHINE -- is it running" in out
    assert "RESEARCH -- is it producing" in out
    assert "HEALTH -- would I know if it broke" in out
    # the two facts that are easiest to misread as failure
    assert "FAIL is the product" in out
    assert "N = " in out
    assert isinstance(worst, int) and 0 <= worst <= 2
    # and it says nothing about a closed family being skipped
    assert "not re-run" not in out


def test_the_surface_defines_every_key_the_headline_reads():
    """A block replacement dropped `mwrr_q05_best` and every Track A return in
    the committed cycle report read n/a for four hours, while the median beside
    it printed fine. A headline field that is None because its key was never
    defined is a defect; one that is None because the metric was unmeasured is a
    fact. They must not print the same way."""
    src = (Path(__file__).resolve().parents[1] / "orc" / "orchestrator"
           / "surface.py").read_text(encoding="utf-8")
    # every *_best the headline reads has to be assigned somewhere in the module
    for key in ("mwrr_q05_best", "mwrr_q50_best", "cagr_best",
                "max_drawdown_best", "primary_metric_best"):
        assert f'"{key}": ' in src, f"{key} is read but never assigned"
    assert "would report n/a for a reason that is a defect" in src


# ---------------------------------------------------------------------------
# The nine high findings that stopped the loop on 2026-09-04 (part two).
# The three in tests/test_kernel.py are the arithmetic; these are the identity,
# the attribution, the routing and the counter.
# ---------------------------------------------------------------------------
def test_a_cell_has_one_identity_whatever_spelled_it():
    """1fda815109fc.  config_hash was decided by JSON representation rather than
    by value: json.dumps writes 7 as "7" and 7.0 as "7.0", and a numpy scalar is
    not JSON-serialisable at all so `default=str` turned np.int64(7) into the
    STRING "7".  One cell could hold three identities -- three rows, three
    contributions to N, and a dedupe that had silently stopped working."""
    import numpy as np

    from orc.ledger.trials import canonical_hash

    base = canonical_hash({"n": 7, "contribution": 100.0})
    assert canonical_hash({"n": 7.0, "contribution": 100.0}) == base
    assert canonical_hash({"n": np.int64(7), "contribution": 100.0}) == base
    assert canonical_hash({"n": np.float64(7.0), "contribution": 100}) == base

    # Distinctions that are real must survive: a different value, and True
    # rather than 1.  bool IS an int in Python, which is why it is checked first.
    assert canonical_hash({"n": 8}) != canonical_hash({"n": 7})
    assert canonical_hash({"n": True}) != canonical_hash({"n": 1})
    # NaN is not JSON and must not round-trip as a bare NaN token.
    h = canonical_hash({"n": float("nan")})
    assert h == canonical_hash({"n": float("nan")})
    assert h != canonical_hash({"n": 0.0})


def test_a_second_hypothesis_sees_a_cell_an_earlier_one_measured(tmp_path,
                                                                 monkeypatch):
    """3f5eecddcf2e.  hypothesis_id rides on the trial row but is not in its
    UNIQUE key, so a second hypothesis enumerating a cell the first already ran
    was INSERT OR IGNORE'd, the row kept the first id, and surface_from_ledger's
    `WHERE hypothesis_id=?` reported those cells as never run -- a full grid of
    real measurements reading as empty.

    N must not move: the measurement was not repeated, so no row is added.  The
    attribution is what has to be recorded."""
    from orc import config as _config
    from orc.ledger.trials import Ledger

    monkeypatch.setattr(_config, "LEDGER_DB", tmp_path / "trials.sqlite")
    args = dict(run_id="r1", family="fam", symbol="BTCUSDT", evaluator="analytic",
                cfg={"stride_days": 7, "n_contributions": 52},
                metrics={"tm_q05": 1.2}, n_starts=10, panel_hash="p1", code="c1")
    with Ledger() as led:
        id_a, new_a = led.record(hypothesis_id="H0001", **args)
        id_b, new_b = led.record(hypothesis_id="H0002", **args)
        assert new_a is True and new_b is False, "the measurement was repeated"
        assert id_a == id_b
        assert led.total_trials() == 1, "N moved for a measurement never repeated"
        seen = {r[0] for r in led.conn.execute(
            "SELECT hypothesis_id FROM trial_hypotheses WHERE trial_id=?",
            (id_a,)).fetchall()}
        assert seen == {"H0001", "H0002"}


def test_the_panel_cache_is_keyed_on_the_clock_as_well_as_the_symbol():
    """0e76e5167368.  `panels: dict[str, Panel]` keyed on cfg.symbol alone, so a
    grid with clock on an axis scored every configuration after the first
    against whichever clock came first -- minute rules measured on hourly bars,
    with panel_hash recording the wrong panel."""
    src = (Path(__file__).resolve().parents[1] / "orc" / "orchestrator"
           / "runner.py").read_text(encoding="utf-8")
    assert "panels: dict[tuple[str, str], Panel]" in src
    assert "key = (cfg.symbol, cfg.clock)" in src
    assert "if cfg.symbol not in panels" not in src


def test_the_track_a_null_scores_the_statistic_the_search_selected_on():
    """1d24187e83e0.  write_report passes surfaces[sym]["best_value"], ranked by
    ranking_metric on mwrr_q05 -- an annualised RETURN, ~0.14 -- and the Track A
    null scored every synthetic path with tm_q05_on_path, a terminal MULTIPLE,
    ~3.6 for the same cell.  The p-value was the answer to a question about
    units.  Track B was already consistent on calmar; this is Track A catching
    up."""
    from orc.orchestrator import runner
    from orc.orchestrator.surface import ranking_metric

    src = (Path(__file__).resolve().parents[1] / "orc" / "orchestrator"
           / "surface.py").read_text(encoding="utf-8")
    assert "mwrr_q05_on_path" in src
    assert "tm_q05_on_path" not in src, \
        "the Track A null is scoring terminal multiples again"
    assert hasattr(runner, "mwrr_q05_on_path")

    class _H:
        track = "A"

    assert ranking_metric(_H()) == "mwrr_q05"


def test_the_opening_counter_only_ever_resolves_upward(tmp_path, monkeypatch):
    """356ad9d05565 and 11971cd77077.  The irreversible counter was rebuilt from
    one file: a missing log read as "never opened" rather than as "unknown", so
    an `rm` restored all three openings; and max() over ordinals collapsed two
    records both claiming opening 2 into a single opening.

    Every way this number can be wrong makes it too SMALL, and each of those is
    a restored look at the sealed data, so every disagreement resolves upward."""
    log = tmp_path / "log.jsonl"
    monkeypatch.setattr(holdout, "LOG_FILE", log)

    assert holdout.openings_used() == 0, "a fresh project is genuinely at zero"

    # Two records that both claim opening 1: max() said one, but two openings
    # really happened.
    log.write_text('{"opening": 1}\n{"opening": 1}\n', encoding="utf-8")
    assert holdout.openings_used() == 2

    # A log that lost its lines cannot restore an opening: the ordinal stands.
    log.write_text('{"opening": 3}\n', encoding="utf-8")
    assert holdout.openings_used() == 3

    # And losing the log entirely does not reset the count, because the state
    # file is a second record of it.
    log.unlink()
    holdout.state_file().write_text('{"openings_used": 2}', encoding="utf-8")
    assert holdout.openings_used() == 2


def test_the_opening_state_file_follows_the_log_and_never_the_real_ledger(
        tmp_path, monkeypatch):
    """The defect introduced while fixing the two above, caught by the suite
    within one run: the state file started life as a module constant beside
    LOG_FILE, and the holdout tests redirect TOKEN_FILE and LOG_FILE to tmp_path
    but had never heard of a third path.  One test run wrote "3 openings used"
    into the REAL ledger directory.  A test that spends the project's
    irreversible openings is worse than the defect being fixed.

    Deriving the path from LOG_FILE means anything that redirects the log
    redirects this too."""
    real = holdout.state_file()
    log = tmp_path / "log.jsonl"
    monkeypatch.setattr(holdout, "LOG_FILE", log)
    assert holdout.state_file().parent == tmp_path
    assert holdout.state_file() != real

    tok = tmp_path / "TOKEN"
    monkeypatch.setattr(holdout, "TOKEN_FILE", tok)
    tok.write_text(holdout.TOKEN_TEXT, encoding="utf-8")
    holdout.open_final_test({"cfg": "a"}, "because")

    assert holdout.state_file().exists()
    assert json.loads(holdout.state_file().read_text(encoding="utf-8"))[
        "openings_used"] == 1
    assert not real.exists(), \
        "a test wrote to the real irreversible holdout counter"


def test_an_ordinal_already_in_the_log_is_never_written_twice(tmp_path,
                                                              monkeypatch):
    """11971cd77077, the second half: open_final_test never checked that the
    ordinal it was about to write was unused, so a count that came back too
    small spent an opening that had already been spent."""
    log = tmp_path / "log.jsonl"
    tok = tmp_path / "TOKEN"
    monkeypatch.setattr(holdout, "LOG_FILE", log)
    monkeypatch.setattr(holdout, "TOKEN_FILE", tok)
    # A log whose highest ordinal disagrees with what openings_used reports:
    # the next ordinal is 2, which is already present.
    log.write_text('{"opening": 2}\n', encoding="utf-8")
    monkeypatch.setattr(holdout, "openings_used", lambda: 1)
    tok.write_text(holdout.TOKEN_TEXT, encoding="utf-8")
    with pytest.raises(holdout.HoldoutViolation, match="already recorded"):
        holdout.open_final_test({"cfg": "a"}, "because")
    assert tok.exists(), "the token was spent on a refused opening"


# Module level, and not closures: these cross a process boundary in the pool
# tests below, which is the whole point of them.
class _SumScorer:
    """Deterministic in the path, so serial and pooled must agree exactly."""

    def __init__(self, k: float):
        self.k = k

    def __eq__(self, other):
        return isinstance(other, _SumScorer) and other.k == self.k

    def __call__(self, close):
        import numpy as np
        return float(np.mean(close) * self.k)


class _EveryThirdRaises:
    """One path in three cannot be scored, the way a real grid meets a path it
    cannot express."""

    def __call__(self, close):
        import numpy as np
        if int(abs(np.sum(close))) % 3 == 0:
            raise ValueError("this path cannot be expressed")
        return float(np.mean(close))


# ---------------------------------------------------------------------------
# The pool.  The search test is the most expensive thing the project does and
# it was running on one core of twenty-four: 4.77s per synthetic path over the
# H0001/BTCUSDT grid, 15.8 minutes for 199 paths, 31.7 for the two symbols a
# report covers -- which was the whole research cycle.
# ---------------------------------------------------------------------------
def test_the_null_scorers_can_cross_a_process_boundary():
    """A closure cannot be pickled, so the null scorers are objects.  If either
    goes back to being a closure the pool silently falls back to serial and the
    cycle quietly costs half an hour again -- silently, because the fallback is
    deliberate and correct for every OTHER caller."""
    import pickle

    from orc.orchestrator.search_test import _is_picklable
    from orc.orchestrator.surface import _TrackANullScorer, _TrackBNullScorer

    for cls in (_TrackANullScorer, _TrackBNullScorer):
        s = cls(configs=(), symbol="BTCUSDT", clock="1h")
        assert _is_picklable(s), f"{cls.__name__} cannot reach a worker"
        assert pickle.loads(pickle.dumps(s)) == s

    # And a closure still falls back rather than raising.
    def closure(close):
        return 0.0

    assert not _is_picklable(closure)


def test_the_pool_changes_the_wall_clock_and_not_the_answer(monkeypatch):
    """Every synthetic path is drawn up front from one seeded generator and the
    results are consumed in order, so serial and pooled must agree exactly --
    not approximately.  Measured on the real grid at 48 paths: 229.9s serial,
    24.1s pooled, 9.55x, and every field of the verdict identical."""
    import numpy as np

    from orc.orchestrator import search_test as st

    class _Panel:
        close = np.exp(np.cumsum(
            np.random.default_rng(7).normal(0, 0.01, 4096))) * 100.0

    scorer = _SumScorer(0.25)

    monkeypatch.setenv("ORC_WORKERS", "1")
    serial = st.best_of_g(1.0, scorer, _Panel(), 8, n_paths=24)
    monkeypatch.setenv("ORC_WORKERS", "4")
    pooled = st.best_of_g(1.0, scorer, _Panel(), 8, n_paths=24)

    assert serial == pooled
    assert serial["n_null"] == 24


def test_a_path_the_grid_cannot_express_does_not_kill_the_null(monkeypatch):
    """The serial loop caught a failing path inline.  A pool has to catch it
    INSIDE the worker, or the exception surfaces where the result is consumed
    and takes the whole null with it -- turning one unscoreable path into no
    p-value at all."""
    import numpy as np

    from orc.orchestrator import search_test as st

    class _Panel:
        close = np.exp(np.cumsum(
            np.random.default_rng(11).normal(0, 0.01, 2048))) * 100.0

    monkeypatch.setenv("ORC_WORKERS", "4")
    pooled = st.best_of_g(1.0, _EveryThirdRaises(), _Panel(), 4, n_paths=24)
    assert pooled["status"] == "ok", "one unscoreable path took the whole null"
    assert 0 < pooled["n_null"] < 24, "nothing was dropped, so nothing raised"

    # The count is not written down here, because a number this test guessed
    # would be a number it is asserting about itself.  What must be true is
    # that the pool drops exactly the paths the serial loop drops.
    monkeypatch.setenv("ORC_WORKERS", "1")
    serial = st.best_of_g(1.0, _EveryThirdRaises(), _Panel(), 4, n_paths=24)
    assert serial == pooled


def test_the_worker_count_is_bounded_by_the_work_and_overridable(monkeypatch):
    """A pool wider than the machine is slower, and the GitHub runner has far
    fewer cores than the workstation."""
    from orc.orchestrator import search_test as st

    monkeypatch.delenv("ORC_WORKERS", raising=False)
    assert st.n_workers(4) <= 4, "more workers than tasks"
    assert st.n_workers(10_000) <= (os.cpu_count() or 1)

    monkeypatch.setenv("ORC_WORKERS", "3")
    assert st.n_workers(199) == 3
    monkeypatch.setenv("ORC_WORKERS", "nonsense")
    assert st.n_workers(199) >= 1


def test_a_file_that_was_already_dirty_is_still_watched(tmp_path):
    """The hole the detector had, found the hard way on 2026-09-04.

    A reasoning pass ran while tests/test_protocol.py was already modified, and
    a provider appended four tests to it. The file was " M" before the call and
    " M" after; the status lines were identical; nothing was recorded. The
    detector could see a file BECOME dirty and could not see a dirty file being
    edited further -- blind over exactly the files someone is working on, which
    is where an unattended model writing into the tree does the most harm.

    So each dirty path carries a hash of its content. The status-line set is
    unchanged here, which is the whole point: this passes only because the
    fingerprint stopped being the status line.
    """
    import subprocess

    from orc import llm

    def git(*a):
        return subprocess.run(("git",) + a, cwd=tmp_path, capture_output=True,
                              text=True)

    git("init", "-q")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    f = tmp_path / "notes.py"
    f.write_text("original\n", encoding="utf-8")
    git("add", "notes.py")
    git("commit", "-qm", "base")

    f.write_text("original\nan edit of my own\n", encoding="utf-8")
    before = llm.tree_fingerprint(tmp_path)
    f.write_text("original\nan edit of my own\nand one nobody asked for\n",
                 encoding="utf-8")
    after = llm.tree_fingerprint(tmp_path)

    # What the old detector compared, and why it saw nothing.
    status_only = lambda s: {ln[3:].split("\t")[0] for ln in s.splitlines()}
    assert status_only(before) == status_only(after)

    assert before != after, "a further edit to an already-dirty file is invisible"
    b = {ln[3:] for ln in before.splitlines()}
    a = {ln[3:] for ln in after.splitlines()}
    assert sorted({llm._named(e) for e in a - b}) == ["notes.py"]

    # A tree nobody touched still reports nothing.
    assert llm.tree_fingerprint(tmp_path) == after
