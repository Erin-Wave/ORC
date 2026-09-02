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
    assert TrialConfig(symbol="X").uses_analytic
    assert not TrialConfig(symbol="X", leverage=3.0).uses_analytic
    assert not TrialConfig(symbol="X", gate="dip:0.1:30").uses_analytic
    assert not TrialConfig(symbol="X", take_profit=0.4).uses_analytic


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
    fr = funding_rate_per_bar(bars, funding)

    assert fr[8] == pytest.approx(0.0001)
    assert fr[23] == pytest.approx(0.0002), "a settlement inside the last bar still counts"
    assert fr.sum() == pytest.approx(0.0003), "nothing past the end may be charged"


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
              "pbo": {"AAA": {"status": "ok", "pbo": 0.1},
                      "BBB": {"status": "ok", "pbo": 0.1}},
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
