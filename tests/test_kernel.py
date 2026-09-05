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
from orc.eval.signal import SignalSpec, liquidation_level, run_signals
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
    settled = rate != 0.0
    a_entry, a_exit = carry_funding(rate, lookback_bars=80, enter_rate=0.00015,
                                    exit_rate=0.00005, settled=settled)
    bumped = rate.copy()
    bumped[400:] = 0.01                      # a wild future, same past
    b_entry, b_exit = carry_funding(bumped, lookback_bars=80, enter_rate=0.00015,
                                    exit_rate=0.00005, settled=settled)
    assert np.array_equal(a_entry[:400], b_entry[:400])
    assert np.array_equal(a_exit[:400], b_exit[:400])


def test_a_carry_signal_stays_flat_until_its_window_is_full():
    from orc.eval.signal_rules import carry_funding

    n = 300
    rate = np.zeros(n)
    rate[::8] = 0.001                        # richly positive from bar zero
    entry, _ = carry_funding(rate, lookback_bars=100, enter_rate=0.00015,
                             exit_rate=0.00005, settled=rate != 0.0)
    assert not entry[:99].any(), "a partial window is not evidence"
    assert entry[99:].any()


def test_carry_thresholds_that_would_flip_every_bar_are_refused():
    from orc.eval.signal_rules import carry_funding

    with pytest.raises(ValueError, match="enter_rate"):
        carry_funding(np.zeros(100), lookback_bars=10, enter_rate=0.0,
                      exit_rate=0.001, settled=np.zeros(100, dtype=bool))


def test_carry_reads_the_rate_per_settlement_not_per_bar():
    """funding_rate is zero except on settlement bars; the mean must ignore those."""
    from orc.eval.signal_rules import _trailing_settlement_mean

    n = 200
    rate = np.zeros(n)
    rate[::8] = 0.0003                       # every eighth bar settles
    m = _trailing_settlement_mean(rate, window=80, settled=rate != 0.0)
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


# --------------------------------------------------------------------------
# the seven the first kernel review left open
# --------------------------------------------------------------------------
def test_a_wiped_out_path_reports_a_total_drawdown():
    """The liquidation bar left `act` before the mark-to-market, so a path that
    lost everything reported the drawdown it had one bar earlier."""
    close = np.concatenate([np.full(100, 100.0), np.linspace(100.0, 1.0, 300)])
    low = close * 0.999
    spec = SimSpec(contribution=1000.0, stride_bars=10, n_contributions=5,
                   hold_bars=300, leverage=5.0, fee_bps=0.0, slippage_bps=0.0)
    out = simulate(close, low, np.array([0]), spec, table=BTC_LIKE)
    assert out["liquidated"][0]
    assert out["terminal_multiple"][0] == pytest.approx(0.0)
    assert out["max_dd_total"][0] >= 1.0, "losing everything is a full drawdown"


def test_time_in_loss_divides_by_the_life_the_path_had():
    """Dividing by the nominal horizon made the paths that died earliest -- the
    worst ones -- look the healthiest on this measure."""
    close = np.concatenate([np.full(100, 100.0), np.linspace(100.0, 1.0, 300)])
    low = close * 0.999
    spec = SimSpec(contribution=1000.0, stride_bars=10, n_contributions=5,
                   hold_bars=300, leverage=5.0, fee_bps=0.0, slippage_bps=0.0)
    out = simulate(close, low, np.array([0]), spec, table=BTC_LIKE)
    lived = out["bars_lived"][0]
    assert lived < spec.horizon_bars + 1, "this path died before the horizon"
    assert out["frac_time_in_loss"][0] <= 1.0
    assert out["frac_time_in_loss"][0] > 0


def test_the_panel_identity_includes_the_wick():
    """high and low decide every exit, so a panel differing only in a wick is
    different data and must not dedupe against the old one."""
    from orc.facts.panel import _hash_arrays

    close = np.array([100.0, 101.0, 102.0])
    fr = np.zeros(3)
    high = np.array([101.0, 102.0, 103.0])
    low_a = np.array([99.0, 100.0, 101.0])
    low_b = low_a.copy()
    low_b[1] = 50.0                        # a spurious wick, corrected
    assert _hash_arrays(close, fr, high, low_a) != _hash_arrays(close, fr, high, low_b)


def test_leverage_is_checked_against_the_bracket_the_size_lands_in():
    """max_leverage is tier 0's and applies only to the smallest notionals."""
    assert LONG_TAIL.leverage_at(1_000.0) == LONG_TAIL.max_leverage
    assert LONG_TAIL.leverage_at(250_000.0) < LONG_TAIL.max_leverage

    n = 40
    close = np.full(n, 100.0)
    e, x = _one_trade(n, SIG_LONG, 1, 30)
    spec = SignalSpec(capital=10_000.0, leverage=LONG_TAIL.max_leverage)
    with pytest.raises(ValueError, match="exceeds"):
        run_signals(close, close, close, e, x, spec, symbol="SOMEALTUSDT",
                    table=LONG_TAIL)


def test_sharpe_refuses_a_destroyed_curve():
    """Every wipeout came out at the same number regardless of size or timing."""
    from orc.kernel.metrics_fc import sharpe

    eq = np.concatenate([np.full(1000, 10_000.0), np.zeros(2000)])
    assert np.isnan(sharpe(eq, 8760))
    big = np.concatenate([np.full(1000, 10_000_000.0), np.zeros(2000)])
    assert np.isnan(sharpe(big, 8760))


# --------------------------------------------------------------------------
# the funding leg and the wallet are the same money
#
# Three findings from the kernel review, deferred as one rewrite because they
# are one defect seen from three sides: Track B booked a funding-driven wipeout
# as an ordinary signal exit.  The liquidation level was frozen at the fill, the
# clamp absorbed a loss larger than the wallet into a zero, and the funding
# income of a liquidated trade was reported as collected beside a wallet of
# nothing.  Each of these fails on the commit before the rewrite.
# --------------------------------------------------------------------------
def _flat(n, price=100.0):
    c = np.full(n, price)
    return c, c.copy(), c.copy()


def test_funding_paid_during_a_trade_moves_the_liquidation_level():
    """A 10x short that has paid 3,600 of funding has a 6,400 wallet, and the
    exchange liquidates it 3.6 dollars earlier than it would have at the fill.
    The level used to be computed once from the entry wallet, so the bar that
    breached it was not liquidated here and the run carried on."""
    n = 300
    close, high, low = _flat(n)
    fr = np.zeros(n)
    fr[8:290:8] = -0.0010                 # a short pays a negative rate
    e, x = _one_trade(n, SIG_SHORT, 0, n - 1)
    spec = SignalSpec(capital=10_000.0, leverage=10.0, fee_bps=0.0, slippage_bps=0.0)

    high[290] = 107.0                     # inside 109.50, outside 105.9
    frozen = liquidation_level(SIG_SHORT, 10_000.0, 10_000.0 * 10.0 / 100.0,
                               100.0, BTC_LIKE)
    assert frozen > 107.0 > 105.0         # the trigger only bites in between

    r = run_signals(close, high, low, e, x, spec, funding_rate=fr, symbol="BTCUSDT")
    t = r["trades"][0]
    assert t["reason"] == "liquidation"
    assert t["exit_bar"] == 290
    assert r["final_equity"] == pytest.approx(0.0)
    # The wallet was down to about 6,400 of funding-eaten margin, so the level
    # had walked in from 109.5 to under 107.
    assert t["funding"] < -3_000.0


def test_funding_alone_can_wipe_a_position_out():
    """Flat price, 0.6 % against the position every eight hours.  Nothing can
    trigger on price, so this is the pure case: the wallet is consumed by the
    coupon and the exchange takes the position.  It used to close on its
    ordinary signal exit having booked -22,200 against a 10,000 wallet."""
    n = 300
    close, high, low = _flat(n)
    fr = np.zeros(n)
    fr[8::8] = -0.0060
    e, x = _one_trade(n, SIG_SHORT, 0, n - 1)
    spec = SignalSpec(capital=10_000.0, leverage=10.0, fee_bps=0.0, slippage_bps=0.0)

    r = run_signals(close, high, low, e, x, spec, funding_rate=fr, symbol="BTCUSDT")
    t = r["trades"][0]
    assert t["reason"] == "liquidation"
    assert r["n_liquidations"] == 1
    assert t["pnl"] == pytest.approx(-10_000.0)      # exactly the wallet, not twice it
    assert t["exit_bar"] < 200                       # taken when the margin ran out
    assert r["final_equity"] == pytest.approx(0.0)
    assert r["equity"].min() >= 0.0                  # no negative equity anywhere


def test_a_wiped_out_position_does_not_recover_when_the_rate_flips():
    """The same trade, with funding turning favourable after bar 200.  The
    position is long gone by then.  It used to carry negative mark equity for
    104 bars, be scored a win, and finish at +56 %."""
    n = 300
    close, high, low = _flat(n)
    fr = np.zeros(n)
    fr[8:200:8] = -0.0060
    fr[200::8] = +0.0080
    e, x = _one_trade(n, SIG_SHORT, 0, n - 1)
    spec = SignalSpec(capital=10_000.0, leverage=10.0, fee_bps=0.0, slippage_bps=0.0)

    r = run_signals(close, high, low, e, x, spec, funding_rate=fr, symbol="BTCUSDT")
    assert r["n_liquidations"] == 1
    assert r["final_equity"] == pytest.approx(0.0)
    assert r["win_rate"] == pytest.approx(0.0)
    assert r["equity"].min() >= 0.0


def test_the_funding_of_a_liquidated_trade_is_reported_against_its_price_leg():
    """A short that collected 3,600 and was then squeezed out reported
    'funding_collected 3,600' beside a final equity of zero -- the mirror image
    of KT-1's 36 % tax, and the exact number this family exists to find.  The
    coupon was real; what was missing is the price leg that took it away."""
    n = 200
    close, high, low = _flat(n)
    fr = np.zeros(n)
    fr[8:150:8] = +0.0020                 # a short collects a positive rate
    close[150:] = 125.0
    high[150:] = 125.0
    low[150:] = 125.0
    e, x = _one_trade(n, SIG_SHORT, 0, n - 1)
    spec = SignalSpec(capital=10_000.0, leverage=10.0, fee_bps=0.0, slippage_bps=0.0)

    r = run_signals(close, high, low, e, x, spec, funding_rate=fr, symbol="BTCUSDT")
    t = r["trades"][0]
    assert t["reason"] == "liquidation"
    assert r["final_equity"] == pytest.approx(0.0)
    assert t["funding"] > 3_000.0                        # collected, and true
    assert t["gross"] == pytest.approx(t["pnl"] - t["funding"])
    assert t["gross"] < -13_000.0                        # what took it away
    assert r["funding_collected"] + r["gross_collected"] == pytest.approx(
        r["pnl_total"])
    assert r["pnl_total"] == pytest.approx(r["final_equity"] - spec.capital)


def test_every_trade_reconciles_with_the_equity_curve(sig_series):
    """sum(pnl) and the curve are two accounts of one pot of money.  Nothing
    cross-footed them, so a clamped wipeout could disagree by 12,200 in
    silence."""
    close, high, low = sig_series
    fr = np.zeros(close.size)
    fr[::8] = 0.0004
    e = np.zeros(close.size, dtype=np.int8)
    e[10::200] = SIG_SHORT
    e[110::200] = SIG_LONG
    x = np.zeros(close.size, dtype=bool)
    x[100::200] = True
    spec = SignalSpec(capital=10_000.0, leverage=3.0, stop_loss=0.3)
    r = run_signals(close, high, low, e, x, spec, funding_rate=fr, symbol="BTCUSDT")
    assert r["n_trades"] > 3
    assert r["pnl_total"] == pytest.approx(r["final_equity"] - spec.capital)
    for t in r["trades"]:
        assert t["gross"] + t["funding"] == pytest.approx(t["pnl"], abs=1e-7)


def test_an_early_exit_is_not_charged_for_deposits_it_never_made():
    """The adversary killed H0008 on this: the path-dependent branch priced
    every path with the REGISTERED n_contributions and the NOMINAL horizon, so
    a programme that take-profits in week 5 was charged for the 151 deposits it
    never made. Measured on the real panel, an ensemble whose true annualised
    IRR is +415 % came out at the bracket floor, -0.9999."""
    # five weekly deposits of 100, worth 700 five weeks in: a real +415 %/yr.
    h = 7.0 / 365.0
    realised = mwrr_equal_interval(100.0, np.array([5.0]), h,
                                   np.array([700.0]),
                                   horizon_years=np.array([5 * h]))
    assert realised[0] > 3.0

    # priced as the registered programme -- 156 deposits over three years --
    # the same 700 dollars is a near-total loss, and lands on the floor.
    as_registered = mwrr_equal_interval(100.0, 156, h, np.array([700.0]),
                                        horizon_years=156 * h)
    assert as_registered[0] < -0.99
    assert realised[0] > as_registered[0] + 4.0


def test_per_path_deposit_counts_agree_with_the_scalar_case():
    """n and T became arrays. A full programme must price exactly as before, or
    every Track A number in the ledger has silently moved."""
    h, V = 7.0 / 365.0, np.array([5_000.0, 15_600.0, 40_000.0])
    scalar = mwrr_equal_interval(100.0, 156, h, V, horizon_years=156 * h)
    arrayed = mwrr_equal_interval(100.0, np.full(3, 156.0), h, V,
                                  horizon_years=np.full(3, 156 * h))
    assert np.allclose(scalar, arrayed, rtol=0, atol=1e-12)


def test_a_wipeout_reports_minus_one_however_few_deposits_landed():
    """Liquidation is the other early exit and it is why the ledger is clean:
    it ends at terminal equity zero, where the IRR is -100 % whether five
    deposits landed or a hundred and fifty-six."""
    h = 7.0 / 365.0
    for n, T in ((5.0, 5 * h), (156.0, 156 * h)):
        r = mwrr_equal_interval(100.0, np.array([n]), h, np.array([0.0]),
                                horizon_years=np.array([T]))
        assert r[0] == pytest.approx(-1.0)


def test_an_unscorable_cell_cannot_survive_the_search_test():
    """The null is filtered for finiteness and observed_best was not, so a NaN
    observed value made every `nb >= observed_best` False and produced the
    SMALLEST p-value the test can emit -- verdict SURVIVES_SEARCH -- for a cell
    that could not be scored at all."""
    from orc.kernel.inference import best_of_g_pvalue

    nulls = np.linspace(0.0, 1.0, 200)
    ok = best_of_g_pvalue(0.5, nulls, 18)
    assert 0.0 < ok.p_value < 1.0
    for bad in (float("nan"), float("inf")):
        with pytest.raises(ValueError, match="could not be scored"):
            best_of_g_pvalue(bad, nulls, 18)


def test_a_left_tail_metric_says_how_many_paths_it_could_not_score():
    """Non-finite paths were dropped and the reduced survivor count reported as
    `n`, so tm_q05 described only the paths that could be scored while reading
    as though it described the ensemble. A left-tail metric computed after
    deleting outcomes is the one error this project cannot afford."""
    from orc.kernel.metrics_cf import start_date_profile

    v = np.array([0.5, 1.0, 1.5, 2.0, np.nan, np.inf])
    prof = start_date_profile(v)
    assert prof["n"] == 4
    assert prof["n_non_finite"] == 2
    assert prof["frac_non_finite"] == pytest.approx(2 / 6)

    clean = start_date_profile(np.array([0.5, 1.0, 1.5, 2.0]))
    assert clean["n_non_finite"] == 0
    assert "frac_non_finite" not in clean
    assert start_date_profile(np.array([np.nan, np.nan])) == {"n": 0, "n_non_finite": 2}


# ---------------------------------------------------------------------------
# The nine high findings that stopped the loop on 2026-09-04.
#
# kernel_review found them, next_action() refused every research action while
# they were open, and the supervisor sat at "blocked" doing nothing for a whole
# day.  Each test below fails if its fix is reverted, because the finding is
# only closed while something would notice it reopening.
# ---------------------------------------------------------------------------
def test_a_nan_equity_curve_is_not_scored_as_a_strategy():
    """c8250bb33b10.  `np.any(equity <= 0.0)` is blind to NaN -- `nan <= 0` is
    False -- so a curve with holes passed the bankruptcy guard, np.log/np.diff
    turned the holes into NaN returns, and `r = r[np.isfinite(r)]` DELETED them
    and treated the survivors as consecutive bars.  The account whose equity was
    not a number came back with a finite, plausible, entirely fictional Sharpe.
    """
    from orc.kernel import metrics_fc

    bpy = metrics_fc.BARS_PER_YEAR["1h"]
    holed = np.array([100.0, 101.0, np.nan, 103.0, 104.0, 105.0])
    assert not metrics_fc.is_measurable(holed)
    for name in ("sharpe", "cagr"):
        v = getattr(metrics_fc, name)(holed, bpy)
        assert not np.isfinite(v), f"{name} scored a curve that is not a number"
    assert not np.isfinite(metrics_fc.max_drawdown(holed))
    assert not np.isfinite(metrics_fc.calmar(holed, bpy))

    # The same curve without the hole is scored normally, so the guard is not
    # simply refusing everything.
    clean = np.array([100.0, 101.0, 102.0, 103.0, 104.0, 105.0])
    assert metrics_fc.is_measurable(clean)
    assert np.isfinite(metrics_fc.sharpe(clean, bpy))


def test_a_non_finite_funding_rate_is_refused_by_the_signal_evaluator():
    """309614dd45f2.  simulate.py has refused this since its own review; signal.py
    did not.  A NaN wallet makes `adverse <= liq` False forever, so liquidation is
    never detected again -- and both RuntimeError invariants meant to catch that
    also compare against NaN and are silently False."""
    n = 64
    close = np.full(n, 100.0)
    entry = np.zeros(n, dtype=np.int8)
    entry[2] = SIG_LONG
    exit_ = np.zeros(n, dtype=bool)
    exit_[40] = True
    spec = SignalSpec(capital=1_000.0, leverage=1.0)

    fr = np.zeros(n)
    fr[10] = np.nan
    with pytest.raises(ValueError, match="non-finite"):
        run_signals(close, close, close, entry, exit_, spec,
                    funding_rate=fr, symbol="BTCUSDT")

    # And the finite case still runs, so this is a guard rather than a wall.
    ok = run_signals(close, close, close, entry, exit_, spec,
                     funding_rate=np.zeros(n), symbol="BTCUSDT")
    assert ok["n_trades"] == 1


def test_a_duplicated_or_unordered_bar_is_refused_as_a_clock():
    """e19968047193.  `missing = 1 - height/expected` only goes positive when
    bars are SHORT, so a duplicated bar or a non-monotonic timestamp pushed
    height to or past expected, drove missing negative, and sailed through the
    one check standing between a broken file and 'bar index is a clock'.  A
    duplicate shifts every later index by one: a 168-bar stride stops being a
    week from that point on."""
    import polars as pl
    from datetime import datetime as _dt

    from orc.facts import panel as panel_mod

    def _frame(hours):
        n = len(hours)
        return pl.DataFrame({
            "ts": hours,
            "open": np.full(n, 100.0), "high": np.full(n, 101.0),
            "low": np.full(n, 99.0), "close": np.full(n, 100.0),
            "volume": np.full(n, 1.0),
        })

    hours = [_dt(2023, 1, 1, h) for h in range(24)]

    # A clean grid is accepted.
    panel_mod._assert_bar_index_is_a_clock(_frame(hours), "TESTUSDT", "1h")

    dup = hours[:12] + [hours[11]] + hours[12:]
    with pytest.raises(ValueError, match="duplicated or out of order"):
        panel_mod._assert_bar_index_is_a_clock(_frame(dup), "TESTUSDT", "1h")

    swapped = hours[:5] + [hours[6], hours[5]] + hours[7:]
    with pytest.raises(ValueError, match="duplicated or out of order"):
        panel_mod._assert_bar_index_is_a_clock(_frame(swapped), "TESTUSDT", "1h")

    off = hours[:8] + [hours[8].replace(minute=30)] + hours[9:]
    with pytest.raises(ValueError, match="whole multiple"):
        panel_mod._assert_bar_index_is_a_clock(_frame(off), "TESTUSDT", "1h")


# --------------------------------------------------------------------------
# CCI and the timeframe it is read on
#
# Track B's first families read the funding series, which is published on its
# own schedule and cannot be read early by accident.  A price indicator can:
# every one of these tests exists because a higher-timeframe reading is exactly
# the kind of thing that is trivially computed one candle too soon, and a
# 4-hour candle read at 01:00 is a backtest that knows how its own hour ends.
# --------------------------------------------------------------------------
def _cci_panel(close, high=None, low=None, rate=None, clock="1h"):
    """A minimal Panel over a given path, on a clean hourly grid from midnight."""
    from orc.facts.panel import Panel

    close = np.asarray(close, dtype=np.float64)
    n = close.size
    fr = np.zeros(n) if rate is None else np.asarray(rate, dtype=np.float64)
    step = np.timedelta64(1, "m" if clock == "1m" else "h")
    return Panel(symbol="BTCUSDT", clock=clock,
                 ts=np.datetime64("2021-01-01T00:00") + np.arange(n) * step,
                 open=close,
                 high=close if high is None else np.asarray(high, dtype=np.float64),
                 low=close if low is None else np.asarray(low, dtype=np.float64),
                 close=close, volume=np.ones(n), funding_rate=fr,
                 funding_settled=np.zeros(n, dtype=bool) if rate is None else fr != 0.0,
                 holdout_state="development", panel_hash="ph")


def _cci_walk(n, seed=11):
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.004, n)))
    return close, close * 1.003, close * 0.997


def test_cci_is_the_textbook_definition():
    """(TP - SMA(TP)) / (0.015 * mean absolute deviation), and nothing else.

    Pinned against a window computed by hand because the two easy substitutions
    -- a standard deviation for the mean absolute deviation, or a deviation
    about the series mean rather than the window's -- both produce a plausible
    oscillator with the same shape and a different scale, and every level a
    hypothesis pre-registers is in the units this constant sets.
    """
    from orc.eval.signal_rules import _CCI_K, cci

    n, period = 60, 20
    close, high, low = _cci_walk(n)
    ts = np.datetime64("2021-01-01") + np.arange(n) * np.timedelta64(1, "h")
    v = cci(ts, high, low, close, period, timeframe_hours=1.0, clock="1h")

    tp = (high + low + close) / 3.0
    i = 45
    w = tp[i - period + 1:i + 1]
    ref = (tp[i] - w.mean()) / (_CCI_K * np.abs(w - w.mean()).mean())
    assert v[i] == pytest.approx(ref)
    assert np.isnan(v[:period - 1]).all(), "a partial window is not a reading"
    assert np.isfinite(v[period - 1:]).all()


def test_a_four_hour_reading_is_not_available_until_its_candle_closes():
    """The whole no-lookahead argument for a higher timeframe.

    The 00:00-04:00 candle is knowable at the close of the 03:00 bar and not
    one bar earlier.  If the reading moved at 01:00 it would be carrying the
    high, low and close of an hour that had not happened yet -- and it would
    look like a working strategy, because it is one, for someone who can see
    three hours ahead.
    """
    from orc.eval.signal_rules import cci

    n = 400
    close, high, low = _cci_walk(n, seed=3)
    ts = np.datetime64("2021-01-01T00:00") + np.arange(n) * np.timedelta64(1, "h")
    v = cci(ts, high, low, close, period_bars=5, timeframe_hours=4.0, clock="1h")

    hour = (np.arange(n) % 4)
    moved = np.flatnonzero(np.diff(np.nan_to_num(v, nan=-1e18)) != 0.0) + 1
    assert moved.size > 10, "a constant reading would pass this test vacuously"
    assert set(hour[moved]) == {3}, (
        "the reading may only change on the bar that CLOSES a 4h candle")


def test_a_cci_signal_cannot_see_past_its_own_bar():
    """Two histories, identical up to bar k and wild after it, same signals up to k."""
    from orc.eval.signal_rules import build_signals
    from orc.orchestrator.spec import SignalTrialConfig

    n, k = 800, 500
    close, high, low = _cci_walk(n, seed=5)
    other = close.copy()
    other[k:] *= np.exp(np.cumsum(np.full(n - k, 0.05)))     # a different future
    cfg = SignalTrialConfig(symbol="BTCUSDT", rule="cci_reversion",
                            lookback_days=1.0, timeframe_hours=4.0,
                            enter_level=100.0, exit_level=20.0)

    a = build_signals(cfg, _cci_panel(close, high, low))
    b = build_signals(cfg, _cci_panel(other, high, low))
    assert np.array_equal(a[0][:k], b[0][:k])
    assert np.array_equal(a[1][:k], b[1][:k])
    assert not np.array_equal(a[0][k:], b[0][k:]), "the futures must actually differ"


def test_a_flat_window_reads_as_nothing_rather_than_as_the_largest_extreme():
    """Mean absolute deviation of zero is a division by zero, not an extreme.

    A dead altcoin printing the same price for a day is the case: the numerator
    is zero too, so the honest answer is that there is no reading.  Returning
    +-inf would put the rule at maximum conviction on a series that did not
    move, and returning 0.0 would report a perfectly neutral market, which is a
    decision rather than the absence of one.
    """
    from orc.eval.signal_rules import cci, cci_reversion

    n = 200
    close = np.full(n, 100.0)
    ts = np.datetime64("2021-01-01") + np.arange(n) * np.timedelta64(1, "h")
    v = cci(ts, close, close, close, period_bars=10, timeframe_hours=1.0, clock="1h")
    assert np.isnan(v).all()

    entry, exit_ = cci_reversion(v, enter_level=100.0, exit_level=20.0)
    assert not entry.any(), "no reading is not a reason to hold a position"
    assert exit_.all(), "an unreadable indicator must not keep one open either"


def test_reversion_and_breakout_take_opposite_sides_of_one_reading():
    """The pair is the test.  Nothing but the side may differ between them."""
    from orc.eval.signal_rules import cci_breakout, cci_reversion

    rng = np.random.default_rng(19)
    v = rng.normal(0.0, 120.0, 5_000)
    fade, ride = (cci_reversion(v, 100.0, 20.0), cci_breakout(v, 100.0, 20.0))
    assert np.array_equal(fade[0], -ride[0])
    assert np.array_equal(fade[1], ride[1])
    assert (fade[0] != 0).any() and (fade[0] == 0).any()


def test_cci_levels_that_would_flip_every_bar_are_refused():
    from orc.eval.signal_rules import cci_breakout, cci_reversion

    v = np.zeros(50)
    for fn in (cci_reversion, cci_breakout):
        with pytest.raises(ValueError, match="enter_level"):
            fn(v, enter_level=50.0, exit_level=80.0)


def test_the_multi_timeframe_filter_must_be_the_slower_of_the_two():
    """Reversed, it is a different rule wearing this one's pre-registration."""
    from orc.eval.signal_rules import build_signals, cci_mtf
    from orc.orchestrator.spec import SignalTrialConfig

    close, high, low = _cci_walk(600, seed=8)
    p = _cci_panel(close, high, low)
    base = dict(symbol="BTCUSDT", rule="cci_mtf", lookback_days=1.0,
                enter_level=100.0, exit_level=0.0, filter_level=100.0)

    with pytest.raises(ValueError, match="filter_timeframe_hours"):
        build_signals(SignalTrialConfig(timeframe_hours=4.0, **base), p)
    with pytest.raises(ValueError, match="must be above"):
        build_signals(SignalTrialConfig(timeframe_hours=4.0,
                                        filter_timeframe_hours=1.0, **base), p)
    with pytest.raises(ValueError, match="filter_level"):
        cci_mtf(np.zeros(10), np.zeros(10), enter_level=100.0, exit_level=0.0,
                filter_level=0.0)


def test_the_multi_timeframe_rule_only_takes_the_side_its_filter_permits():
    from orc.eval.signal_rules import cci_mtf
    from orc.eval.signal import FLAT, LONG, SHORT

    base = np.array([-200.0, -200.0, 200.0, 200.0, -200.0])
    filt = np.array([+150.0, -150.0, +150.0, -150.0, 0.0])
    entry, _ = cci_mtf(base, filt, enter_level=100.0, exit_level=0.0,
                       filter_level=100.0)
    # oversold inside an uptrend is the only long; overbought inside a
    # downtrend the only short; no trend permits nothing at all.
    assert list(entry) == [LONG, FLAT, FLAT, SHORT, FLAT]


def test_build_signals_reads_the_configuration_rather_than_its_defaults():
    """The guard on the defect the dispatch refactor was for.

    `build_signals` used to take (rule, panel, lookback, enter_rate, exit_rate)
    and had five call sites, each unpacking those five by hand.  A rule reading
    a NEW field would have been handed the dataclass default by four of them
    while the fifth honoured the grid, and the visible result is a robustness
    check or an execution-realism run reporting a number for a configuration it
    never evaluated.  So the config goes in whole, and this test fails if any
    field it carries stops reaching the rule.
    """
    from orc.eval.signal_rules import build_signals
    from orc.orchestrator.spec import SignalTrialConfig

    close, high, low = _cci_walk(1_200, seed=13)
    p = _cci_panel(close, high, low)
    base = dict(symbol="BTCUSDT", rule="cci_reversion", lookback_days=1.0,
                timeframe_hours=1.0, enter_level=100.0, exit_level=20.0)

    ref = build_signals(SignalTrialConfig(**base), p)
    for field, value in (("timeframe_hours", 4.0), ("enter_level", 250.0),
                         ("exit_level", 80.0), ("lookback_days", 5.0)):
        other = build_signals(SignalTrialConfig(**{**base, field: value}), p)
        assert not (np.array_equal(ref[0], other[0])
                    and np.array_equal(ref[1], other[1])), (
            f"{field} changed and the signals did not; the rule is not reading it")


def test_the_null_scores_a_price_rule_on_the_synthetic_path():
    """A price rule handed the real panel is a null for a strategy nobody ran.

    The search test bootstraps a history and re-runs the whole grid on it.  For
    a carry rule the panel's funding series is the input and the bootstrap does
    not touch it, so the signals are identical by design; for a CCI rule the
    input IS the bootstrapped path, and reading the panel's own close instead
    would compare the observed best against a null that had seen the real
    prices all along.  Track A carries the same override on `build_gate` and
    the same footnote on why.
    """
    from orc.eval.signal_rules import build_signals
    from orc.orchestrator.spec import SignalTrialConfig

    close, high, low = _cci_walk(1_200, seed=17)
    other, _, _ = _cci_walk(1_200, seed=23)
    p = _cci_panel(close, high, low)
    cfg = SignalTrialConfig(symbol="BTCUSDT", rule="cci_reversion",
                            lookback_days=1.0, timeframe_hours=4.0,
                            enter_level=100.0, exit_level=20.0)

    real = build_signals(cfg, p)
    null = build_signals(cfg, p, close=other)
    assert not np.array_equal(real[0], null[0])
    # and the bootstrap has no wick: high and low default to the path itself
    assert np.array_equal(null[0], build_signals(cfg, p, close=other,
                                                 high=other, low=other)[0])


def test_a_higher_timeframe_reading_does_not_depend_on_the_execution_clock():
    """The same 4h candle on 1h bars and on 1m bars, to the last decimal.

    This is what makes `execution_realism` able to say anything: it re-runs one
    cell on minute bars, and if the signal itself changed with the clock, the
    drift it measures would be a mixture of two effects with no way to separate
    them.  Aggregating from the epoch rather than from the panel's first bar is
    what buys this.
    """
    from orc.eval.signal_rules import cci

    hours = 96
    rng = np.random.default_rng(29)
    minute = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.0004, hours * 60)))
    ts_m = np.datetime64("2021-01-01T00:00") + np.arange(minute.size) * np.timedelta64(1, "m")
    # the hourly panel the same minutes would build
    block = minute.reshape(hours, 60)
    ts_h = np.datetime64("2021-01-01T00:00") + np.arange(hours) * np.timedelta64(1, "h")
    hi_h, lo_h, cl_h = block.max(1), block.min(1), block[:, -1]

    on_minutes = cci(ts_m, minute, minute, minute, period_bars=6,
                     timeframe_hours=4.0, clock="1m")
    on_hours = cci(ts_h, hi_h, lo_h, cl_h, period_bars=6,
                   timeframe_hours=4.0, clock="1h")
    # compare where both exist: the hourly bar at 03:00 and the minute bar at
    # 03:59 are the same instant, and the reading must be the same number.
    last_minute_of_hour = np.arange(59, minute.size, 60)
    a, b = on_minutes[last_minute_of_hour], on_hours
    both = np.isfinite(a) & np.isfinite(b)
    assert both.sum() > 10
    np.testing.assert_allclose(a[both], b[both], rtol=1e-12, atol=1e-9)


# --------------------------------------------------------------------------
# holes the mutation harness found, 2026-09-04
#
# scripts/mutation.py breaks the kernel on purpose and asks whether anything
# fails.  Three mutations SURVIVED a green 248-test suite, which means the code
# was right and the oracle was not looking:
#
#   the_seal_is_not_applied   deleting `df = holdout.development_slice(df)`
#                             from panel.load broke NO test. The sealed holdout
#                             is section 2 of the constitution and the one
#                             guarantee the whole project rests on, and it was
#                             enforced by a line nobody was watching.
#   drawdown_upside_down      inverting max_drawdown broke no test either, and
#                             it is half of the owner's stop condition: every
#                             candidate would clear TARGET_MAX_DRAWDOWN.
#   cci_partial_window        the carry rules are tested for refusing a partial
#                             window; the CCI path was not.
#
# These three tests exist so that those three mutations die. A test written
# because a mutation survived is the only kind that is known to be load-bearing
# before it ever fails for real.
# --------------------------------------------------------------------------
def test_a_development_load_actually_truncates_at_the_seal(tmp_path, monkeypatch):
    """Not that it refuses a sealed read -- that the ordinary read is cut.

    The existing tests cover the door: `development_only=False` and
    `sealed_only=True` both raise unless a final test is open. Nothing covered
    the floor, which is that the DEFAULT path physically drops every bar at or
    after HOLDOUT_START. That is the line research calls thousands of times a
    day and the only thing standing between it and the sealed period.
    """
    import polars as pl

    from orc import config
    from orc.facts import panel as panel_mod

    monkeypatch.setattr(config, "FACTS", tmp_path)
    d = tmp_path / "panel_1h"
    d.mkdir()

    # 40 days of clean hourly bars straddling the seal.
    start = np.datetime64(str(config.HOLDOUT_START), "h") - np.timedelta64(20 * 24, "h")
    ts = start + np.arange(40 * 24) * np.timedelta64(1, "h")
    n = ts.size
    px = 100.0 + np.arange(n) * 0.01
    pl.DataFrame({"ts": ts.astype("datetime64[ms]"), "open": px, "high": px + 1.0,
                  "low": px - 1.0, "close": px, "volume": np.ones(n)}
                 ).write_parquet(d / "TESTUSDT.parquet")

    p = panel_mod.load("TESTUSDT", "1h", development_only=True, with_funding=False)
    seal = np.datetime64(str(config.HOLDOUT_START), "ms")
    assert p.holdout_state == panel_mod.DEVELOPMENT
    assert len(p) == 20 * 24, "half the file is on the sealed side of the seal"
    assert p.ts.astype("datetime64[ms]").max() < seal, (
        "a development load handed research a bar at or past the seal")


def test_a_missing_code_hash_root_refuses_instead_of_hashing_nothing():
    """kernel_review c6fe59d949ee, 2026-09-05, and worse than it was reported.

    A missing root contributed nothing and raised nothing: is_file() is False
    for a path that is not there, and rglob over a missing directory yields an
    empty iterator. So a renamed root silently left the hash -- and with EVERY
    root gone the function returned e3b0c44298fc..., the SHA-256 of nothing,
    a perfectly well-formed digest computed over no code at all.

    That is precisely the failure code_hash exists to prevent, made permanent:
    a corrected evaluator would key on a constant, match its own old rows and
    be discarded by INSERT OR IGNORE while printing "new 0". Three evaluator
    corrections were landed on 2026-09-05 trusting this hash to move.
    """
    import hashlib

    from orc import config
    from orc.ledger import trials

    kernel = config.ORC_ROOT / "orc" / "kernel"
    assert trials.code_hash([kernel]), "the ordinary case must still work"

    with pytest.raises(FileNotFoundError):
        trials.code_hash([kernel, config.ORC_ROOT / "orc" / "NO_SUCH_DIR"])
    with pytest.raises(FileNotFoundError):
        trials.code_hash([config.ORC_ROOT / "orc" / "kernel" / "nope.py"])

    # The specific value that used to come back when nothing was read.
    assert hashlib.sha256().hexdigest().startswith("e3b0c44298fc")
    with pytest.raises(FileNotFoundError):
        trials.code_hash([config.ORC_ROOT / "orc" / "NO_SUCH_DIR"])


def test_a_panel_starts_where_its_funding_record_starts(tmp_path, monkeypatch):
    """kernel_review 9a9abb9c8d10, 2026-09-05, and LIVE.

    Bars before the funding record began were filled with funding_rate 0.0 and
    handed to research, while has_funding() answered True on the strength of
    settlements later in the same panel. So "funding was zero here" and "there
    is no funding record here" were the same panel -- and funding is the
    dominant term for Track A, measured by KT-1 at 36% of contributed capital.

    Measured over the nine researched symbols: BTCUSDT 2,739 such bars, 6.98%
    of its development window, and ETHUSDT 832, 2.23%. Those bars were charged
    nothing at all.

    funding_settled cannot fix this downstream: funding settles every eight
    hours, so False is the ordinary state of a bar and says nothing about
    whether a record exists.
    """
    import polars as pl

    from orc import config
    from orc.facts import panel as panel_mod

    monkeypatch.setattr(config, "FACTS", tmp_path)
    (tmp_path / "panel_1h").mkdir()
    (tmp_path / "funding").mkdir()

    start = np.datetime64(str(config.HOLDOUT_START), "h") - np.timedelta64(400, "h")
    ts = start + np.arange(200) * np.timedelta64(1, "h")
    px = np.full(200, 100.0)
    pl.DataFrame({"ts": ts.astype("datetime64[ms]"), "open": px, "high": px,
                  "low": px, "close": px, "volume": np.ones(200)}
                 ).write_parquet(tmp_path / "panel_1h" / "TESTUSDT.parquet")

    # Funding begins 100 bars in, and every settlement is a real cost.
    fts = ts[100::8]
    pl.DataFrame({"ts": fts.astype("datetime64[ms]"),
                  "funding_rate": np.full(fts.size, 0.0001)}
                 ).write_parquet(tmp_path / "funding" / "TESTUSDT.parquet")

    with_f = panel_mod.load("TESTUSDT", "1h", development_only=True,
                            with_funding=True)
    assert len(with_f) == 100, \
        "the 100 bars with no funding record were still handed to research"
    assert with_f.ts.astype("datetime64[ms]").min() == ts[100].astype("datetime64[ms]")
    assert with_f.has_funding()

    # Asking for no funding is untouched: the whole span is still there.
    without = panel_mod.load("TESTUSDT", "1h", development_only=True,
                             with_funding=False)
    assert len(without) == 200


def test_a_wick_that_did_not_liquidate_still_counts_as_drawdown():
    """kernel_review b29a2f5e1a0d, 2026-09-05, and the one finding of the seven
    that was LIVE rather than latent.

    Step 1 read `low` for the liquidation check and step 5 marked to market on
    `close` alone, so any intrabar fall that stopped short of the liquidation
    level left no trace in the drawdown at all. runner.py records dd_q50 and
    dd_q95 on every Track A simulate row from this number and surface.py ranks
    on its median, and section 4 names drawdown on invested capital as Track
    A's definition -- so this was understating the recorded metric, not a
    display detail.
    """
    from orc.eval import simulate as sim

    spec = sim.SimSpec(contribution=100.0, stride_bars=1, n_contributions=1,
                       hold_bars=3, leverage=1.0, fee_bps=0.0,
                       slippage_bps=0.0, exit_fee_bps=0.0)
    starts = np.array([0])

    flat_close = np.array([100.0, 100.0, 100.0, 100.0])
    wick_low = np.array([100.0, 60.0, 100.0, 100.0])
    wick = sim.simulate(flat_close, wick_low, starts, spec)

    # The identical -40%, printed as a close instead of a wick.
    on_close = np.array([100.0, 60.0, 100.0, 100.0])
    closed = sim.simulate(on_close, on_close, starts, spec)

    assert closed["max_dd_total"][0] == pytest.approx(0.40, abs=1e-9)
    assert wick["max_dd_total"][0] == pytest.approx(0.40, abs=1e-9), \
        "a -40% wick that did not liquidate vanished from the drawdown"

    # Both recover to 100, so neither lost anything by the end. The drawdown is
    # the whole difference between them, which is the point.
    assert wick["terminal_multiple"][0] == pytest.approx(1.0, abs=1e-9)
    assert closed["terminal_multiple"][0] == pytest.approx(1.0, abs=1e-9)

    # A bar whose low equals its close adds nothing: the fix must not invent
    # drawdown where there was none.
    calm = np.array([100.0, 101.0, 102.0, 103.0])
    assert sim.simulate(calm, calm, starts, spec)["max_dd_total"][0] == \
        pytest.approx(0.0, abs=1e-9)


def test_the_closed_form_says_ruined_rather_than_a_multiple(monkeypatch):
    """kernel_review 04dbaaf9817f, 2026-09-05.

    `evaluate()` subtracts the funding bill from a position a real account
    would have been liquidated out of and returns a finite terminal value, and
    the only thing excluding that state from results was `uses_analytic` in
    another module -- which scripts/robustness.py reached past, calling this
    directly for the regime gate on any cell with include_funding set.

    The closed form cannot see a path that went through zero and recovered, so
    the routing is still what makes the ledger correct. What it CAN see is a
    terminal at or below zero, and that must not come back as a multiple.
    """
    from orc.eval.analytic import AnalyticSpec, evaluate

    n = 400
    close = np.full(n, 100.0)
    spec = AnalyticSpec(contribution=100.0, stride_bars=1, n_contributions=4,
                        hold_bars=10, fee_bps=0.0, slippage_bps=0.0,
                        exit_fee_bps=0.0)

    ok = evaluate(close, spec)
    assert ok["n_ruined"] == 0
    assert np.all(np.isfinite(ok["terminal_multiple"]))

    # A funding bill far larger than the position is worth.
    ruinous = evaluate(close, spec, funding_flow=close * 0.5)
    assert ruinous["n_ruined"] > 0, "a wiped-out account still reported a value"
    assert np.all(np.isnan(ruinous["terminal_multiple"][ruinous["ruined"]])), \
        "a negative terminal came back as an ordinary bad multiple"


def test_an_unreadable_opening_counter_is_not_zero_openings(tmp_path, monkeypatch):
    """kernel_review 9b4c4e0f67d5, 2026-09-05.

    `_state_count()` swallowed OSError/ValueError/KeyError/TypeError and
    returned 0, so a state file that EXISTS but cannot be parsed -- a truncated
    write, a bad merge, a hand edit -- read as "never opened". With the log
    also gone, openings_used() went back to zero and the project would hand out
    three fresh looks at the sealed period.

    The existing counter test covers a MISSING log against a valid state file.
    Nothing covered a state file that is there and is garbage, which is the
    more likely accident of the two.
    """
    from orc import holdout

    log = tmp_path / "log.jsonl"
    monkeypatch.setattr(holdout, "LOG_FILE", log)
    state = holdout.state_file()

    # Absent is a genuine zero: a fresh project has neither file.
    assert not state.exists()
    assert holdout.openings_used() == 0

    for garbage in ("", "{", '{"openings_used": "two"}', '{"other": 1}',
                    "null"):
        state.write_text(garbage, encoding="utf-8")
        assert holdout.openings_used() == holdout.MAX_FINAL_TESTS, (
            f"an unparseable state file ({garbage!r}) read as a spent count "
            "of zero; unknown must resolve upward, never downward")

    # And a readable one is still read, so this did not simply pin the counter.
    state.write_text('{"openings_used": 1}', encoding="utf-8")
    assert holdout.openings_used() == 1


def test_a_window_too_short_to_annualise_is_not_a_cagr():
    """kernel_review a1ddba290d1d, 2026-09-05.

    `cagr()` divided by `years` with no floor, so a symbol listed three months
    ago that happened to double returned (2.0 ** 4) - 1 = 1500 % -- finite,
    plausible, and compared directly against TARGET_CAGR by orc.target. That is
    the owner's stop condition being satisfied by an extrapolation.

    Nothing on record was affected: the shortest history in the ledger on
    2026-09-05 was 30,113 bars. KT-3 had just cleared the survivorship
    objection that kept short-lived alt symbols out, which is what was about to
    make it reachable.
    """
    from orc.kernel import metrics_fc

    bpy = metrics_fc.BARS_PER_YEAR["1h"]

    # Three months, doubled. This is the number that used to come back.
    quarter = np.linspace(1.0, 2.0, int(bpy / 4))
    assert not np.isfinite(metrics_fc.cagr(quarter, bpy)), \
        "a three-month window still annualises into the stop condition"

    # Two years, doubled: 2 ** 0.5 - 1, and this must still be measured.
    two_years = np.linspace(1.0, 2.0, int(bpy * 2))
    assert metrics_fc.cagr(two_years, bpy) == pytest.approx(2 ** 0.5 - 1,
                                                            rel=1e-3)

    # The floor is a floor, not a rounding: just under is nan, just over is not.
    just_under = np.linspace(1.0, 2.0, int(bpy * 0.99))
    just_over = np.linspace(1.0, 2.0, int(bpy * 1.01))
    assert not np.isfinite(metrics_fc.cagr(just_under, bpy))
    assert np.isfinite(metrics_fc.cagr(just_over, bpy))


def test_positioning_is_sealed_by_the_same_door_the_panels_are(tmp_path, monkeypatch):
    """A new data source is a new way to breach the seal.

    orc/facts/positioning.py adds open interest and taker flow, which is the
    observable section 7b says the project lacks -- and every argument in
    section 2 applies to it unchanged. The store holds the FULL history, sealed
    days included, exactly as the panels do, so `load()` is the only thing
    standing between research and the sealed period. That is the line this
    pins, for the same reason the panel version above exists: the mutation
    harness showed on 2026-09-04 that deleting a truncation broke nothing.
    """
    import polars as pl

    from orc import config, holdout
    from orc.facts import positioning

    monkeypatch.setattr(config, "FACTS", tmp_path)

    # 40 days of five-minute rows straddling the seal, written to the store the
    # way fetch() writes them -- untruncated.
    seal = np.datetime64(str(config.HOLDOUT_START), "s")
    ts = (seal - np.timedelta64(20 * 288 * 5, "m")
          + np.arange(40 * 288) * np.timedelta64(5, "m"))
    n = ts.size
    d = positioning.store()
    d.mkdir(parents=True, exist_ok=True)
    pl.DataFrame({
        "ts": ts.astype("datetime64[us]"),
        "open_interest": np.linspace(1000.0, 2000.0, n),
        "open_interest_usd": np.linspace(1e6, 2e6, n),
        "toptrader_accounts_ls": np.ones(n),
        "toptrader_positions_ls": np.ones(n),
        "accounts_ls": np.ones(n),
        "taker_buy_sell": np.ones(n),
    }).write_parquet(positioning.path_for("TESTUSDT"))

    df = positioning.load("TESTUSDT")
    assert df.height == 20 * 288, "half the file is on the sealed side"
    assert np.datetime64(df["ts"].max(), "s") < seal, \
        "a development load handed research a row at or past the seal"

    # And the sealed side is not reachable by asking politely.
    with pytest.raises(holdout.HoldoutViolation):
        positioning.load("TESTUSDT", development_only=False)

    # A missing symbol says so rather than returning an empty frame that would
    # read downstream as "this symbol had no open interest".
    with pytest.raises(FileNotFoundError):
        positioning.load("NOSUCHUSDT")


def test_max_drawdown_is_the_fall_from_the_peak_not_the_rise_to_it():
    """Half of the stop condition, pinned to a number computed by hand.

    Inverted, this returns ~0 for every curve that ever made a new high, so
    every candidate clears TARGET_MAX_DRAWDOWN and `orc.target` declares the
    research finished on the first cell it sees.
    """
    from orc.kernel import metrics_fc

    assert metrics_fc.max_drawdown(np.array([100.0, 200.0, 100.0])) == pytest.approx(0.5)
    assert metrics_fc.max_drawdown(np.array([100.0, 90.0, 120.0, 60.0])) == pytest.approx(0.5)
    # a curve that only rises has no drawdown, and that is 0.0 rather than a
    # negative number: the metric is a magnitude of loss.
    assert metrics_fc.max_drawdown(np.array([1.0, 2.0, 3.0])) == 0.0
    assert metrics_fc.max_drawdown(np.array([100.0, 50.0])) == pytest.approx(0.5)


def test_a_window_longer_than_the_series_is_no_reading_rather_than_a_crash():
    """The CCI path's version of "a partial window is not evidence".

    `carry_funding` has this covered on the funding side. The price side did
    not, and the harness proved it: relaxing the guard to `n < 1` left the
    suite green, and every caller with a short history would then have gone on
    to `sliding_window_view` on an array too small for the window.
    """
    from orc.eval.signal_rules import _rolling_mean_and_mad

    x = np.arange(5, dtype=np.float64)
    mean, mad = _rolling_mean_and_mad(x, period=20)
    assert mean.shape == mad.shape == x.shape
    assert np.isnan(mean).all() and np.isnan(mad).all()

    # and the boundary: exactly enough bars for one window is a reading
    mean, mad = _rolling_mean_and_mad(x, period=5)
    assert np.isnan(mean[:4]).all()
    assert mean[4] == pytest.approx(2.0)
