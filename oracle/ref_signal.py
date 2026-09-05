from __future__ import annotations

import numpy as np

from orc.eval.signal import (
    FLAT,
    LONG,
    SHORT,
    SignalSpec,
    liquidation_level,
    tier_table_for,
)


def ref_run_signals(
    close,
    high,
    low,
    entry,
    exit_,
    spec,
    funding_rate=None,
    symbol="",
    table=None,
) -> dict:
    close = np.asarray(close, dtype=np.float64)
    high = np.asarray(high, dtype=np.float64)
    low = np.asarray(low, dtype=np.float64)
    entry = np.asarray(entry, dtype=np.int8)
    exit_ = np.asarray(exit_, dtype=np.bool_)

    if close.ndim != 1:
        raise ValueError("inputs must be one-dimensional")
    if high.shape != close.shape or low.shape != close.shape:
        raise ValueError("close, high, and low must have identical shapes")
    if entry.shape != close.shape or exit_.shape != close.shape:
        raise ValueError("signals must have one value per bar")
    if np.any((entry != LONG) & (entry != SHORT) & (entry != FLAT)):
        raise ValueError("entry must contain only LONG, SHORT, or FLAT")

    n_bars = close.size

    if funding_rate is None:
        funding_rate = np.zeros(n_bars, dtype=np.float64)
    else:
        funding_rate = np.asarray(funding_rate, dtype=np.float64)
        if funding_rate.shape != close.shape:
            raise ValueError("funding_rate must have one value per bar")

    equity = np.full(n_bars, float(spec.capital), dtype=np.float64)
    trades = []
    funding_collected = 0.0
    n_liquidations = 0

    if n_bars == 0:
        return {
            "equity": equity,
            "final_equity": float(spec.capital),
            "n_trades": 0,
            "trades": trades,
            "n_liquidations": 0,
            "funding_collected": 0.0,
        }

    if table is None:
        table = tier_table_for(symbol)

    cost_rate = (
        float(spec.fee_bps) + float(spec.slippage_bps)
    ) / 10_000.0
    leverage = float(spec.leverage)

    wallet = float(spec.capital)
    ruined = False

    side = FLAT
    entry_bar = -1
    entry_price = 0.0
    quantity = 0.0
    trade_funding = 0.0

    first_eligible_signal_bar = 0

    def entry_fill(raw_price, position_side):
        if position_side == LONG:
            return float(raw_price) * (1.0 + cost_rate)
        return float(raw_price) * (1.0 - cost_rate)

    def exit_fill(raw_price, position_side):
        if position_side == LONG:
            return float(raw_price) * (1.0 - cost_rate)
        return float(raw_price) * (1.0 + cost_rate)

    def finish_trade(bar, reason, raw_exit_price):
        nonlocal wallet
        nonlocal ruined
        nonlocal side
        nonlocal entry_bar
        nonlocal entry_price
        nonlocal quantity
        nonlocal trade_funding
        nonlocal funding_collected
        nonlocal n_liquidations
        nonlocal first_eligible_signal_bar

        closed_side = side
        closed_entry_bar = entry_bar
        closed_entry_price = entry_price
        closed_quantity = quantity
        closed_funding = trade_funding

        if reason == "liquidation":
            actual_exit_price = float(raw_exit_price)
            price_pnl = -wallet
            wallet = 0.0
            ruined = True
            n_liquidations += 1
        else:
            actual_exit_price = exit_fill(raw_exit_price, closed_side)
            price_pnl = (
                float(closed_side)
                * closed_quantity
                * (actual_exit_price - closed_entry_price)
            )
            wallet += price_pnl

        funding_collected += closed_funding

        trades.append(
            {
                "entry_bar": int(closed_entry_bar),
                "exit_bar": int(bar),
                "bars_held": int(bar - closed_entry_bar),
                "side": int(closed_side),
                "entry_price": float(closed_entry_price),
                "exit_price": float(actual_exit_price),
                "reason": reason,
                "funding": float(closed_funding),
                "pnl": float(price_pnl + closed_funding),
            }
        )

        side = FLAT
        entry_bar = -1
        entry_price = 0.0
        quantity = 0.0
        trade_funding = 0.0

        # The position was still open while this bar's signal was observed.
        first_eligible_signal_bar = bar + 1

    for bar in range(n_bars):
        if ruined:
            equity[bar] = 0.0
            continue

        opened_here = False

        # A final-bar fill would have to be closed on its entry bar. Since no
        # trade may enter and exit on one bar, the last possible fill is n-2.
        if side == FLAT and 1 <= bar < n_bars - 1:
            signal_bar = bar - 1

            if signal_bar >= first_eligible_signal_bar:
                requested_side = int(entry[signal_bar])

                if requested_side != FLAT:
                    side = requested_side
                    entry_bar = bar
                    entry_price = entry_fill(close[bar], side)
                    quantity = wallet * leverage / entry_price
                    trade_funding = 0.0
                    opened_here = True

        if side == FLAT:
            equity[bar] = wallet
            continue

        mark_price = float(close[bar])

        # The fill is at this bar's close. This bar's extremes and funding
        # precede the fill and therefore cannot affect the new position.
        if opened_here:
            equity[bar] = (
                wallet
                + float(side) * quantity * (mark_price - entry_price)
            )
            continue

        liquidation_price = float(
            liquidation_level(
                side,
                wallet,
                quantity,
                entry_price,
                table,
            )
        )

        if side == LONG:
            liquidation_hit = float(low[bar]) <= liquidation_price
        else:
            liquidation_hit = float(high[bar]) >= liquidation_price

        if liquidation_hit:
            trade_funding += (
                -float(side)
                * quantity
                * mark_price
                * float(funding_rate[bar])
            )
            finish_trade(bar, "liquidation", liquidation_price)
            equity[bar] = 0.0
            continue

        funding_cashflow = (
            -float(side)
            * quantity
            * mark_price
            * float(funding_rate[bar])
        )
        wallet += funding_cashflow
        trade_funding += funding_cashflow

        if wallet <= 0.0:
            finish_trade(bar, "liquidation", mark_price)
            equity[bar] = 0.0
            continue

        if spec.stop_loss is not None:
            stop_distance = float(spec.stop_loss) / leverage

            if side == LONG:
                stop_price = entry_price * (1.0 - stop_distance)
                stop_hit = float(low[bar]) <= stop_price
            else:
                stop_price = entry_price * (1.0 + stop_distance)
                stop_hit = float(high[bar]) >= stop_price

            if stop_hit:
                finish_trade(bar, "stop", stop_price)
                equity[bar] = wallet
                continue

        if spec.take_profit is not None:
            target_distance = float(spec.take_profit) / leverage

            if side == LONG:
                target_price = entry_price * (1.0 + target_distance)
                target_hit = float(high[bar]) >= target_price
            else:
                target_price = entry_price * (1.0 - target_distance)
                target_hit = float(low[bar]) <= target_price

            if target_hit:
                finish_trade(bar, "take_profit", target_price)
                equity[bar] = wallet
                continue

        if spec.max_hold_bars is not None:
            if bar - entry_bar >= int(spec.max_hold_bars):
                finish_trade(bar, "max_hold", mark_price)
                equity[bar] = wallet
                continue

        # The exit signal from the preceding bar fills at this bar's close.
        if bool(exit_[bar - 1]):
            finish_trade(bar, "signal", mark_price)
            equity[bar] = wallet
            continue

        if bar == n_bars - 1:
            finish_trade(bar, "signal", mark_price)
            equity[bar] = wallet
            continue

        equity[bar] = (
            wallet
            + float(side) * quantity * (mark_price - entry_price)
        )

    return {
        "equity": equity,
        "final_equity": float(equity[-1]),
        "n_trades": len(trades),
        "trades": trades,
        "n_liquidations": int(n_liquidations),
        "funding_collected": float(funding_collected),
    }