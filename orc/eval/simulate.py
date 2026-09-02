"""ORC | Path simulator -- vectorised across start dates.

Handles everything the analytic evaluator cannot: conditional deployment,
leverage, liquidation, take-profit and stop-loss.

Shape of the computation: the outer loop runs over ELAPSED bars, not calendar
bars, so at step e every path is exactly e bars into its own life and the price
lookup is one gather, close[starts + e].  Vector width is the number of start
dates; loop length is the horizon.  No path is ever materialised.

Accounting (Binance USDs-M, one-way long, cross margin on a single position):

    wallet   = deposits - fees - funding + realised PnL
    equity   = wallet + qty * (mark - avg_entry)
    pnl      = equity - contributed

Cost convention, identical to orc.eval.analytic so the two can be cross-checked
to machine precision: buys fill at P*(1+c), sells at P*(1-c), marks at P.

Liquidation is tested against the bar LOW, i.e. the worst mark a long saw
inside the bar.  Because the hourly panel is aggregated from 1m bars, that low
is the true intrabar extreme, not an hourly close.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from orc.kernel.liquidation import TierTable, is_liquidated, tier_table_for

# exit_reason codes
EXIT_HORIZON = 0
EXIT_LIQUIDATION = 1
EXIT_TAKE_PROFIT = 2
EXIT_STOP_LOSS = 3


@dataclass(frozen=True)
class SimSpec:
    contribution: float
    stride_bars: int
    n_contributions: int
    hold_bars: int = 0
    leverage: float = 1.0
    fee_bps: float = 4.5
    slippage_bps: float = 1.0
    exit_fee_bps: float = 4.5
    take_profit: float | None = None      # exit all when pnl/contributed >= x
    stop_loss: float | None = None        # exit all when pnl/contributed <= -x
    undeployed_counts_as_margin: bool = True

    @property
    def entry_cost(self) -> float:
        return (self.fee_bps + self.slippage_bps) / 1e4

    @property
    def exit_cost(self) -> float:
        return (self.exit_fee_bps + self.slippage_bps) / 1e4

    @property
    def horizon_bars(self) -> int:
        return (self.n_contributions - 1) * self.stride_bars + self.hold_bars


def simulate(
    close: np.ndarray,
    low: np.ndarray,
    starts: np.ndarray,
    spec: SimSpec,
    funding_rate: np.ndarray | None = None,
    gate: np.ndarray | None = None,
    table: TierTable | None = None,
) -> dict:
    """Run the ensemble.  starts must satisfy starts + horizon_bars < len(close).

    gate[t] True means undeployed cash may be put to work at bar t.  None means
    unconditional deployment, which reproduces the analytic evaluator exactly.
    """
    close = np.asarray(close, dtype=np.float64)
    low = np.asarray(low, dtype=np.float64)
    starts = np.asarray(starts, dtype=np.int64)
    N = close.size
    H = spec.horizon_bars
    if starts.size and (int(starts.max()) + H >= N or int(starts.min()) < 0):
        raise ValueError("start offsets run past the end of the series")
    table = table or tier_table_for("")
    fr = np.zeros(N) if funding_rate is None else np.asarray(funding_rate, dtype=np.float64)
    # One non-finite rate turns wallet into NaN, and NaN <= maintenance_margin
    # is False, so is_liquidated answers False for that path forever after: it
    # is reported as a survivor and liquidation_rate -- the only number KT-2
    # reads -- comes back finite and understated with nothing raising anywhere.
    if not np.isfinite(fr).all():
        raise ValueError(
            f"funding_rate carries {int((~np.isfinite(fr)).sum())} non-finite "
            "value(s); a NaN here silently makes every path that touches it "
            "unliquidatable")

    M = int(starts.size)

    def z():
        return np.zeros(M, dtype=np.float64)

    wallet, qty, basis, contributed, powder = z(), z(), z(), z(), z()
    funding_paid = z()
    peak_pnl, max_dd_abs = z(), z()
    bars_in_loss = np.zeros(M, dtype=np.int64)
    bars_below_peak = np.zeros(M, dtype=np.int64)
    terminal_equity = z()
    closed = np.zeros(M, dtype=bool)
    liquidated = np.zeros(M, dtype=bool)
    exit_reason = np.zeros(M, dtype=np.int8)
    exit_bar = np.full(M, -1, dtype=np.int64)

    k, n, L = spec.stride_bars, spec.n_contributions, spec.leverage
    c_in, c_out = spec.entry_cost, spec.exit_cost
    deposits_done = 0
    no_hit = np.zeros(M, dtype=bool)

    for e in range(H + 1):
        act = ~closed
        if not act.any():
            break
        idx = starts + e
        px = close[idx]
        lo = low[idx]

        # 1. liquidation at the worst mark inside the bar, against the account
        #    as it stood ENTERING it. This used to run after the bar's deposit
        #    and its close fill, so margin that arrives later in time rescued a
        #    position from a low that had already printed, and quantity bought
        #    at the close took a loss at a low it was never exposed to. The two
        #    do not cancel: the rescue is worth `powder` and the phantom loss
        #    `powder*L*(1 - lo/px)`, so a deposit bar always errs towards
        #    survival. close=[100,55,55,55] low=[100,49,55,55] at 2x reported
        #    terminal_multiple 0.6981 and not liquidated for an account whose
        #    margin balance at that low was -2.05. liquidation_rate is the only
        #    number KT-2 reads.
        has_pos = act & (qty > 0.0)
        ep = np.where(qty > 0.0, basis / np.maximum(qty, 1e-300), 0.0)
        margin = wallet if spec.undeployed_counts_as_margin else wallet - powder
        liq_now = has_pos & is_liquidated(margin, qty, ep, lo, table)
        if liq_now.any():
            # Record the wipeout before the path leaves `act`, or the bar on
            # which everything was lost never reaches peak_pnl/max_dd_abs and a
            # total loss is reported with the drawdown it had one bar earlier:
            # 100% of contributed capital gone, max_dd_total 0.894.
            max_dd_abs = np.where(liq_now, np.maximum(max_dd_abs, peak_pnl + contributed),
                                  max_dd_abs)
            terminal_equity = np.where(liq_now, 0.0, terminal_equity)
            exit_reason = np.where(liq_now, EXIT_LIQUIDATION, exit_reason)
            exit_bar = np.where(liq_now, e, exit_bar)
            liquidated |= liq_now
            closed |= liq_now
            act = ~closed

        # 2. scheduled deposit (every path shares the elapsed schedule)
        if e % k == 0 and deposits_done < n:
            add = np.where(act, spec.contribution, 0.0)
            wallet += add
            contributed += add
            powder += add
            deposits_done += 1

        # 3. deployment, subject to the gate
        open_gate = np.ones(M, dtype=bool) if gate is None else gate[idx]
        dep = act & (powder > 0.0) & open_gate
        if dep.any():
            fill = px * (1.0 + c_in)
            notional = powder * L
            qty += np.where(dep, notional / fill, 0.0)
            basis += np.where(dep, notional, 0.0)
            powder = np.where(dep, 0.0, powder)

        # 4. funding on the mark notional (a long pays when the rate is positive)
        pay = np.where(act, qty * px * fr[idx], 0.0)
        wallet -= pay
        funding_paid += pay

        # 5. mark to market; drawdown is tracked against invested capital.
        # ep above was read before this bar's deployment, so recompute it.
        ep = np.where(qty > 0.0, basis / np.maximum(qty, 1e-300), 0.0)
        equity = wallet + qty * (px - ep)
        pnl = equity - contributed
        peak_pnl = np.where(act, np.maximum(peak_pnl, pnl), peak_pnl)
        max_dd_abs = np.where(act, np.maximum(max_dd_abs, peak_pnl - pnl), max_dd_abs)
        bars_in_loss += (act & (pnl < 0.0)).astype(np.int64)
        bars_below_peak += (act & (pnl < peak_pnl - 1e-12)).astype(np.int64)

        # 6. path-dependent exits
        if spec.take_profit is not None or spec.stop_loss is not None:
            ratio = pnl / np.maximum(contributed, 1e-12)
            hit_tp = act & (ratio >= spec.take_profit) if spec.take_profit is not None else no_hit
            hit_sl = act & (ratio <= -spec.stop_loss) if spec.stop_loss is not None else no_hit
            hit = hit_tp | hit_sl
            if hit.any():
                realised = wallet + qty * (px * (1.0 - c_out) - ep)
                terminal_equity = np.where(hit, realised, terminal_equity)
                exit_reason = np.where(hit_tp, EXIT_TAKE_PROFIT,
                                       np.where(hit_sl, EXIT_STOP_LOSS, exit_reason))
                exit_bar = np.where(hit, e, exit_bar)
                closed |= hit
                act = ~closed

    # anyone still open is closed at the horizon
    still = ~closed
    if still.any():
        idx = starts + H
        px = close[idx]
        ep = np.where(qty > 0.0, basis / np.maximum(qty, 1e-300), 0.0)
        realised = wallet + qty * (px * (1.0 - c_out) - ep)
        terminal_equity = np.where(still, realised, terminal_equity)
        exit_bar = np.where(still, H, exit_bar)

    total_invested = np.maximum(contributed, 1e-12)
    # Divided by the bars the path actually lived, not the nominal horizon.
    # A path liquidated at bar 155 of 340 that was underwater for 54 of its 156
    # living bars was reporting 15.8% rather than 34.6%, so the paths that die
    # earliest -- the worst ones -- looked the healthiest on this measure.
    lived = np.maximum(exit_bar.astype(np.float64) + 1.0, 1.0)
    return {
        "n_starts": M,
        "start_idx": starts,
        "terminal_equity": terminal_equity,
        "terminal_multiple": terminal_equity / total_invested,
        "invested": contributed,
        "nominal_invested": float(spec.contribution * n),
        "funding_paid": funding_paid,
        "liquidated": liquidated,
        "liquidation_rate": float(liquidated.mean()) if M else 0.0,
        "exit_reason": exit_reason,
        "exit_bar": exit_bar,
        "max_dd_abs": max_dd_abs,
        "max_dd_total": max_dd_abs / total_invested,
        "bars_lived": lived,
        "frac_time_in_loss": bars_in_loss / lived,
        "frac_time_below_peak": bars_below_peak / lived,
    }


# --------------------------------------------------------------------------
# Causal deployment gates
# --------------------------------------------------------------------------
def gate_always(n: int) -> np.ndarray:
    return np.ones(n, dtype=bool)


def gate_below_trailing_peak(close: np.ndarray, drop: float, lookback: int) -> np.ndarray:
    """Deploy only when price sits `drop` below its trailing high.

    The high is taken over bars strictly BEFORE the current bar, so the gate is
    causal: no bar can see its own close inside its own trigger.
    """
    from numpy.lib.stride_tricks import sliding_window_view

    close = np.asarray(close, dtype=np.float64)
    n = close.size
    prior = np.concatenate([[np.nan], close[:-1]])
    roll = np.full(n, np.nan)
    if lookback <= 0:
        roll = np.maximum.accumulate(np.nan_to_num(prior, nan=-np.inf))
    elif n > lookback:
        win = sliding_window_view(prior, lookback)
        roll[lookback - 1:] = np.nanmax(win, axis=1)
    out = np.zeros(n, dtype=bool)
    ok = np.isfinite(roll)
    out[ok] = close[ok] <= roll[ok] * (1.0 - drop)
    return out


def gate_below_sma(close: np.ndarray, window: int) -> np.ndarray:
    """Deploy only when price is under the simple average of the PRIOR window."""
    close = np.asarray(close, dtype=np.float64)
    n = close.size
    cs = np.concatenate([[0.0], np.cumsum(close)])
    sma = np.full(n, np.nan)
    if n > window:
        sma[window:] = (cs[window:-1] - cs[:-window - 1]) / float(window)
    out = np.zeros(n, dtype=bool)
    ok = np.isfinite(sma)
    out[ok] = close[ok] <= sma[ok]
    return out
