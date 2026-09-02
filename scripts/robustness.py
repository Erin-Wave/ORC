"""ORC | Run the robustness gate over a family's best cells.

The cycle reports what each cell returned.  This asks whether that number
survives the three cheapest ways of being wrong: the costs being an estimate,
the cell having been chosen with knowledge of the whole window, and six years
of crypto being mostly one direction.

Reads the registry and the ledger, writes reports/ROBUSTNESS.json, and prints a
line per cell.  It never opens the holdout: every split here is inside the
development period, which research may already see in full.

Usage:  python scripts/robustness.py [H0002 ...]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orc import config                                            # noqa: E402
from orc.facts import panel as panel_mod                          # noqa: E402
from orc.kernel import metrics_fc                                 # noqa: E402
from orc.orchestrator import robustness                           # noqa: E402
from orc.orchestrator.runner import run_trial                     # noqa: E402
from orc.orchestrator.spec import SignalTrialConfig, load_registry  # noqa: E402
from orc.orchestrator.verdict import survivors                    # noqa: E402

# A regime label needs long enough to mean "the market went up", not "the last
# few hours did".  Frozen at 30 days before any result was seen.
REGIME_WINDOW_DAYS = 30


def _score(cfg, panel, metric: str) -> float:
    try:
        return float(run_trial(cfg, panel).metrics.get(metric, float("nan")))
    except Exception:                                              # noqa: BLE001
        return float("nan")


def _sliced(panel, lo: int, hi: int):
    """A view of the panel over [lo, hi), keeping every array in step."""
    from dataclasses import replace
    return replace(panel,
                   ts=panel.ts[lo:hi], open=panel.open[lo:hi], high=panel.high[lo:hi],
                   low=panel.low[lo:hi], close=panel.close[lo:hi],
                   volume=panel.volume[lo:hi], funding_rate=panel.funding_rate[lo:hi])


def _tm_q05_over_mask(panel, cfg, mask: np.ndarray) -> float:
    """Track A: the 5th-percentile terminal multiple over start dates in a regime.

    DCA has no equity curve to slice, but it does have one outcome per start
    date, so the split is on where each path began. That asks the same question
    the Track B split asks: of the money committed while the market was doing
    this, what happened to the unlucky twentieth of it?
    """
    from orc.eval.analytic import AnalyticSpec, evaluate

    stride, hold = panel.bars(cfg.stride_days), panel.bars(cfg.hold_days)
    if stride < 1 or (cfg.n_contributions - 1) * stride + hold >= len(panel):
        return float("nan")
    spec = AnalyticSpec(contribution=cfg.contribution, stride_bars=stride,
                        n_contributions=cfg.n_contributions, hold_bars=hold,
                        fee_bps=cfg.effective_fee_bps,
                        slippage_bps=cfg.effective_slippage_bps,
                        exit_fee_bps=cfg.effective_fee_bps)
    res = evaluate(panel.close, spec,
                   funding_flow=panel.funding_flow if cfg.include_funding else None)
    idx = res.get("start_idx")
    if idx is None or len(idx) == 0:
        return float("nan")
    sel = mask[idx]
    if sel.sum() < 100:
        return float("nan")
    return float(np.quantile(res["terminal_multiple"][sel], 0.05))


def _annualised_over_mask(panel, cfg, mask: np.ndarray) -> float:
    """Annualised return counting only the bars the mask selects.

    The position is not re-run per regime -- a path strategy cannot be cut into
    pieces and still be the same strategy.  The equity curve is produced once
    and its per-bar log returns are summed over the selected bars only, which
    asks the honest question: while the market was doing this, was the rule
    making money or losing it?
    """
    try:
        eq = _equity(cfg, panel)
    except Exception:                                              # noqa: BLE001
        return float("nan")
    if eq is None or eq.size < 3:
        return float("nan")
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.diff(np.log(np.maximum(eq, 1e-12)))
    sel = mask[1:eq.size][:r.size]
    r = r[:sel.size][np.isfinite(r[:sel.size]) & sel]
    if r.size < 2:
        return float("nan")
    bpy = metrics_fc.BARS_PER_YEAR[cfg.clock]
    return float(np.expm1(r.sum() / r.size * bpy))


def _equity(cfg, panel) -> np.ndarray | None:
    from orc.eval.signal import SignalSpec, run_signals
    from orc.eval.signal_rules import build_signals
    if not isinstance(cfg, SignalTrialConfig):
        return None
    lookback = panel.bars(cfg.lookback_days)
    entry, exit_ = build_signals(cfg.rule, panel, lookback, cfg.enter_rate, cfg.exit_rate)
    spec = SignalSpec(capital=cfg.capital, leverage=cfg.leverage,
                      fee_bps=cfg.effective_fee_bps,
                      slippage_bps=cfg.effective_slippage_bps,
                      stop_loss=cfg.stop_loss, take_profit=cfg.take_profit,
                      max_hold_bars=panel.bars(cfg.max_hold_days) if cfg.max_hold_days else None)
    return run_signals(panel.close, panel.high, panel.low, entry, exit_, spec,
                       funding_rate=panel.funding_rate, symbol=cfg.symbol)["equity"]


def _execution_check(h, cfg) -> dict:
    """Does the hourly answer survive the minute bars underneath it?

    Both tracks fill on a bar's close, so both carry the bias: Track B in a few
    fills, Track A spread over every scheduled deposit.  Exempting Track A
    would have left it permanently unmeasured and therefore permanently
    uncertifiable, which is a hole dressed up as caution.

    Reported as unmeasured, not failed, wherever the minute panel is absent --
    which is every cloud run, because 9.5 GB never goes into the bundle. That
    is deliberate rather than a limitation: the worker can rank and reject on
    its own, but it cannot certify a candidate, because the data that would
    settle the question is only on the machine that built it.
    """
    if not panel_mod.panel_path(cfg.symbol, "1m").exists():
        return {"check": "execution", "passed": None,
                "reason": "no minute panel here; certification has to happen locally"}
    try:
        import execution_realism
        r = execution_realism.compare(cfg)
    except Exception as exc:                                       # noqa: BLE001
        return {"check": "execution", "passed": None,
                "reason": f"{type(exc).__name__}: {exc}"}
    return {
        "check": "execution",
        "hourly_return": r["hourly"]["total_return"],
        "minute_return": r["minute"]["total_return"],
        "relative_drift": r["relative_drift"],
        "sign_agrees": r["sign_agrees"],
        "passed": r["passed"],
    }


def gate_one(h, symbol: str, best_config: dict) -> dict:
    """Every check, for one hypothesis's best cell on one symbol."""
    metric = h.primary_metric
    panel = panel_mod.load(symbol, "1h", development_only=True)
    cls = SignalTrialConfig if h.track == "B" else type(h.expand()[0])
    cfg = cls(symbol=symbol, **{**h.fixed, **best_config})

    checks = [robustness.cost_stress(lambda c, p: _score(c, p, metric), cfg, panel)]

    try:
        cells = [c for c in h.expand() if c.symbol == symbol]
        checks.append(robustness.walk_forward(
            lambda c, p, lo, hi: _score(c, _sliced(p, lo, hi), metric), cells, panel))
    except ValueError as exc:
        checks.append({"check": "walk_forward", "passed": False, "reason": str(exc)})

    # Track A is scored on a terminal multiple, where 1.0 is break-even, so the
    # regime check subtracts it: the sign then means the same thing on both
    # tracks and one rule can read both.
    if h.track == "B":
        scorer = lambda c, p, m: _annualised_over_mask(p, c, m)          # noqa: E731
    else:
        scorer = lambda c, p, m: _tm_q05_over_mask(p, c, m) - 1.0        # noqa: E731
    checks.append(robustness.regime_consistency(
        scorer, cfg, panel, panel.bars(REGIME_WINDOW_DAYS)))
    checks.append(_execution_check(h, cfg))

    out = robustness.verdict(checks)
    out.update({"hypothesis_id": h.hypothesis_id, "symbol": symbol,
                "metric": metric, "config": best_config})
    return out


def main(argv: list[str]) -> int:
    wanted = set(argv) or None
    results = []
    for h in load_registry():
        if wanted and h.hypothesis_id not in wanted:
            continue
        rep_path = config.REPORTS / f"{h.hypothesis_id}_SURFACE.json"
        if not rep_path.exists():
            continue
        rep = json.loads(rep_path.read_text(encoding="utf-8"))

        # The gate is expensive and only meaningful on cells that got this far,
        # so it runs on whatever cleared shape, paths and PBO -- and, when
        # nothing did, on the single best cell so the report still says why.
        cells = survivors(rep)
        if not cells:
            best = max(rep["surfaces"].items(), key=lambda kv: kv[1]["best_value"])
            cells = [best]
            note = "nothing cleared; gating the best cell for the record"
        else:
            note = f"{len(cells)} cell(s) cleared and are being gated"
        print(f"\n{h.hypothesis_id}  {h.family}  ({note})")

        for sym, s in cells:
            r = gate_one(h, sym, s["best_config"])
            results.append(r)
            if r["passed"]:
                mark = "PASS"
            else:
                bits = []
                if r["failed"]:
                    bits.append("FAIL: " + ", ".join(r["failed"]))
                if r["unmeasured"]:
                    bits.append("UNMEASURED: " + ", ".join(r["unmeasured"]))
                mark = "  ".join(bits)
            print(f"  {sym:10s} {mark}")
            for c in r["checks"]:
                if c["check"] == "cost":
                    print(f"      cost x{c['multiplier']:g}   {c['base']:+.4f} -> {c['stressed']:+.4f}")
                elif c["check"] == "walk_forward":
                    if "reason" in c:
                        print(f"      walk        {c['reason']}")
                    else:
                        print(f"      walk        in {c['in_sample']:+.4f}  out {c['out_of_sample']:+.4f}")
                elif c["check"] == "regime":
                    if "reason" in c:
                        print(f"      regime      {c['reason']}")
                    else:
                        print(f"      regime      rising {c['rising']:+.2%}  falling {c['falling']:+.2%}")
                else:
                    if "reason" in c:
                        print(f"      execution   {c['reason']}")
                    else:
                        print(f"      execution   1h {c['hourly_return']:+.2%} -> "
                              f"1m {c['minute_return']:+.2%}  drift {c['relative_drift']:.1%}")

    (config.REPORTS / "ROBUSTNESS.json").write_text(
        json.dumps({"results": results}, indent=2, default=str), encoding="utf-8")
    passed = sum(1 for r in results if r["passed"])
    print(f"\n{passed}/{len(results)} cell(s) passed the gate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
