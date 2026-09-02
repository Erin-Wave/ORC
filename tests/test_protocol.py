"""ORC | Protocol enforcement.

These tests are not about arithmetic.  They check that the parts of the system
whose whole job is to say NO actually say no: the append-only ledger, the
pre-registration hash, and the sealed holdout.  A protocol that is only a
convention is not a protocol once the loop runs unattended.
"""
from __future__ import annotations

import json
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
    monkeypatch.setattr(config, "MAX_CONFIGURATIONS_PER_HYPOTHESIS", 10)

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
