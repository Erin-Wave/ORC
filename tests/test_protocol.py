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
from datetime import datetime
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
