"""ORC | Response surfaces and the overfitting check.

Two questions are asked of every completed hypothesis, and both must be answered
before any configuration is described as a finding:

  SHAPE   Is the best cell a plateau or a spike?  A mechanism that is real
          degrades gently as parameters move; one that is fitted falls off a
          cliff.  This is why the grid is enumerated rather than sampled --
          the surface is the evidence, not its maximum.

  PBO     If the sample is split every balanced way into in-sample and
          out-of-sample halves, how often does the in-sample winner land below
          the out-of-sample median?  At 0.5 the selection carries no
          information at all.

PBO needs a performance-per-time-slice matrix, which the ledger does not store,
so the grid is re-evaluated here keeping per-start-date outcomes.  That is
affordable precisely because the closed-form evaluator exists.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np

from orc import config
from orc.eval.analytic import AnalyticSpec, evaluate
from orc.facts import panel as panel_mod
from orc.kernel.inference import cscv_pbo, plateau_score
from orc.ledger.trials import Ledger
from orc.orchestrator.spec import Hypothesis

PRIMARY_METRIC = "tm_q05"          # 5th percentile terminal multiple


# --------------------------------------------------------------------------
def surface_from_ledger(h: Hypothesis, metric: str | None = None) -> dict:
    """Assemble the metric over the hypothesis grid, per symbol.

    The metric follows the track: a Track B row has no tm_q05 to read, and
    silently skipping every row of a whole track would report an empty
    family as if it had simply not run.
    """
    metric = metric or h.primary_metric
    axes = sorted(h.grid)
    with Ledger() as led:
        rows = led.conn.execute(
            "SELECT symbol, config_json, metrics_json, n_starts "
            "FROM trials WHERE hypothesis_id=?",
            (h.hypothesis_id,)).fetchall()

    values: dict[str, dict[tuple, float]] = {}
    # How much evidence each cell actually rests on, carried alongside the
    # metric so the winning cell can be reported with its denominator.
    context: dict[str, dict[tuple, dict]] = {}
    for sym, cfg_json, met_json, n_starts in rows:
        cfg = json.loads(cfg_json)
        met = json.loads(met_json)
        if metric not in met:
            continue
        key = tuple(cfg[a] for a in axes)
        values.setdefault(sym, {})[key] = float(met[metric])
        context.setdefault(sym, {})[key] = {
            "n_starts": int(n_starts),
            # Absent on trials from code revisions predating the span figure.
            "effective_independent_paths": met.get("effective_independent_paths"),
            # tm_q05 is a multiple of contributed capital, so it grows with the
            # horizon and cannot be compared across cells that hold for
            # different lengths of time.  The annualised money-weighted return
            # can, and the horizon says which comparison is even being made.
            "mwrr_q05": met.get("mwrr_q05"),
            "mwrr_q50": met.get("mwrr_q50"),
            "horizon_days": met.get("horizon_days"),
            # Track B judges the same cell on fixed-capital ratios; carrying
            # them here is what lets one report show both tracks without the
            # reader having to open the ledger to see what a number means.
            "cagr": met.get("cagr"),
            "max_drawdown": met.get("max_drawdown"),
            "sharpe": met.get("sharpe"),
            "n_trades": met.get("n_trades"),
            "n_liquidations": met.get("n_liquidations"),
            "funding_frac_of_capital": met.get("funding_frac_of_capital"),
        }

    # An axis is ordinal only if its values are numeric and it has enough
    # levels for 'one step away' to mean a small change.
    ordinal = [len(h.grid[a]) > 2 and all(isinstance(v, (int, float))
               and not isinstance(v, bool) for v in h.grid[a]) for a in axes]

    out: dict[str, dict] = {}
    for sym, cells in values.items():
        shape = [len(h.grid[a]) for a in axes]
        grid = np.full(shape, np.nan)
        for key, v in cells.items():
            idx = tuple(h.grid[a].index(key[i]) for i, a in enumerate(axes))
            grid[idx] = v
        if np.all(np.isnan(grid)):
            continue
        best_flat = int(np.nanargmax(grid))
        best_idx = np.unravel_index(best_flat, grid.shape)
        best_key = tuple(h.grid[a][best_idx[i]] for i, a in enumerate(axes))
        ctx = context.get(sym, {}).get(best_key, {})
        out[sym] = {
            "axes": axes,
            "axis_values": {a: h.grid[a] for a in axes},
            "grid": grid.tolist(),
            "cells_filled": int(np.sum(~np.isnan(grid))),
            "cells_total": int(grid.size),
            "best_value": float(grid[best_idx]),
            "best_config": {a: h.grid[a][best_idx[i]] for i, a in enumerate(axes)},
            "shape_diagnostic": plateau_score(grid, ordinal),
            # The denominator behind the winning cell.  n_starts counts start
            # offsets, which overlap almost completely; independent_paths is the
            # generous upper bound on how many genuinely separate experiments
            # those offsets amount to.  Reporting the first without the second
            # is how a handful of experiments gets mistaken for tens of
            # thousands.
            "n_starts_best": ctx.get("n_starts"),
            "independent_paths_best": ctx.get("effective_independent_paths"),
            "mwrr_q05_best": ctx.get("mwrr_q05"),
            "mwrr_q50_best": ctx.get("mwrr_q50"),
            "horizon_days_best": ctx.get("horizon_days"),
            "cagr_best": ctx.get("cagr"),
            "max_drawdown_best": ctx.get("max_drawdown"),
            "sharpe_best": ctx.get("sharpe"),
            "n_trades_best": ctx.get("n_trades"),
            "n_liquidations_best": ctx.get("n_liquidations"),
            "funding_frac_best": ctx.get("funding_frac_of_capital"),
        }
    return out


# --------------------------------------------------------------------------
def pbo_for_hypothesis(h: Hypothesis, symbol: str, n_blocks: int = 10) -> dict:
    """CSCV probability of backtest overfitting, over the hypothesis grid.

    Only the closed-form-evaluable configurations are used: they share an exact,
    dense start-date grid, which is what makes the columns comparable.
    """
    p = panel_mod.load(symbol, "1h", development_only=True)
    configs = [c for c in h.expand() if c.symbol == symbol and c.uses_analytic]
    if len(configs) < 2:
        return {"symbol": symbol, "status": "fewer than two analytic configurations"}

    per_config: list[tuple[np.ndarray, np.ndarray]] = []
    labels: list[dict] = []
    for cfg in configs:
        stride, hold = p.bars(cfg.stride_days), p.bars(cfg.hold_days)
        if stride < 1 or (cfg.n_contributions - 1) * stride + hold >= len(p):
            continue
        spec = AnalyticSpec(contribution=cfg.contribution, stride_bars=stride,
                            n_contributions=cfg.n_contributions, hold_bars=hold,
                            fee_bps=cfg.effective_fee_bps,
                            slippage_bps=cfg.effective_slippage_bps,
                            exit_fee_bps=cfg.effective_fee_bps)
        res = evaluate(p.close, spec,
                       funding_flow=p.funding_flow if cfg.include_funding else None)
        if res.get("n_starts", 0) == 0:
            continue
        per_config.append((res["start_idx"], res["terminal_multiple"]))
        labels.append({k: v for k, v in cfg.to_dict().items() if k in h.grid})

    if len(per_config) < 2:
        return {"symbol": symbol, "status": "no comparable configurations"}

    # Columns must be evaluated on the SAME start dates or the split is not a
    # split.  Different horizons admit different starts, so intersect them.
    common = per_config[0][0]
    for s, _ in per_config[1:]:
        common = np.intersect1d(common, s, assume_unique=True)
    if common.size < n_blocks * 10:
        return {"symbol": symbol, "status": f"only {common.size} common start dates"}

    mat = np.column_stack([
        vals[np.searchsorted(starts, common)] for starts, vals in per_config])

    res = cscv_pbo(mat, n_blocks=n_blocks)
    return {
        "symbol": symbol,
        "status": "ok",
        "n_configs": res.n_configs,
        "n_common_starts": int(common.size),
        "n_splits": res.n_splits,
        "pbo": res.pbo,
        "median_logit": res.median_logit,
        "degraded_fraction": res.degraded_fraction,
        "verdict": res.verdict(),
        "best_config_overall": labels[int(np.argmax(mat.mean(axis=0)))],
    }


# --------------------------------------------------------------------------
def pbo_for_signal_hypothesis(h: Hypothesis, symbol: str, n_blocks: int = 10) -> dict:
    """CSCV for Track B, where the columns are equity curves rather than start dates.

    Track A gets its rows from start dates: every configuration is scored on the
    same calendar of beginnings, so the rows line up.  A signal rule has no such
    ensemble -- it runs once and produces one curve -- and the obvious move, one
    row per configuration, gives CSCV nothing to split.

    The rows are bars instead.  Every configuration on a symbol walks the same
    panel, so its per-bar log return is directly comparable to every other's at
    that bar, which is exactly the "same slicing for every column" that
    cscv_pbo requires.  Splitting bars into blocks then asks the question CSCV
    is for: choose the best rule on half the history, and see where it lands on
    the half that did not choose it.

    Configurations that liquidate stay in.  Dropping them would quietly raise
    the out-of-sample median that the in-sample winner is measured against, and
    flattering the winner is the precise failure PBO exists to catch.  The count
    is reported so a reader knows what the median is made of.
    """
    from orc.eval.signal import SignalSpec, run_signals
    from orc.eval.signal_rules import build_signals

    p = panel_mod.load(symbol, "1h", development_only=True)
    configs = [c for c in h.expand() if c.symbol == symbol]
    if len(configs) < 2:
        return {"symbol": symbol, "status": "fewer than two configurations"}

    curves, labels, liquidated = [], [], 0
    for cfg in configs:
        lookback = p.bars(cfg.lookback_days)
        if lookback < 2 or lookback >= len(p):
            continue
        entry, exit_ = build_signals(cfg.rule, p, lookback, cfg.enter_rate, cfg.exit_rate)
        spec = SignalSpec(
            capital=cfg.capital, leverage=cfg.leverage,
            fee_bps=cfg.effective_fee_bps, slippage_bps=cfg.effective_slippage_bps,
            stop_loss=cfg.stop_loss, take_profit=cfg.take_profit,
            max_hold_bars=p.bars(cfg.max_hold_days) if cfg.max_hold_days else None)
        r = run_signals(p.close, p.high, p.low, entry, exit_, spec,
                        funding_rate=p.funding_rate, symbol=symbol)
        if r["n_trades"] == 0:
            continue
        liquidated += bool(r["n_liquidations"])
        curves.append(r["equity"])
        labels.append({k: v for k, v in cfg.to_dict().items() if k in h.grid})

    if len(curves) < 2:
        return {"symbol": symbol, "status": "fewer than two configurations traded"}

    eq = np.column_stack(curves)
    with np.errstate(divide="ignore", invalid="ignore"):
        mat = np.diff(np.log(np.maximum(eq, 1e-12)), axis=0)
    mat[~np.isfinite(mat)] = 0.0

    res = cscv_pbo(mat, n_blocks=n_blocks)
    return {
        "symbol": symbol,
        "status": "ok",
        "n_configs": res.n_configs,
        "n_bars": int(mat.shape[0]),
        "n_splits": res.n_splits,
        "pbo": res.pbo,
        "median_logit": res.median_logit,
        "degraded_fraction": res.degraded_fraction,
        "verdict": res.verdict(),
        "n_liquidating_configs": liquidated,
        "best_config_overall": labels[int(np.argmax(mat.mean(axis=0)))],
    }


# --------------------------------------------------------------------------
def write_report(h: Hypothesis, metric: str | None = None,
                 pbo_symbols: list[str] | None = None) -> dict:
    metric = metric or h.primary_metric
    surfaces = surface_from_ledger(h, metric)
    pbo = {}
    run_pbo = pbo_for_signal_hypothesis if h.track == "B" else pbo_for_hypothesis
    # The overfitting check has to run on the cells someone would actually be
    # tempted by.  Taking whatever three symbols the dict happened to hold left
    # the top-ranked cell -- the only one anyone reads -- with no PBO at all,
    # which is the one place the check was needed.
    ranked = [s for s, _ in sorted(surfaces.items(),
                                   key=lambda kv: -kv[1]["best_value"])]
    for sym in (pbo_symbols or ranked[:3]):
        try:
            pbo[sym] = run_pbo(h, sym)
        except (ValueError, FileNotFoundError) as exc:
            pbo[sym] = {"symbol": sym, "status": str(exc)}

    with Ledger() as led:
        ledger_total = led.total_trials()
        family_total = led.trials_in_family(h.family)

    report = {
        "hypothesis_id": h.hypothesis_id,
        "family": h.family,
        "track": h.track,
        "claim": h.claim,
        "kill_condition": h.kill_condition,
        "prereg_hash": h.prereg_hash,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "metric": metric,
        "holdout_start": str(config.HOLDOUT_START),
        "trials_in_family": family_total,
        "trials_in_project": ledger_total,
        "surfaces": surfaces,
        "pbo": pbo,
    }
    out = config.REPORTS / f"{h.hypothesis_id}_SURFACE.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    report["_path"] = str(out)
    return report


def summarise(report: dict) -> str:
    lines = [
        f"{report['hypothesis_id']}  {report['family']}",
        f"  metric {report['metric']}   trials in family {report['trials_in_family']}"
        f"   project total {report['trials_in_project']}",
    ]
    for sym, s in sorted(report["surfaces"].items(),
                         key=lambda kv: -kv[1]["best_value"]):
        shape = s["shape_diagnostic"].get("shape", "?")
        ratio = s["shape_diagnostic"].get("plateau_ratio", float("nan"))
        paths = s.get("independent_paths_best")
        paths_txt = "n/a" if paths is None else f"{paths:g}"
        lines.append(f"  {sym:10s} best {s['best_value']:+.4f}  {shape:8s} "
                     f"(neighbour/peak {ratio:.3f})  indep paths {paths_txt}  "
                     f"{s['best_config']}")
    for sym, r in report["pbo"].items():
        if r.get("status") == "ok":
            lines.append(f"  PBO {sym:10s} {r['pbo']:.3f}  {r['verdict']}"
                         f"  ({r['n_configs']} configs, {r['n_splits']} splits)")
        else:
            lines.append(f"  PBO {sym:10s} -- {r.get('status')}")
    return "\n".join(lines)
