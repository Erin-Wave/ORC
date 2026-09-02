"""ORC | KILL TEST 1 -- does perpetual funding kill long DCA?

A perpetual long pays funding on the FULL NOTIONAL, at every settlement,
regardless of leverage.  Before building anything on top of "DCA into a perp
long", measure what that costs over the archive.

Decision rule, written before the numbers were seen:

  * If the median funding bill exceeds 25 % of contributed capital over a
    3-year DCA, then a perpetual long is a structurally worse container for
    DCA than spot accumulation, and the perp-long family is CLOSED.
  * The interesting corollary is then the other side of the same trade: if
    longs pay this much, something is being paid TO the short side.

Run:  python scripts/kt1_funding_drag.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orc import config
from orc.eval.analytic import AnalyticSpec, evaluate
from orc.facts import panel as panel_mod
from orc.kernel.metrics_cf import start_date_profile

CLOSE_FAMILY_THRESHOLD = 0.25       # frozen before results were seen
HORIZON_YEARS = 3
CONTRIBUTION = 100.0


def annualised_funding_stats(p) -> dict:
    fr = p.funding_rate[p.funding_rate != 0.0]
    if fr.size == 0:
        return {"settlements": 0}
    per_year = 365.0 * 3.0                    # 8-hourly settlements
    return {
        "settlements": int(fr.size),
        "mean_rate_per_8h": float(fr.mean()),
        "median_rate_per_8h": float(np.median(fr)),
        "pct_positive": float((fr > 0).mean()),
        "naive_annualised_pct": float(fr.mean() * per_year * 100.0),
        "worst_single_settlement_pct": float(fr.max() * 100.0),
    }


def run_symbol(symbol: str) -> dict | None:
    try:
        p = panel_mod.load(symbol, clock="1h", development_only=True)
    except (FileNotFoundError, ValueError) as exc:
        print(f"  {symbol:10s} unavailable: {exc}")
        return None
    if not p.has_funding():
        print(f"  {symbol:10s} no funding data")
        return None

    stride = p.bars(7)                                   # weekly deposits
    n = int(round(HORIZON_YEARS * 52))
    spec = AnalyticSpec(contribution=CONTRIBUTION, stride_bars=stride,
                        n_contributions=n, hold_bars=0,
                        fee_bps=config.TAKER_FEE_BPS,
                        slippage_bps=config.SLIPPAGE_BPS,
                        exit_fee_bps=config.TAKER_FEE_BPS)

    free = evaluate(p.close, spec)                        # spot-style: no funding
    perp = evaluate(p.close, spec, funding_flow=p.funding_flow)
    if free.get("n_starts", 0) == 0:
        print(f"  {symbol:10s} series too short for a {HORIZON_YEARS}y horizon")
        return None

    invested = CONTRIBUTION * n
    bill_frac = perp["funding_paid"] / invested
    drag = (free["terminal_multiple"] - perp["terminal_multiple"])

    row = {
        "symbol": symbol,
        "bars": len(p),
        "n_starts": perp["n_starts"],
        "invested_usdt": invested,
        "funding": annualised_funding_stats(p),
        "funding_bill_frac_of_invested": start_date_profile(bill_frac),
        "terminal_multiple_spot_style": start_date_profile(free["terminal_multiple"]),
        "terminal_multiple_perp_long": start_date_profile(perp["terminal_multiple"]),
        "multiple_lost_to_funding": start_date_profile(drag),
    }
    med = row["funding_bill_frac_of_invested"]["q50"]
    print(f"  {symbol:10s} median funding bill = {med*100:6.2f} % of capital   "
          f"spot x{row['terminal_multiple_spot_style']['q50']:.3f} -> "
          f"perp x{row['terminal_multiple_perp_long']['q50']:.3f}")
    return row


def main() -> int:
    config.ensure_dirs()
    symbols = panel_mod.available_symbols("1h")
    if not symbols:
        print("no panels built yet; run: python -m orc.facts.build_panel")
        return 2

    print(f"KT-1  perpetual funding drag on a {HORIZON_YEARS}-year weekly DCA")
    print(f"      universe: {len(symbols)} symbols, development data only "
          f"(sealed from {config.HOLDOUT_START})\n")

    rows = [r for s in symbols if (r := run_symbol(s)) is not None]
    if not rows:
        print("\nno symbol produced a result")
        return 2

    medians = np.array([r["funding_bill_frac_of_invested"]["q50"] for r in rows])
    worst = np.array([r["funding_bill_frac_of_invested"]["q95"] for r in rows])
    universe_median = float(np.median(medians))
    verdict = "CLOSE_PERP_LONG_FAMILY" if universe_median > CLOSE_FAMILY_THRESHOLD else "PERP_LONG_SURVIVES"

    report = {
        "kill_test": "KT-1 funding drag",
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "threshold_frozen_before_results": CLOSE_FAMILY_THRESHOLD,
        "horizon_years": HORIZON_YEARS,
        "deposit_interval": "weekly",
        "holdout_start": str(config.HOLDOUT_START),
        "universe_median_funding_bill_frac": universe_median,
        "universe_q95_funding_bill_frac": float(np.median(worst)),
        "verdict": verdict,
        "per_symbol": rows,
    }
    out = config.REPORTS / "KT1_FUNDING_DRAG.json"
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    print("\n" + "=" * 68)
    print(f"universe median funding bill : {universe_median*100:.2f} % of contributed capital")
    print(f"threshold (frozen in advance): {CLOSE_FAMILY_THRESHOLD*100:.0f} %")
    print(f"VERDICT                      : {verdict}")
    print("=" * 68)
    print(f"written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
