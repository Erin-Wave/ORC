"""ORC | Track B evaluator: one position at a time, entered and exited on signal.

Track A asks what happens to money that keeps arriving on a schedule.  Track B
asks what happens to one pot of money that goes long or short when a rule says
so and flattens when the rule says so.  The two share nothing but the panel, so
this is a separate evaluator rather than another mode of `simulate.py`, whose
whole shape is a schedule of contributions.

Conventions, all chosen to be pessimistic where the data cannot say:

  no lookahead     A signal read at bar i is acted on at bar i+1.  Nothing is
                   ever filled at a price that was used to decide the fill.
  adverse first    If a stop and a target fall inside the same bar, the stop is
                   taken.  Minute bars would resolve the order; hourly bars
                   cannot, and guessing in one's own favour is how a backtest
                   invents money.
  liquidation wins If the maintenance margin is breached inside the bar, the
                   position is gone regardless of where the bar closed.
  funding is real  A long pays when the rate is positive and a short is paid.
                   That asymmetry is the entire subject of Track B's first
                   family, so it is charged bar by bar, never approximated.

The scan is over trades, not bars: entries and exits are found with searchsorted
on their index arrays, so a six-year hourly panel with two hundred trades costs
two hundred iterations rather than fifty thousand.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from orc.kernel.liquidation import TierTable, tier_table_for

LONG, SHORT, FLAT = 1, -1, 0

# Fixed-point passes for the liquidation level.  The maintenance margin rate
# depends on the notional at the liquidation price, which depends on the rate.
# Three passes settle it to well under a tick on every tier table here.
_LIQ_ITERS = 3

# Tie-break when several exits fall in the same bar.  Lower goes first, and the
# order is deliberately the one that costs the most: an hourly bar cannot say
# whether the stop or the target was touched first, so it is not our choice.
_PRIORITY = {"liquidation": 0, "stop": 1, "take_profit": 2, "signal": 3}


@dataclass(frozen=True)
class SignalSpec:
    capital: float = 10_000.0
    leverage: float = 1.0
    fee_bps: float = 4.5
    slippage_bps: float = 1.0
    # Fractions of the position's own margin, not of price.
    stop_loss: float | None = None
    take_profit: float | None = None
    max_hold_bars: int | None = None

    @property
    def entry_cost(self) -> float:
        return (self.fee_bps + self.slippage_bps) / 1e4

    @property
    def exit_cost(self) -> float:
        return (self.fee_bps + self.slippage_bps) / 1e4


def liquidation_level(side: int, wallet: float, qty: float,
                      entry: float, table: TierTable) -> float:
    """Price at which the maintenance margin is breached.

        long   WB + Q*(P-EP) = Q*P*MMR - cumB  ->  P = (Q*EP - WB - cumB)/(Q*(1-MMR))
        short  WB + Q*(EP-P) = Q*P*MMR - cumB  ->  P = (Q*EP + WB + cumB)/(Q*(1+MMR))

    The short side has no upper bound on loss, which is the asymmetry Track B
    has to keep in view: a long can lose its margin, a short can be asked for
    more than it put up.
    """
    price = entry
    for _ in range(_LIQ_ITERS):
        mmr, cum = table.lookup(np.array([qty * price]))
        mmr, cum = float(mmr[0]), float(cum[0])
        if side == LONG:
            denom = qty * (1.0 - mmr)
            price = (qty * entry - wallet - cum) / denom if denom > 0 else 0.0
        else:
            price = (qty * entry + wallet + cum) / (qty * (1.0 + mmr))
    return max(price, 0.0)


def _first_true(mask: np.ndarray) -> int:
    """Index of the first True, or -1.  argmax alone cannot tell them apart."""
    return int(np.argmax(mask)) if mask.any() else -1


def run_signals(
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    entry: np.ndarray,
    exit_: np.ndarray,
    spec: SignalSpec,
    funding_rate: np.ndarray | None = None,
    symbol: str = "",
    table: TierTable | None = None,
) -> dict:
    """Walk the signals and return the equity curve and every trade.

    `entry` is +1 / -1 / 0 per bar and `exit_` is boolean.  Both are read at bar
    i and acted on at bar i+1.
    """
    close = np.asarray(close, dtype=np.float64)
    high = np.asarray(high, dtype=np.float64)
    low = np.asarray(low, dtype=np.float64)
    entry = np.asarray(entry, dtype=np.int8)
    exit_ = np.asarray(exit_, dtype=bool)
    n = close.size
    if not (high.size == low.size == entry.size == exit_.size == n):
        raise ValueError("close, high, low, entry and exit_ must be the same length")
    if n < 3:
        raise ValueError("a panel needs at least three bars to signal, fill and exit")

    table = table or tier_table_for(symbol)
    if spec.leverage > table.max_leverage:
        raise ValueError(f"leverage {spec.leverage} exceeds {table.max_leverage} "
                         f"for the {table.name} tier table")

    # Funding accrues per bar on the position's notional.  Prefix sums make the
    # bill over any held window O(1), which is what keeps the trade scan cheap.
    if funding_rate is None:
        flow_cum = np.zeros(n + 1, dtype=np.float64)
    else:
        flow = close * np.asarray(funding_rate, dtype=np.float64)
        flow_cum = np.concatenate(([0.0], np.cumsum(flow)))

    entry_idx = np.flatnonzero(entry != 0)
    exit_idx = np.flatnonzero(exit_)

    equity = np.full(n, spec.capital, dtype=np.float64)
    trades: list[dict] = []
    cash = spec.capital
    i = 0

    while cash > 0.0:
        k = int(np.searchsorted(entry_idx, i, side="left"))
        if k >= entry_idx.size:
            break
        sig_bar = int(entry_idx[k])
        a = sig_bar + 1                                   # fill on the next bar
        if a > n - 2:
            break

        side = int(entry[sig_bar])
        fill = close[a] * (1.0 + side * spec.entry_cost)
        qty = cash * spec.leverage / fill
        liq = liquidation_level(side, cash, qty, fill, table)

        # Last bar this trade could still be open on: the bar after the next
        # exit signal, or the end of the panel if none comes.
        ke = int(np.searchsorted(exit_idx, a, side="left"))
        sig_exit = int(exit_idx[ke]) if ke < exit_idx.size else n - 2
        b = min(sig_exit + 1, n - 1)
        if spec.max_hold_bars is not None:
            b = min(b, a + spec.max_hold_bars)

        adverse = low[a:b + 1] if side == LONG else high[a:b + 1]
        favour = high[a:b + 1] if side == LONG else low[a:b + 1]

        # Every way this trade can end, as (bar offset, priority, reason, price).
        ends = [(b - a, _PRIORITY["signal"], "signal", float(close[b]))]

        hit = _first_true(adverse <= liq if side == LONG else adverse >= liq)
        if hit >= 0:
            ends.append((hit, _PRIORITY["liquidation"], "liquidation", liq))
        if spec.stop_loss is not None:
            lvl = fill - side * spec.stop_loss * cash / qty
            hit = _first_true(adverse <= lvl if side == LONG else adverse >= lvl)
            if hit >= 0:
                ends.append((hit, _PRIORITY["stop"], "stop", lvl))
        if spec.take_profit is not None:
            lvl = fill + side * spec.take_profit * cash / qty
            hit = _first_true(favour >= lvl if side == LONG else favour <= lvl)
            if hit >= 0:
                ends.append((hit, _PRIORITY["take_profit"], "take_profit", lvl))

        off, _, reason, px = min(ends)
        b = a + off
        exit_px = px if reason == "liquidation" else px * (1.0 - side * spec.exit_cost)

        # A long pays positive funding; a short collects it.
        funding = -side * qty * float(flow_cum[b + 1] - flow_cum[a])
        gross = side * qty * (exit_px - fill)
        pnl = -cash if reason == "liquidation" else gross + funding

        # Mark the curve bar by bar so drawdown sees the path, not just the fills.
        unreal = side * qty * (close[a:b + 1] - fill)
        accrued = -side * qty * (flow_cum[a + 1:b + 2] - flow_cum[a])
        equity[a:b + 1] = np.maximum(cash + unreal + accrued, 0.0)

        cash = max(cash + pnl, 0.0)
        equity[b:] = cash
        trades.append({
            "side": side, "entry_bar": a, "exit_bar": b, "bars_held": b - a,
            "entry_price": fill, "exit_price": exit_px, "reason": reason,
            "qty": qty, "funding": funding, "gross": gross, "pnl": pnl,
            "equity_after": cash,
        })
        if cash <= 0.0:
            break
        i = b + 1

    wins = sum(1 for t in trades if t["pnl"] > 0)
    return {
        "equity": equity,
        "trades": trades,
        "n_trades": len(trades),
        "win_rate": wins / len(trades) if trades else float("nan"),
        "funding_collected": float(sum(t["funding"] for t in trades)),
        "n_liquidations": sum(1 for t in trades if t["reason"] == "liquidation"),
        "final_equity": float(cash),
    }
