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
                   position is gone regardless of where the bar closed, AND
                   THE ACCOUNT IS AT ZERO. Not the residue above the bankruptcy
                   price -- zero.

                   Decided 2026-09-05 and written here because it had never
                   been written anywhere. The differential oracle found it: an
                   independently written second implementation kept the residue
                   (1000 -> 40.4 on a 5x long halved) and went on trading, and
                   every numeric disagreement between the two traced to this
                   one unstated choice. With no liquidation in the window they
                   agree to 0.00e+00.

                   Zero, for three reasons that all point the same way. A
                   Binance USD-M liquidation is an immediate-or-cancel order
                   plus a clearance fee (CLAUDE.md section 7b), which takes the
                   position margin; the residue assumes a fill exactly at the
                   maintenance-margin price, which is the one price a forced
                   IOC order is least likely to get. KT-2 closed leverage above
                   1x on `liquidation rate hits 100% at 2x and above`, and that
                   conclusion reads a liquidation as ruin. And it is the
                   pessimistic reading, which is what every other line in this
                   list chooses when the data cannot say.
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
_PRIORITY = {"liquidation": 0, "stop": 1, "take_profit": 2, "max_hold": 3,
             "signal": 4}


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


def liquidation_level(side: int, wallet, qty: float,
                      entry: float, table: TierTable):
    """Price at which the maintenance margin is breached.

        long   WB + Q*(P-EP) = Q*P*MMR - cumB  ->  P = (Q*EP - WB - cumB)/(Q*(1-MMR))
        short  WB + Q*(EP-P) = Q*P*MMR - cumB  ->  P = (Q*EP + WB + cumB)/(Q*(1+MMR))

    The short side has no upper bound on loss, which is the asymmetry Track B
    has to keep in view: a long can lose its margin, a short can be asked for
    more than it put up.

    `wallet` may be an array, one entry per bar, and that is the whole point.
    WB is the isolated wallet balance, and funding settles against it: a payer's
    wallet shrinks every eight hours, which walks the liquidation price toward
    the entry.  Computing this once at the fill and never again is what let a
    position whose margin had been eaten by funding go on trading -- the level
    stayed where the entry wallet put it, `adverse >= liq` never fired, and the
    trade closed on its ordinary signal exit with an arithmetically consistent
    set of numbers.
    """
    scalar = np.isscalar(wallet) or np.ndim(wallet) == 0
    wal = np.atleast_1d(np.asarray(wallet, dtype=np.float64))
    price = np.full(wal.shape, float(entry), dtype=np.float64)
    for _ in range(_LIQ_ITERS):
        mmr, cum = table.lookup(qty * price)
        if side == LONG:
            denom = qty * (1.0 - mmr)
            price = np.where(denom > 0, (qty * entry - wal - cum) / denom, 0.0)
        else:
            price = (qty * entry + wal + cum) / (qty * (1.0 + mmr))
    price = np.maximum(price, 0.0)
    return float(price[0]) if scalar else price


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
    # max_leverage is tier 0's, which applies only to the smallest notionals.
    # Checking against it let a position run at a size the exchange caps lower:
    # 25x on 10,000 is a notional of 250,000, which sits in a bracket where the
    # allowed leverage is 10. Check the bracket the position actually lands in.
    notional = spec.capital * spec.leverage
    allowed = table.leverage_at(notional)
    if spec.leverage > allowed:
        raise ValueError(f"leverage {spec.leverage} exceeds {allowed} at a notional "
                         f"of {notional:,.0f} on the {table.name} tier table")

    # Funding accrues per bar on the position's notional.  Prefix sums make the
    # bill over any held window O(1), which is what keeps the trade scan cheap.
    if funding_rate is None:
        flow_cum = np.zeros(n + 1, dtype=np.float64)
    else:
        fr = np.asarray(funding_rate, dtype=np.float64)
        # The same refusal simulate.py:93 already makes, and for the same
        # reason -- it was simply missing on this side.  One non-finite rate
        # turns the wallet into NaN, `adverse <= liq` is False for NaN, so
        # liquidation is never detected again on that path: the trade is
        # reported as a survivor.  Worse, the two RuntimeError invariants meant
        # to catch exactly this (the wallet check and the trade-log
        # reconciliation) also compare against NaN and are silently False, so
        # the run completes and reports CAGR, Sharpe and a liquidation count
        # that are all fiction.
        if not np.isfinite(fr).all():
            raise ValueError(
                f"funding_rate carries {int((~np.isfinite(fr)).sum())} non-finite "
                "value(s); a NaN here makes every trade that touches it "
                "unliquidatable and defeats the invariants meant to catch that")
        flow = close * fr
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

        # Last bar this trade could still be open on: the bar after the next
        # exit signal, or the end of the panel if none comes.
        ke = int(np.searchsorted(exit_idx, a, side="left"))
        sig_exit = int(exit_idx[ke]) if ke < exit_idx.size else n - 2
        b = min(sig_exit + 1, n - 1)
        # Which of the two ended it, kept rather than collapsed. `max_hold` had
        # no entry in _PRIORITY, so a position closed by the CLOCK was reported
        # as "signal" -- an exit nothing signalled. The timing and the equity
        # were right; the exits histogram execution_realism prints was not, and
        # a reader counting signal exits was counting two different things.
        #
        # Found by the differential oracle: after five specification gaps were
        # closed it was the ONE remaining disagreement across 400 fuzz cases,
        # and the only one where the reference was right and this was wrong.
        # `<=`, not `<`. When the clock and the exit signal land on the SAME
        # bar the tie goes to max_hold, because _PRIORITY orders it ahead of
        # signal -- and the whole point of that table is that ties resolve the
        # same way everywhere. Written with `<` first, which reported the tie
        # as "signal" and was the last disagreement the oracle held on to.
        held_out = False
        if spec.max_hold_bars is not None and a + spec.max_hold_bars <= b:
            b = a + spec.max_hold_bars
            held_out = True

        # The scan starts at a+1, not at a.  The fill is close[a], so bar a's
        # own extremes all happened before the position existed and cannot
        # touch it.  Including them let a target be hit on the entry bar by a
        # spike that preceded the fill: a flat series with high[5]=130 and a
        # fill at close[5]=100 returned a closed trade with bars_held 0 and
        # +20%, read entirely off a price the position never saw.  The mirror
        # fabricates losses, and both are structurally identical to real trades.
        scan = slice(a + 1, b + 1)
        adverse = low[scan] if side == LONG else high[scan]
        favour = high[scan] if side == LONG else low[scan]

        # The wallet the exchange would see at each scanned bar.  Funding has
        # already settled against it by then, so the liquidation level moves
        # with it rather than staying where the fill left it.
        #
        # Which side of the bar the settlement falls on is unknowable at this
        # resolution, so the check takes the worse of the two -- the wallet
        # before this bar's settlement and after it.  For a payer that is the
        # post-settlement wallet, and the wick is met on the smaller margin;
        # for a collector it is the pre-settlement wallet, so a coupon is never
        # allowed to rescue a position from a low that may have printed first.
        acc = -side * qty * (flow_cum[a + 2:b + 2] - flow_cum[a + 1])
        acc_prev = -side * qty * (flow_cum[a + 1:b + 1] - flow_cum[a + 1])
        liq = liquidation_level(side, cash + np.minimum(acc, acc_prev),
                                qty, fill, table)

        # Every way this trade can end, as (bar offset, priority, reason, price).
        _why = "max_hold" if held_out else "signal"
        ends = [(b - a, _PRIORITY[_why], _why, float(close[b]))]

        hit = _first_true(adverse <= liq if side == LONG else adverse >= liq)
        if hit >= 0:
            ends.append((hit + 1, _PRIORITY["liquidation"], "liquidation",
                         float(liq[hit])))
        if spec.stop_loss is not None:
            lvl = fill - side * spec.stop_loss * cash / qty
            hit = _first_true(adverse <= lvl if side == LONG else adverse >= lvl)
            if hit >= 0:
                ends.append((hit + 1, _PRIORITY["stop"], "stop", lvl))
        if spec.take_profit is not None:
            lvl = fill + side * spec.take_profit * cash / qty
            hit = _first_true(favour >= lvl if side == LONG else favour <= lvl)
            if hit >= 0:
                ends.append((hit + 1, _PRIORITY["take_profit"], "take_profit", lvl))

        off, _, reason, px = min(ends)
        b = a + off
        exit_px = px if reason == "liquidation" else px * (1.0 - side * spec.exit_cost)

        # A long pays positive funding; a short collects it -- from bar a+1.
        # Panels are labelled by open time and a settlement sits on the bar
        # containing it, so bar a's settlement cleared before the fill at
        # close[a].  Summing from a credited a full-notional settlement to a
        # position that did not yet exist, on roughly one trade in eight, in a
        # family whose entire subject is funding income.
        funding = -side * qty * float(flow_cum[b + 1] - flow_cum[a + 1])

        if reason == "liquidation":
            # The isolated wallet is gone, all of it, and the insurance fund
            # absorbs whatever the book gave up beyond it.  The coupon accrued
            # up to this bar was real and was sitting in that wallet when it
            # was taken, so it is reported as collected AND the price leg is
            # made to absorb the rest: the two legs sum to the loss instead of
            # the coupon being reported as income beside a wallet of zero.
            # `funding_collected` used to sum a figure no wallet ever kept --
            # 3,600 of funding on an account that ended at 0.0, which is
            # numerically the mirror image of KT-1's 36 % tax and exactly the
            # number Track B's first family exists to find.
            pnl = -cash
            gross = pnl - funding
        else:
            gross = side * qty * (exit_px - fill)
            pnl = gross + funding

        # Mark the curve bar by bar so drawdown sees the path, not just the fills.
        unreal = side * qty * (close[a:b + 1] - fill)
        accrued = -side * qty * (flow_cum[a + 1:b + 2] - flow_cum[a + 1])
        path = cash + unreal + accrued

        # Now that the liquidation level tracks the wallet, an ordinary exit
        # CANNOT lose more than the wallet: the check is made against the bar's
        # adverse extreme, which is at least as bad as its close, so a mark
        # equity that goes through zero has already been liquidated with
        # priority over every other exit.  The clamp that used to stand here --
        # cash = max(cash + pnl, 0.0), with np.maximum on the path -- absorbed
        # a wipeout into a zero and could not tell 'lost exactly the wallet'
        # from 'lost twice the wallet': a flat series paying 0.6 % every eight
        # hours booked a trade pnl of -22,200 against a 10,000 wallet as an
        # ordinary signal exit, and if the funding regime flipped back the
        # curve carried negative equity for 104 bars and recovered to +56 %.
        # So the invariant is asserted rather than clamped.  If it ever fires,
        # the liquidation check has a hole and no Track B number is safe.
        if reason == "liquidation":
            path = np.maximum(path, 0.0)
            path[-1] = 0.0
            equity[a:b + 1] = path
            cash = 0.0
        else:
            floor = -1e-9 * spec.capital
            worst = float(path.min())
            if worst < floor or cash + pnl < floor:
                raise RuntimeError(
                    f"a {'long' if side == LONG else 'short'} closed on "
                    f"'{reason}' lost more than its wallet: mark equity fell to "
                    f"{worst:,.2f} and the trade booked {pnl:,.2f} against a "
                    f"wallet of {cash:,.2f} (funding {funding:,.2f}, gross "
                    f"{gross:,.2f}, entry bar {a}, exit bar {b}). The "
                    "liquidation check did not see it, so it has a hole.")
            equity[a:b + 1] = path
            cash = cash + pnl
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

    # The trade log and the equity curve are two accounts of the same money and
    # they have to agree.  They did not: the clamp meant sum(pnl) could read
    # -22,200 while the curve had moved -10,000, and nothing cross-footed them,
    # so the contradiction never met itself.
    booked = float(sum(t["pnl"] for t in trades))
    moved = float(cash) - spec.capital
    if abs(booked - moved) > max(1e-6, 1e-9 * spec.capital):
        raise RuntimeError(
            f"the trade log does not reconcile with the equity curve: trades "
            f"book {booked:,.2f} and the curve moved {moved:,.2f}")

    return {
        "equity": equity,
        "trades": trades,
        "n_trades": len(trades),
        "win_rate": wins / len(trades) if trades else float("nan"),
        # Reported together, always.  Either alone is a story: the coupon
        # without the price leg says a losing short was a carry trade, and the
        # price leg without the coupon says the opposite.  They sum to pnl_total
        # by construction, including on liquidated trades.
        "funding_collected": float(sum(t["funding"] for t in trades)),
        "gross_collected": float(sum(t["gross"] for t in trades)),
        "pnl_total": booked,
        "n_liquidations": sum(1 for t in trades if t["reason"] == "liquidation"),
        "final_equity": float(cash),
    }
