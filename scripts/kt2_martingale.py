"""ORC | KILL TEST 2 -- is levered averaging-down a martingale?

"Buy more when it falls" plus leverage is a martingale: the equity curve is
beautiful until the bar where the position is liquidated, and a backtest that
models liquidation loosely will never show you that bar.

This test does not ask whether the strategy is profitable.  It asks a narrower
and more important question: at what leverage does the LEFT TAIL become an
absorbing state?  A strategy whose 5th percentile is a total loss is not a
strategy with a bad tail, it is a strategy with a termination condition.

Decision rule, frozen before results were seen:

  * Any (leverage, gate) cell whose liquidation rate across start dates exceeds
    5 % is CLOSED. Not penalised -- closed. Liquidation is not a drawdown you
    recover from.

Run:  python scripts/kt2_martingale.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orc import config
from orc.eval.simulate import SimSpec, gate_below_trailing_peak, simulate
from orc.facts import panel as panel_mod
from orc.kernel.liquidation import liquidation_price_long, tier_table_for
from orc.kernel.metrics_cf import start_date_profile

MAX_ACCEPTABLE_LIQUIDATION_RATE = 0.05
LEVERAGES = (1.0, 2.0, 3.0, 5.0, 10.0)
GATES = ("none", "dip:0.10:90", "dip:0.25:365")
CONTRIBUTION = 100.0
STRIDE_DAYS = 7.0
N_CONTRIB = 156                      # three years of weekly deposits


def run_cell(p, leverage: float, gate_spec: str) -> dict:
    stride = p.bars(STRIDE_DAYS)
    horizon = (N_CONTRIB - 1) * stride
    if horizon >= len(p):
        return {"status": "history too short"}

    gate = None
    if gate_spec != "none":
        _, drop, look = gate_spec.split(":")
        gate = gate_below_trailing_peak(p.close, float(drop), p.bars(float(look)))

    spec = SimSpec(contribution=CONTRIBUTION, stride_bars=stride,
                   n_contributions=N_CONTRIB, leverage=leverage,
                   fee_bps=config.TAKER_FEE_BPS, slippage_bps=config.SLIPPAGE_BPS,
                   exit_fee_bps=config.TAKER_FEE_BPS)
    starts = np.arange(0, len(p) - horizon - 1, max(p.bars(1.0), 1), dtype=np.int64)
    if starts.size == 0:
        return {"status": "no start dates"}

    out = simulate(p.close, p.low, starts, spec, funding_rate=p.funding_rate,
                   gate=gate, table=tier_table_for(p.symbol))
    tm = start_date_profile(out["terminal_multiple"])
    horizon_days = horizon / float(p.bars_per_day)
    span_days = float((p.ts[int(starts.max())] - p.ts[int(starts.min())])
                      / np.timedelta64(1, "D"))
    return {
        "status": "ok",
        "n_starts": out["n_starts"],
        "start_first": str(p.ts[int(starts.min())])[:10],
        "start_last": str(p.ts[int(starts.max())])[:10],
        "effective_independent_paths": round(span_days / max(horizon_days, 1.0) + 1.0, 2),
        "liquidation_rate": out["liquidation_rate"],
        "terminal_multiple": {k: tm[k] for k in ("q01", "q05", "q50", "q95", "worst")},
        "max_dd_total_q95": float(np.quantile(out["max_dd_total"], 0.95)),
        "closed": out["liquidation_rate"] > MAX_ACCEPTABLE_LIQUIDATION_RATE,
    }


def main() -> int:
    config.ensure_dirs()
    symbols = panel_mod.available_symbols("1h")
    if not symbols:
        print("no panels built yet")
        return 2

    print("KT-2  levered averaging-down: where does the left tail become absorbing?")
    print(f"      {N_CONTRIB} weekly deposits, funding charged, liquidation at the bar low")
    print(f"      close threshold: liquidation rate > {MAX_ACCEPTABLE_LIQUIDATION_RATE:.0%}\n")

    ref = liquidation_price_long(3000.0, 3000.0 * 10 / 50_000.0, 50_000.0,
                                 tier_table_for("BTCUSDT"))
    print(f"  reference: a 10x BTC long liquidates {(1 - float(ref)/50_000)*100:.2f} %"
          f" below entry\n")

    rows = []
    for sym in symbols:
        try:
            p = panel_mod.load(sym, "1h", development_only=True)
        except (FileNotFoundError, ValueError):
            continue
        for lev in LEVERAGES:
            for gate in GATES:
                r = run_cell(p, lev, gate)
                if r.get("status") != "ok":
                    continue
                r.update(symbol=sym, leverage=lev, gate=gate)
                rows.append(r)
                mark = "CLOSED" if r["closed"] else "open  "
                print(f"  {sym:10s} lev {lev:4.1f}x  {gate:15s} "
                      f"liq {r['liquidation_rate']*100:6.2f}%  "
                      f"tm q05 {r['terminal_multiple']['q05']:+.3f}  {mark}  "
                      f"starts {r['start_first']}..{r['start_last']} "
                      f"(~{r['effective_independent_paths']} independent)")

    if not rows:
        print("\nno cell produced a result")
        return 2

    survivors = [r for r in rows if not r["closed"]]
    max_open_lev = max((r["leverage"] for r in survivors), default=0.0)
    report = {
        "kill_test": "KT-2 levered averaging-down",
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "threshold_frozen_before_results": MAX_ACCEPTABLE_LIQUIDATION_RATE,
        "cells": len(rows),
        "cells_closed": len(rows) - len(survivors),
        "highest_leverage_still_open": max_open_lev,
        "verdict": ("LEVERAGE_CAPPED_AT_%g" % max_open_lev) if max_open_lev
                   else "ALL_LEVERAGE_CLOSED",
        "per_cell": rows,
    }
    out = config.REPORTS / "KT2_MARTINGALE.json"
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    print("\n" + "=" * 68)
    print(f"cells {len(rows)}, closed {report['cells_closed']}")
    print(f"highest leverage that survives the tail test: {max_open_lev:g}x")
    print(f"VERDICT: {report['verdict']}")
    print("=" * 68)
    print(f"written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
