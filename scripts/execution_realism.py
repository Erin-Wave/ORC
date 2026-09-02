"""ORC | Re-run a cell on minute bars and see what the hourly bar was hiding.

Every Track B result so far rests on an hourly panel, and an hourly bar is a
summary that throws away the order things happened in.  Two assumptions in the
evaluator exist only because of that:

  adverse first   When a stop and a target both fall inside one hourly bar, the
                  evaluator takes the stop, because the bar cannot say which
                  came first.  Minute bars can, so this run says how often that
                  assumption cost something that did not actually happen -- and
                  how often it was too generous, which matters more.

  one fill        A signal read at hour i is filled at hour i+1's close, up to
                  an hour after the rule fired.  On minute bars the same rule
                  fills within a minute of firing, and the difference between
                  the two is the part of the return that was waiting-time.

Neither is a small detail for a rule that holds for days: the hourly answer can
be optimistic or pessimistic and there is no way to know which from inside it.

This is the last gate, and it only makes sense on a cell that has already
passed the others.  Minute panels stay on this machine -- they are 9.5 GB and
never reach the cloud bundle -- so this runs locally by design.

Usage:  python scripts/execution_realism.py H0002 BTCUSDT
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orc import config                                            # noqa: E402
from orc.eval.signal import SignalSpec, run_signals               # noqa: E402
from orc.eval.signal_rules import build_signals                   # noqa: E402
from orc.facts import panel as panel_mod                          # noqa: E402
from orc.kernel import metrics_fc                                 # noqa: E402
from orc.orchestrator.spec import SignalTrialConfig, load_registry  # noqa: E402

# How far the minute answer may drift from the hourly one before the hourly
# answer stops being evidence.  Frozen before any candidate existed: a tenth of
# the return is the most a change of clock may explain away.
MAX_RELATIVE_DRIFT = 0.10


def run_on(cfg: SignalTrialConfig, clock: str) -> dict:
    p = panel_mod.load(cfg.symbol, clock, development_only=True)
    lookback = p.bars(cfg.lookback_days)
    entry, exit_ = build_signals(cfg.rule, p, lookback, cfg.enter_rate, cfg.exit_rate)
    spec = SignalSpec(capital=cfg.capital, leverage=cfg.leverage,
                      fee_bps=cfg.effective_fee_bps,
                      slippage_bps=cfg.effective_slippage_bps,
                      stop_loss=cfg.stop_loss, take_profit=cfg.take_profit,
                      max_hold_bars=p.bars(cfg.max_hold_days) if cfg.max_hold_days else None)
    r = run_signals(p.close, p.high, p.low, entry, exit_, spec,
                    funding_rate=p.funding_rate, symbol=cfg.symbol)
    m = metrics_fc.summary(r["equity"], clock)
    return {"clock": clock, "bars": len(p), **m,
            "n_trades": r["n_trades"], "n_liquidations": r["n_liquidations"],
            "funding_collected": r["funding_collected"],
            "final_equity": r["final_equity"],
            "exit_reasons": {k: sum(1 for t in r["trades"] if t["reason"] == k)
                             for k in ("signal", "stop", "take_profit", "liquidation")}}


def compare(cfg: SignalTrialConfig) -> dict:
    hourly = run_on(cfg, "1h")
    minute = run_on(cfg, "1m")
    base = abs(hourly["total_return"])
    drift = abs(minute["total_return"] - hourly["total_return"]) / max(base, 1e-9)
    return {
        "symbol": cfg.symbol,
        "config": cfg.to_dict(),
        "hourly": hourly,
        "minute": minute,
        "relative_drift": drift,
        # A sign change means the two clocks disagree about whether the rule
        # makes money, which is not drift -- it is the hourly answer being
        # wrong.
        "sign_agrees": (hourly["total_return"] > 0) == (minute["total_return"] > 0),
        "passed": drift <= MAX_RELATIVE_DRIFT
                  and (hourly["total_return"] > 0) == (minute["total_return"] > 0),
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[-1])
        return 2
    hid, symbol = argv
    h = next((x for x in load_registry() if x.hypothesis_id == hid), None)
    if h is None:
        print(f"no such hypothesis: {hid}")
        return 2
    if h.track != "B":
        print(f"{hid} is track {h.track}; this gate is for signal families")
        return 2

    rep = json.loads((config.REPORTS / f"{hid}_SURFACE.json").read_text(encoding="utf-8"))
    if symbol not in rep["surfaces"]:
        print(f"{symbol} has no surface in {hid}")
        return 2
    best = rep["surfaces"][symbol]["best_config"]
    cfg = SignalTrialConfig(symbol=symbol, **{**h.fixed, **best})

    print(f"{hid} {symbol}  {best}")
    r = compare(cfg)
    for side in ("hourly", "minute"):
        d = r[side]
        print(f"  {side:7s} bars {d['bars']:>9,}  return {d['total_return']:+8.2%}  "
              f"CAGR {d['cagr']:+7.2%}  MDD {d['max_drawdown']:6.2%}  "
              f"trades {d['n_trades']:4d}  liq {d['n_liquidations']:3d}")
        print(f"          exits {d['exit_reasons']}")
    print(f"  drift {r['relative_drift']:.1%}  sign agrees {r['sign_agrees']}  "
          f"-> {'PASS' if r['passed'] else 'FAIL'}")

    out = config.REPORTS / "EXECUTION_REALISM.json"
    prev = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {"results": []}
    prev["results"] = [x for x in prev["results"]
                       if not (x["symbol"] == symbol and x.get("hypothesis_id") == hid)]
    prev["results"].append({"hypothesis_id": hid, **r})
    out.write_text(json.dumps(prev, indent=2, default=str), encoding="utf-8")
    return 0 if r["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
