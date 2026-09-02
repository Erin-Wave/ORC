"""ORC | KILL TEST 3 -- how large is the survivorship bias?

The local archive holds the symbols that were worth archiving.  The exchange
archive holds every symbol that ever traded, including the ones that went to
zero and were delisted.  If a DCA result on an alt basket is computed over the
first set and reported as if it were the second, the number is fiction.

This test measures the size of the lie rather than assuming it is small:

  1. count the gap between the ever-listed universe and what is on disk,
  2. pull a sample of DELISTED symbols straight from the archive,
  3. run the identical DCA configuration on survivors and on the delisted,
  4. report the difference.

Decision rule, frozen before results were seen:

  * If the median terminal multiple of delisted symbols is more than 0.20 below
    that of survivors, then no alt-basket hypothesis may be run on the local
    universe alone.  The delisted symbols must be materialised first.

Run:  python scripts/kt3_survivorship.py [n_delisted_to_sample]
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
from orc.facts import fetch_vision as fv
from orc.facts import panel as panel_mod
from orc.kernel.metrics_cf import start_date_profile

MAX_ACCEPTABLE_GAP = 0.20
# Most delisted symbols never lived long enough for a two-year DCA, so the
# usable sample is far smaller than the sample drawn.  Below this count the
# comparison is not evidence and the test must say so instead of ruling.
MIN_USABLE_PER_GROUP = 10
SAMPLE_DEFAULT = 25
CONTRIBUTION = 100.0
STRIDE_DAYS = 7.0
N_CONTRIB = 104                      # two years of weekly deposits
SEED = 20260902


def dca_outcome(symbol: str) -> dict | None:
    try:
        p = panel_mod.load(symbol, "1h", development_only=True, with_funding=False)
    except (FileNotFoundError, ValueError):
        return None
    stride = p.bars(STRIDE_DAYS)
    if (N_CONTRIB - 1) * stride >= len(p):
        return None
    spec = AnalyticSpec(contribution=CONTRIBUTION, stride_bars=stride,
                        n_contributions=N_CONTRIB,
                        fee_bps=config.TAKER_FEE_BPS,
                        slippage_bps=config.SLIPPAGE_BPS,
                        exit_fee_bps=config.TAKER_FEE_BPS)
    res = evaluate(p.close, spec)
    if res.get("n_starts", 0) == 0:
        return None
    prof = start_date_profile(res["terminal_multiple"])
    return {"symbol": symbol, "bars": len(p), "n_starts": res["n_starts"],
            "tm_q05": prof["q05"], "tm_q50": prof["q50"], "tm_q95": prof["q95"]}


def main() -> int:
    config.ensure_dirs()
    n_sample = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else SAMPLE_DEFAULT

    print("KT-3  survivorship bias in the alt universe\n")

    ever = fv.list_symbols_ever("klines")
    on_disk = set(panel_mod.available_symbols("1h")) | {
        p.stem for p in (config.FACTS / "panel_1m").glob("*.parquet")}
    local_archive = {p.name for p in config.RAW_1M.iterdir() if p.is_dir()} \
        if config.RAW_1M.exists() else set()

    missing = sorted(set(ever) - local_archive)
    print(f"  symbols that ever traded : {len(ever)}")
    print(f"  in the local 1m archive  : {len(local_archive)}")
    print(f"  never archived locally   : {len(missing)}  "
          f"({len(missing)/max(len(ever),1)*100:.1f} % of the universe)")

    live: set[str] = set()
    r = fv._get("https://fapi.binance.com/fapi/v1/exchangeInfo", tries=3, timeout=30)
    if r is not None:
        live = {s["symbol"] for s in r.json().get("symbols", [])
                if s.get("status") == "TRADING"}
    delisted = sorted(set(ever) - live) if live else []
    print(f"  currently listed         : {len(live)}")
    print(f"  delisted (ever - live)   : {len(delisted)}\n")

    rng = np.random.default_rng(SEED)
    pool = [s for s in delisted if s.endswith("USDT")]
    sample = sorted(rng.choice(pool, size=min(n_sample, len(pool)), replace=False).tolist()) \
        if pool else []

    print(f"  materialising {len(sample)} delisted symbols from the archive")
    fv.fetch_panels_for(sample, "1h")

    print("\n  running the identical DCA on both groups")
    survivors = [o for s in sorted(on_disk & live)[:60] if (o := dca_outcome(s))]
    dead = [o for s in sample if (o := dca_outcome(s))]

    if not survivors or not dead:
        print("\n  not enough symbols in one of the groups to compare")
        return 2

    s_med = float(np.median([o["tm_q50"] for o in survivors]))
    d_med = float(np.median([o["tm_q50"] for o in dead]))
    s_q05 = float(np.median([o["tm_q05"] for o in survivors]))
    d_q05 = float(np.median([o["tm_q05"] for o in dead]))
    gap = s_med - d_med

    print(f"\n  survivors ({len(survivors):3d} symbols)  median terminal multiple "
          f"{s_med:.3f}   left tail {s_q05:.3f}")
    print(f"  delisted  ({len(dead):3d} symbols)  median terminal multiple "
          f"{d_med:.3f}   left tail {d_q05:.3f}")

    if len(dead) < MIN_USABLE_PER_GROUP or len(survivors) < MIN_USABLE_PER_GROUP:
        verdict = "INCONCLUSIVE_INSUFFICIENT_SAMPLE"
    elif gap > MAX_ACCEPTABLE_GAP:
        verdict = "ALT_BASKETS_REQUIRE_DELISTED_SYMBOLS"
    else:
        verdict = "LOCAL_UNIVERSE_ACCEPTABLE"
    report = {
        "kill_test": "KT-3 survivorship",
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "threshold_frozen_before_results": MAX_ACCEPTABLE_GAP,
        "symbols_ever": len(ever),
        "symbols_in_local_archive": len(local_archive),
        "symbols_never_archived_locally": len(missing),
        "symbols_currently_listed": len(live),
        "symbols_delisted": len(delisted),
        "sampled_delisted": sample,
        "survivor_median_terminal_multiple": s_med,
        "delisted_median_terminal_multiple": d_med,
        "gap": gap,
        "usable_survivors": len(survivors),
        "usable_delisted": len(dead),
        "min_usable_per_group": MIN_USABLE_PER_GROUP,
        "verdict": verdict,
        "survivors": survivors,
        "delisted_sample": dead,
    }
    out = config.REPORTS / "KT3_SURVIVORSHIP.json"
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    print("\n" + "=" * 68)
    print(f"gap in median terminal multiple : {gap:+.3f}")
    print(f"threshold (frozen in advance)   : {MAX_ACCEPTABLE_GAP:.2f}")
    print(f"usable survivors / delisted     : {len(survivors)} / {len(dead)} "
          f"(need {MIN_USABLE_PER_GROUP} each)")
    print(f"VERDICT                         : {verdict}")
    if verdict == "INCONCLUSIVE_INSUFFICIENT_SAMPLE":
        print("  -> re-run with a larger sample, e.g. "
              "python scripts/kt3_survivorship.py 120")
    print("=" * 68)
    print(f"written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
