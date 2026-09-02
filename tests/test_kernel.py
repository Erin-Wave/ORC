"""ORC | Kernel correctness.

The load-bearing test in this project is test_analytic_matches_simulator.
Two independent implementations -- a closed-form prefix-sum evaluator and a
bar-by-bar path simulator -- must agree to machine precision on the case both
can express.  If they ever diverge, one of them is wrong and every result that
depends on it is void.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orc import clean_room
from orc.eval.analytic import AnalyticSpec, evaluate, strided_window_sum
from orc.eval.signal import LONG as SIG_LONG, SHORT as SIG_SHORT
from orc.eval.signal import SignalSpec, run_signals
from orc.eval.simulate import (SimSpec, gate_below_sma, gate_below_trailing_peak,
                               simulate)
from orc.kernel.liquidation import (BTC_LIKE, LONG_TAIL, is_liquidated,
                                    liquidation_price_long, tier_table_for)
from orc.kernel.metrics_cf import (drawdown_on_invested, mwrr_equal_interval,
                                   mwrr_irregular, start_date_profile)

RNG = np.random.default_rng(20260902)


@pytest.fixture(scope="module")
def series():
    """A geometric random walk with fat tails and a real drawdown, 20k bars."""
    n = 20_000
    shocks = RNG.standard_t(df=3, size=n) * 0.004
    close = 100.0 * np.exp(np.cumsum(shocks))
    low = close * (1.0 - np.abs(RNG.normal(0, 0.002, n)))
    return close, np.minimum(low, close)


# --------------------------------------------------------------------------
# prefix sums
# --------------------------------------------------------------------------
def test_strided_window_sum_matches_loop():
    a = RNG.normal(size=997)
    for k, n in [(1, 5), (7, 12), (60, 3), (13, 1)]:
        sums, starts = strided_window_sum(a, k, n)
        assert starts.size > 0
        pick = RNG.choice(starts.size, size=min(50, starts.size), replace=False)
        for i in pick:
            s = int(starts[i])
            assert np.isclose(sums[i], a[s:s + (n - 1) * k + 1:k].sum(), rtol=0, atol=1e-11)


def test_strided_window_sum_rejects_impossible_window():
    assert strided_window_sum(np.ones(10), k=5, n=3)[1].size == 0


# --------------------------------------------------------------------------
# the load-bearing cross-check
# --------------------------------------------------------------------------
@pytest.mark.parametrize("stride,n_contrib,hold", [(24, 30, 0), (168, 12, 500), (1, 50, 0)])
def test_analytic_matches_simulator(series, stride, n_contrib, hold):
    close, low = series
    a = AnalyticSpec(contribution=100.0, stride_bars=stride, n_contributions=n_contrib,
                     hold_bars=hold, fee_bps=4.5, slippage_bps=1.0, exit_fee_bps=4.5)
    res = evaluate(close, a)
    assert res["n_starts"] > 100

    starts = res["start_idx"][RNG.choice(res["n_starts"], size=250, replace=False)]
    order = np.argsort(starts)
    starts = starts[order]

    s = SimSpec(contribution=100.0, stride_bars=stride, n_contributions=n_contrib,
                hold_bars=hold, leverage=1.0, fee_bps=4.5, slippage_bps=1.0,
                exit_fee_bps=4.5)
    sim = simulate(close, low, starts, s, table=BTC_LIKE)

    want = res["terminal_value"][np.searchsorted(res["start_idx"], starts)]
    got = sim["terminal_equity"]
    assert not sim["liquidated"].any(), "1x accumulation must never liquidate"
    assert np.allclose(got, want, rtol=1e-11, atol=1e-8)


def test_analytic_matches_simulator_with_funding(series):
    close, low = series
    fr = np.zeros_like(close)
    fr[::8] = 1e-4                      # +0.01 % every 8 bars, longs pay
    a = AnalyticSpec(contribution=100.0, stride_bars=24, n_contributions=30)
    res = evaluate(close, a, funding_flow=close * fr)

    starts = np.sort(res["start_idx"][RNG.choice(res["n_starts"], 200, replace=False)])
    s = SimSpec(contribution=100.0, stride_bars=24, n_contributions=30, leverage=1.0)
    sim = simulate(close, low, starts, s, funding_rate=fr, table=BTC_LIKE)

    i = np.searchsorted(res["start_idx"], starts)
    assert np.allclose(sim["funding_paid"], res["funding_paid"][i], rtol=1e-10, atol=1e-9)
    assert np.allclose(sim["terminal_equity"], res["terminal_value"][i], rtol=1e-10, atol=1e-8)


def test_funding_is_a_real_cost(series):
    """A positive funding rate must strictly reduce the outcome."""
    close, _ = series
    a = AnalyticSpec(contribution=100.0, stride_bars=24, n_contributions=30)
    free = evaluate(close, a)
    fr = np.zeros_like(close)
    fr[::8] = 1e-4
    paid = evaluate(close, a, funding_flow=close * fr)
    assert (paid["funding_paid"] > 0).mean() > 0.99
    assert np.all(paid["terminal_value"] < free["terminal_value"] + 1e-9)


# --------------------------------------------------------------------------
# liquidation
# --------------------------------------------------------------------------
def test_liquidation_price_is_consistent_with_the_test():
    wallet, qty, entry = 3000.0, 0.6, 50_000.0
    p = float(liquidation_price_long(wallet, qty, entry, BTC_LIKE))
    assert 0 < p < entry
    assert bool(is_liquidated(np.float64(wallet), np.float64(qty),
                              np.float64(entry), np.float64(p * (1 - 1e-6)), BTC_LIKE))
    assert not bool(is_liquidated(np.float64(wallet), np.float64(qty),
                                  np.float64(entry), np.float64(p * (1 + 1e-3)), BTC_LIKE))


def test_ten_x_long_liquidates_near_ten_percent():
    p = float(liquidation_price_long(3000.0, 0.6, 50_000.0, BTC_LIKE))
    drop = 1.0 - p / 50_000.0
    assert 0.090 < drop < 0.100


def test_unknown_symbol_gets_the_harshest_table():
    assert tier_table_for("SOMETHINGWEIRDUSDT") is LONG_TAIL
    assert tier_table_for("BTCUSDT") is BTC_LIKE


def test_leverage_produces_liquidations(series):
    """Sanity: a levered averaging-down book must actually be killable."""
    close, low = series
    starts = np.arange(0, 8000, 40, dtype=np.int64)
    s = SimSpec(contribution=100.0, stride_bars=24, n_contributions=30, leverage=10.0)
    out = simulate(close, low, starts, s, table=BTC_LIKE)
    assert out["liquidation_rate"] > 0.0
    assert np.all(out["terminal_equity"][out["liquidated"]] == 0.0)


# --------------------------------------------------------------------------
# gates must be causal
# --------------------------------------------------------------------------
@pytest.mark.parametrize("fn", [
    lambda c: gate_below_trailing_peak(c, 0.10, 500),
    lambda c: gate_below_sma(c, 200),
])
def test_gate_has_no_lookahead(series, fn):
    close, _ = series
    cut = 12_000
    base = fn(close)
    tampered = close.copy()
    tampered[cut:] *= 3.0                      # obliterate the future
    after = fn(tampered)
    assert np.array_equal(base[:cut], after[:cut]), "gate leaked future information"


# --------------------------------------------------------------------------
# cash-flow metrics
# --------------------------------------------------------------------------
def test_irr_solvers_agree():
    C, n, h, V = 100.0, 12, 1.0 / 12.0, 1500.0
    fast = float(mwrr_equal_interval(C, n, h, np.array([V]))[0])
    ref = mwrr_irregular(np.array([-C] * n + [V]),
                         np.array([h * j for j in range(n)] + [h * (n - 1)]))
    assert abs(fast - ref) < 1e-8


def test_irr_of_flat_outcome_is_zero():
    r = float(mwrr_equal_interval(100.0, 12, 1 / 12, np.array([1200.0]))[0])
    assert abs(r) < 1e-6


def test_total_loss_reports_minus_one():
    assert float(mwrr_equal_interval(100.0, 12, 1 / 12, np.array([0.0]))[0]) == -1.0


def test_drawdown_uses_invested_capital_not_equity():
    """Late deposits refill the account; they must not erase the drawdown."""
    contributed = np.array([100.0, 100.0, 200.0, 200.0])
    equity = np.array([100.0, 50.0, 150.0, 150.0])   # -50 pnl, then a 100 deposit
    dd = drawdown_on_invested(equity, contributed)
    assert np.isclose(dd["max_dd_abs"], 50.0)
    assert np.isclose(dd["max_dd_total"], 0.25)
    assert dd["frac_time_in_loss"] > 0.0


def test_start_date_profile_reports_the_left_tail():
    p = start_date_profile(np.arange(1000, dtype=float))
    assert p["q05"] < p["q50"] < p["q95"]
    assert p["worst"] == 0.0 and p["n"] == 1000


# --------------------------------------------------------------------------
# clean room
# --------------------------------------------------------------------------
def test_no_prior_lab_artifacts_referenced():
    hits = clean_room.scan(Path(__file__).resolve().parent.parent)
    assert not hits, "clean-room violation: " + repr(hits[:5])


# --------------------------------------------------------------------------
# Track B: the signal evaluator
#
# Nothing cross-checks this one the way the simulator cross-checks the analytic
# evaluator, so these tests carry that weight on their own.  Each pins a
# convention that a backtest gets wrong in its own favour by default.
# --------------------------------------------------------------------------
@pytest.fixture(scope="module")
def sig_series():
    n = 2_000
    close = 100.0 * np.exp(np.cumsum(RNG.normal(0, 0.003, n)))
    return close, close * 1.002, close * 0.998


def _one_trade(n, side, enter_at, exit_at):
    e = np.zeros(n, dtype=np.int8)
    e[enter_at] = side
    x = np.zeros(n, dtype=bool)
    x[exit_at] = True
    return e, x


def test_long_and_short_are_exact_mirrors_without_costs(sig_series):
    close, high, low = sig_series
    free = SignalSpec(capital=10_000.0, fee_bps=0.0, slippage_bps=0.0)
    out = []
    for side in (SIG_LONG, SIG_SHORT):
        e, x = _one_trade(close.size, side, 10, 900)
        out.append(run_signals(close, high, low, e, x, free,
                               symbol="BTCUSDT")["trades"][0]["gross"])
    assert out[0] + out[1] == pytest.approx(0.0, abs=1e-9)


def test_a_short_is_paid_the_funding_a_long_pays(sig_series):
    close, high, low = sig_series
    fr = np.zeros(close.size)
    fr[::8] = 0.0004                      # a persistently positive rate
    free = SignalSpec(capital=10_000.0, fee_bps=0.0, slippage_bps=0.0)
    paid = {}
    for side in (SIG_LONG, SIG_SHORT):
        e, x = _one_trade(close.size, side, 10, 900)
        paid[side] = run_signals(close, high, low, e, x, free, funding_rate=fr,
                                 symbol="BTCUSDT")["funding_collected"]
    assert paid[SIG_SHORT] > 0 > paid[SIG_LONG]
    assert paid[SIG_SHORT] + paid[SIG_LONG] == pytest.approx(0.0, abs=1e-9)


def test_a_signal_is_filled_on_the_next_bar_never_its_own(sig_series):
    """The bar that produced the signal must not also produce the fill price."""
    close, high, low = sig_series
    spec = SignalSpec(capital=10_000.0, fee_bps=0.0, slippage_bps=0.0)
    e, x = _one_trade(close.size, SIG_LONG, 10, 900)
    t = run_signals(close, high, low, e, x, spec, symbol="BTCUSDT")["trades"][0]
    assert t["entry_bar"] == 11
    assert t["entry_price"] == pytest.approx(close[11])
    assert t["entry_price"] != pytest.approx(close[10])


def test_a_signal_on_the_last_bars_cannot_be_traded(sig_series):
    close, high, low = sig_series
    spec = SignalSpec(capital=10_000.0)
    e = np.zeros(close.size, dtype=np.int8)
    e[-1] = SIG_LONG
    x = np.zeros(close.size, dtype=bool)
    assert run_signals(close, high, low, e, x, spec, symbol="BTCUSDT")["n_trades"] == 0


def test_stop_and_target_in_one_bar_resolve_against_us():
    """An hourly bar cannot say which came first, so the loss is taken."""
    n = 20
    close = np.full(n, 100.0)
    high = close.copy()
    low = close.copy()
    high[5] = 130.0                       # target and stop both inside bar 5
    low[5] = 70.0
    e, x = _one_trade(n, SIG_LONG, 1, 15)
    spec = SignalSpec(capital=10_000.0, leverage=1.0, fee_bps=0.0, slippage_bps=0.0,
                      stop_loss=0.10, take_profit=0.10)
    t = run_signals(close, high, low, e, x, spec, symbol="BTCUSDT")["trades"][0]
    assert t["reason"] == "stop"
    assert t["pnl"] < 0


def test_leverage_beyond_the_tier_table_is_refused():
    n = 20
    close = np.full(n, 100.0)
    e, x = _one_trade(n, SIG_LONG, 1, 15)
    spec = SignalSpec(capital=10_000.0, leverage=500.0)
    with pytest.raises(ValueError, match="exceeds"):
        run_signals(close, close, close, e, x, spec, symbol="BTCUSDT")


def test_a_liquidated_position_loses_the_whole_margin():
    n = 30
    close = np.full(n, 100.0)
    high = close.copy()
    low = close.copy()
    low[5] = 1.0                          # far below any long liquidation level
    e, x = _one_trade(n, SIG_LONG, 1, 25)
    spec = SignalSpec(capital=10_000.0, leverage=10.0, fee_bps=0.0, slippage_bps=0.0)
    r = run_signals(close, high, low, e, x, spec, symbol="BTCUSDT")
    assert r["n_liquidations"] == 1
    assert r["trades"][0]["pnl"] == pytest.approx(-10_000.0)
    assert r["final_equity"] == pytest.approx(0.0)


def test_a_short_squeeze_liquidates_the_short_side():
    n = 30
    close = np.full(n, 100.0)
    high = close.copy()
    low = close.copy()
    high[5] = 1_000.0
    e, x = _one_trade(n, SIG_SHORT, 1, 25)
    spec = SignalSpec(capital=10_000.0, leverage=5.0, fee_bps=0.0, slippage_bps=0.0)
    r = run_signals(close, high, low, e, x, spec, symbol="BTCUSDT")
    assert r["n_liquidations"] == 1
    assert r["final_equity"] == pytest.approx(0.0)


def test_a_carry_signal_cannot_see_past_its_own_bar():
    """Changing a future funding rate must not change any earlier signal."""
    from orc.eval.signal_rules import carry_funding

    n = 600
    rate = np.zeros(n)
    rate[::8] = 0.0002
    a_entry, a_exit = carry_funding(rate, lookback_bars=80, enter_rate=0.00015,
                                    exit_rate=0.00005)
    bumped = rate.copy()
    bumped[400:] = 0.01                      # a wild future, same past
    b_entry, b_exit = carry_funding(bumped, lookback_bars=80, enter_rate=0.00015,
                                    exit_rate=0.00005)
    assert np.array_equal(a_entry[:400], b_entry[:400])
    assert np.array_equal(a_exit[:400], b_exit[:400])


def test_a_carry_signal_stays_flat_until_its_window_is_full():
    from orc.eval.signal_rules import carry_funding

    n = 300
    rate = np.zeros(n)
    rate[::8] = 0.001                        # richly positive from bar zero
    entry, _ = carry_funding(rate, lookback_bars=100, enter_rate=0.00015,
                             exit_rate=0.00005)
    assert not entry[:99].any(), "a partial window is not evidence"
    assert entry[99:].any()


def test_carry_thresholds_that_would_flip_every_bar_are_refused():
    from orc.eval.signal_rules import carry_funding

    with pytest.raises(ValueError, match="enter_rate"):
        carry_funding(np.zeros(100), lookback_bars=10, enter_rate=0.0,
                      exit_rate=0.001)


def test_carry_reads_the_rate_per_settlement_not_per_bar():
    """funding_rate is zero except on settlement bars; the mean must ignore those."""
    from orc.eval.signal_rules import _trailing_settlement_mean

    n = 200
    rate = np.zeros(n)
    rate[::8] = 0.0003                       # every eighth bar settles
    m = _trailing_settlement_mean(rate, window=80)
    assert m[-1] == pytest.approx(0.0003), "dividing by the window would give an eighth"


def test_the_entry_bar_cannot_close_the_trade_it_opened():
    """Found by the kernel review. The fill is close[a], so bar a's own high and
    low happened before the position existed and must not reach it. Including
    them returned a closed trade with bars_held 0 and +20% read off a spike that
    preceded the fill; the mirror fabricates losses the same way."""
    n = 40
    close = np.full(n, 100.0)
    high = close.copy()
    low = close.copy()
    high[5] = 130.0                       # inside bar 5, before its close
    e, x = _one_trade(n, SIG_LONG, 4, 35)   # fills at close[5] == 100
    spec = SignalSpec(capital=10_000.0, fee_bps=0.0, slippage_bps=0.0, take_profit=0.20)
    t = run_signals(close, high, low, e, x, spec, symbol="BTCUSDT")["trades"][0]
    assert t["bars_held"] > 0
    assert t["reason"] == "signal"
    assert t["pnl"] == pytest.approx(0.0)


def test_a_settlement_before_the_fill_is_not_collected():
    """Also from the review. Panels are labelled by open time and a settlement
    sits on the bar containing it, so bar a's settlement cleared before the fill
    at close[a]. Summing from a credited a full-notional settlement to a
    position that did not yet exist."""
    n = 60
    close = np.full(n, 100.0)
    fr = np.zeros(n)
    fr[10] = 0.01                         # one fat settlement, on the fill bar
    e, x = _one_trade(n, SIG_SHORT, 9, 40)  # fills at close[10]
    spec = SignalSpec(capital=10_000.0, fee_bps=0.0, slippage_bps=0.0)
    r = run_signals(close, close, close, e, x, spec, funding_rate=fr, symbol="BTCUSDT")
    assert r["funding_collected"] == pytest.approx(0.0)

    fr2 = np.zeros(n)
    fr2[11] = 0.01                        # the very next bar is collected
    r2 = run_signals(close, close, close, e, x, spec, funding_rate=fr2, symbol="BTCUSDT")
    assert r2["funding_collected"] > 0
