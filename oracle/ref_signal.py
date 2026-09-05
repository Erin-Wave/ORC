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
    exit_ = np.asarray(exit_, dtype=bool)

    n = close.size
    if high.shape != close.shape or low.shape != close.shape:
        raise ValueError("close, high, and low must have the same shape")
    if entry.shape != close.shape or exit_.shape != close.shape:
        raise ValueError("entry and exit_ must have one value per bar")
    if not np.all(np.isin(entry, (SHORT, FLAT, LONG))):
        raise ValueError("entry values must be LONG, SHORT, or FLAT")
    if not np.all(np.isfinite(close)):
        raise ValueError("close contains non-finite values")
    if not np.all(np.isfinite(high)):
        raise ValueError("high contains non-finite values")
    if not np.all(np.isfinite(low)):
        raise ValueError("low contains non-finite values")
    if np.any(close <= 0.0) or np.any(high <= 0.0) or np.any(low <= 0.0):
        raise ValueError("prices must be positive")
    if np.any(high < low):
        raise ValueError("high must not be below low")

    if funding_rate is None:
        rates = np.zeros(n, dtype=np.float64)
    else:
        rates = np.asarray(funding_rate, dtype=np.float64)
        if rates.shape != close.shape:
            raise ValueError("funding_rate must have one value per bar")
        if not np.all(np.isfinite(rates)):
            raise ValueError("funding_rate contains non-finite values")

    if n == 0:
        return {
            "equity": np.empty(0, dtype=np.float64),
            "n_trades": 0,
            "trades": [],
            "n_liquidations": 0,
            "funding_collected": 0.0,
            "final_equity": float(spec.capital),
        }

    if table is None:
        table = tier_table_for(symbol)

    cost = (float(spec.fee_bps) + float(spec.slippage_bps)) / 1e4
    leverage = float(spec.leverage)
    wallet = float(spec.capital)

    equity = np.empty(n, dtype=np.float64)
    equity[0] = wallet

    trades = []
    n_liquidations = 0
    funding_collected = 0.0

    side = FLAT
    entry_bar = -1
    entry_price = 0.0
    entry_wallet = 0.0
    qty = 0.0
    trade_funding = 0.0

    def fill_price(price, order_side):
        if order_side == LONG:
            return price * (1.0 + cost)
        return price * (1.0 - cost)

    def mark_equity(price):
        if side == FLAT:
            return wallet
        return wallet + side * qty * (price - entry_price)

    def close_position(bar, reason, raw_price):
        nonlocal wallet
        nonlocal side
        nonlocal entry_bar
        nonlocal entry_price
        nonlocal entry_wallet
        nonlocal qty
        nonlocal trade_funding
        nonlocal n_liquidations

        exit_order_side = SHORT if side == LONG else LONG
        exit_price = fill_price(float(raw_price), exit_order_side)
        gross = side * qty * (exit_price - entry_price)
        pnl = gross + trade_funding
        wallet = entry_wallet + pnl

        trades.append(
            {
                "entry_bar": entry_bar,
                "exit_bar": int(bar),
                "side": int(side),
                "entry_price": float(entry_price),
                "exit_price": float(exit_price),
                "bars_held": int(bar - entry_bar),
                "reason": reason,
                "gross": float(gross),
                "funding": float(trade_funding),
                "pnl": float(pnl),
            }
        )

        if reason == "liquidation":
            n_liquidations += 1

        side = FLAT
        entry_bar = -1
        entry_price = 0.0
        entry_wallet = 0.0
        qty = 0.0
        trade_funding = 0.0

    for bar in range(1, n):
        if side == FLAT:
            requested_side = int(entry[bar - 1])
            if requested_side != FLAT and wallet != 0.0:
                notional = abs(wallet) * leverage
                allowed_leverage = table.leverage_at(notional)
                if leverage > allowed_leverage:
                    raise ValueError(
                        f"leverage {leverage} exceeds tier maximum "
                        f"{allowed_leverage} for notional {notional}"
                    )

                side = requested_side
                entry_bar = bar
                entry_wallet = wallet
                entry_price = fill_price(close[bar], side)
                qty = notional / entry_price
                trade_funding = 0.0

            equity[bar] = mark_equity(close[bar])
            continue

        funding = -side * qty * close[bar] * rates[bar]
        wallet += funding
        trade_funding += funding
        funding_collected += funding

        reason = None
        raw_exit_price = None

        if wallet <= 0.0:
            reason = "liquidation"
            raw_exit_price = close[bar]
        else:
            liq = liquidation_level(
                side,
                wallet,
                qty,
                entry_price,
                table,
            )
            if side == LONG and low[bar] <= liq:
                reason = "liquidation"
                raw_exit_price = liq
            elif side == SHORT and high[bar] >= liq:
                reason = "liquidation"
                raw_exit_price = liq

        if reason is None and spec.stop_loss is not None:
            stop_distance = entry_price * float(spec.stop_loss) / leverage
            stop_price = entry_price - side * stop_distance
            if side == LONG and low[bar] <= stop_price:
                reason = "stop"
                raw_exit_price = stop_price
            elif side == SHORT and high[bar] >= stop_price:
                reason = "stop"
                raw_exit_price = stop_price

        if reason is None and spec.take_profit is not None:
            target_distance = entry_price * float(spec.take_profit) / leverage
            target_price = entry_price + side * target_distance
            if side == LONG and high[bar] >= target_price:
                reason = "take_profit"
                raw_exit_price = target_price
            elif side == SHORT and low[bar] <= target_price:
                reason = "take_profit"
                raw_exit_price = target_price

        if reason is None and exit_[bar - 1]:
            reason = "signal"
            raw_exit_price = close[bar]

        if (
            reason is None
            and spec.max_hold_bars is not None
            and bar - entry_bar >= int(spec.max_hold_bars)
        ):
            reason = "max_hold"
            raw_exit_price = close[bar]

        if reason is not None:
            close_position(bar, reason, raw_exit_price)

        equity[bar] = mark_equity(close[bar])

    if side != FLAT:
        close_position(n - 1, "end", close[-1])
        equity[-1] = wallet

    pnl_total = wallet - float(spec.capital)
    gross_collected = sum(trade["gross"] for trade in trades)
    wins = sum(trade["pnl"] > 0.0 for trade in trades)

    return {
        "equity": equity,
        "n_trades": len(trades),
        "trades": trades,
        "n_liquidations": n_liquidations,
        "funding_collected": float(funding_collected),
        "gross_collected": float(gross_collected),
        "pnl_total": float(pnl_total),
        "final_equity": float(wallet),
        "win_rate": float(wins / len(trades)) if trades else 0.0,
    }