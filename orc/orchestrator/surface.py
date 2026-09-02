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
from orc.orchestrator.spec import ordinal_axis, Hypothesis

PRIMARY_METRIC = "tm_q05"          # 5th percentile terminal multiple

# CSCV splits rows into blocks and asks whether the in-sample winner survives
# out of sample. That only means something if the blocks cover different price
# history. On Track A the rows are start offsets and each carries a horizon:
# H0001/BTCUSDT had 105 days of offsets against horizons up to 4650, so every
# column covered essentially the same window, the split was not a split, and
# PBO came back as exactly 0.000 labelled SELECTION_INFORMATIVE -- the
# strongest endorsement the scale has, from a comparison that measured nothing.
# The offsets must span at least as long as the horizon before the answer is
# reportable. Frozen before any family cleared.
MIN_SPAN_OVER_HORIZON = 1.0


# --------------------------------------------------------------------------
def ranking_metric(h: Hypothesis) -> str:
    """What decides which cell of a grid is called the best one.

    A different question from what the family is judged against.  Section 4
    says tm_q05 is a multiple of contributed capital, grows with the horizon and
    may not be compared between cells that hold for different lengths of time --
    and the surface ranked cells by exactly that, so the argmax was decided
    mostly by which cell held longest and plateau_score measured holding time
    rather than parameter sensitivity.  The annualised IRR is the comparison
    section 4 names as surviving a horizon change, and its fifth percentile
    keeps the left tail this project decides on.

    Hypothesis.primary_metric is untouched and still reported: the kill
    conditions were pre-registered against it, and a threshold is a per-cell
    test rather than a ranking.

    This lives here and not on the Hypothesis because spec.py is inside the
    ledger's code hash: a reporting choice defined there would give every trial
    in the project a new identity and add 1210 rows to N without a single
    recorded number changing.
    """
    return "calmar" if h.track == "B" else "mwrr_q05"


def drawdown_for(cfg, p=None) -> float | None:
    """Max drawdown on invested capital for one Track A cell.

    Section 4 asks for this figure and the closed-form evaluator cannot produce
    it: drawdown is peak-to-trough along an equity curve, and a curve is exactly
    what an O(1)-per-start closed form does not build.  So the cell is measured
    once on the simulator, which does.  One call per reported cell, not per grid
    point -- the ranking still comes from the fast evaluator.
    """
    from orc.eval.simulate import SimSpec, simulate
    from orc.kernel.liquidation import tier_table_for
    from orc.orchestrator.runner import SIM_START_STRIDE_DAYS, build_gate

    p = p or panel_mod.load(cfg.symbol, cfg.clock, development_only=True)
    stride, hold = p.bars(cfg.stride_days), p.bars(cfg.hold_days)
    horizon = (cfg.n_contributions - 1) * stride + hold
    if stride < 1 or horizon >= len(p):
        return None
    step = max(p.bars(SIM_START_STRIDE_DAYS), 1)
    starts = np.arange(0, len(p) - horizon - 1, step, dtype=np.int64)
    if starts.size == 0:
        return None
    sim = SimSpec(contribution=cfg.contribution, stride_bars=stride,
                  n_contributions=cfg.n_contributions, hold_bars=hold,
                  leverage=cfg.leverage, fee_bps=cfg.effective_fee_bps,
                  slippage_bps=cfg.effective_slippage_bps,
                  exit_fee_bps=cfg.effective_fee_bps,
                  take_profit=cfg.take_profit, stop_loss=cfg.stop_loss)
    out = simulate(p.close, p.low, starts, sim,
                   funding_rate=p.funding_rate if cfg.include_funding else None,
                   gate=build_gate(cfg.gate, p), table=tier_table_for(cfg.symbol))
    return float(np.median(out["max_dd_total"]))


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
            "SELECT symbol, config_json, metrics_json, n_starts, code_hash, "
            "panel_hash FROM trials WHERE hypothesis_id=? ORDER BY trial_id",
            (h.hypothesis_id,)).fetchall()

    values: dict[str, dict[tuple, float]] = {}
    # How much evidence each cell actually rests on, carried alongside the
    # metric so the winning cell can be reported with its denominator.
    context: dict[str, dict[tuple, dict]] = {}
    # Which revision produced the number a cell reports used to be decided by
    # whatever order SQLite returned: 1210 (hypothesis, symbol, config) groups
    # hold more than one row, and on H0002 alone 613 of them disagree on calmar
    # between revisions. One surface could therefore mix cells computed by
    # different kernels on different panels, and plateau_score would compare
    # them as though they were neighbours in the same experiment. Take the
    # newest row per cell explicitly -- trial_id is monotonic, so the last write
    # wins by construction rather than by luck -- and record what the surface
    # was actually assembled from.
    provenance: dict[str, dict] = {}
    for sym, cfg_json, met_json, n_starts, code_h, panel_h in rows:
        cfg = json.loads(cfg_json)
        met = json.loads(met_json)
        if metric not in met:
            continue
        key = tuple(cfg[a] for a in axes)
        values.setdefault(sym, {})[key] = float(met[metric])
        pv = provenance.setdefault(sym, {"code": set(), "panel": set()})
        pv["code"].add(code_h)
        pv["panel"].add(panel_h)
        context.setdefault(sym, {})[key] = {
            "n_starts": int(n_starts),
            # Absent on trials from code revisions predating the span figure.
            "effective_independent_paths": met.get("effective_independent_paths"),
            # tm_q05 is a multiple of contributed capital, so it grows with the
            # horizon and cannot be compared across cells that hold for
            # different lengths of time.  The annualised money-weighted return
            # can, and the horizon says which comparison is even being made.
            "mwrr_q05": met.get("mwrr_q05"),
            # Drawdown on invested capital, section 4's replacement for equity
            # drawdown. Only the simulator produces it: the closed form has no
            # equity curve, and a peak-to-trough figure cannot be recovered from
            # terminal values. Absent means unmeasured, and the report says so.
            "dd_q50": met.get("dd_q50"),
            "dd_q95": met.get("dd_q95"),
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
    # An axis is ordinal if "one step away" means a small change along it. That
    # needs three levels and an order. A None among otherwise numeric values is
    # "off", which sorts nowhere, so the numeric levels are still ordinal but
    # the None column is not a neighbour of anything -- previously the whole
    # axis was declared categorical and never perturbed, which on H0002 left
    # one axis of five carrying the entire shape verdict.
    ordinal = [ordinal_axis(h.grid[a]) for a in axes]

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
            # More than one of either means this surface was assembled across
            # revisions. The cells are individually real and comparing them to
            # each other is not, which is exactly what the shape diagnostic does.
            "assembled_from": {
                "code_revisions": len(provenance.get(sym, {}).get("code", ())),
                "panel_revisions": len(provenance.get(sym, {}).get("panel", ())),
            },
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
            "dd_q50_best": ctx.get("dd_q50"),
            "sharpe_best": ctx.get("sharpe"),
            "n_trades_best": ctx.get("n_trades"),
            "n_liquidations_best": ctx.get("n_liquidations"),
            "funding_frac_best": ctx.get("funding_frac_of_capital"),
        }
    return out


# --------------------------------------------------------------------------
def pbo_for_hypothesis(h: Hypothesis, symbol: str, n_blocks: int = 10,
                       best_config: dict | None = None) -> dict:
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
    horizons: list[int] = []
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
        horizons.append((cfg.n_contributions - 1) * stride + hold)
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

    # Horizons differ across the grid, and a terminal multiple grows with the
    # horizon (section 4), so the columns are not comparable as they stand and
    # the in-sample winner would be chosen by holding longest. Keep only the
    # configurations sharing the most common horizon.
    from collections import Counter
    # Which group, though?  The modal one, with ties broken by insertion order,
    # is not necessarily the group the reported best cell is in -- on H0001 all
    # nine horizons tied at two and the winner was stride_days 1.0, while every
    # symbol's best cell was stride_days 30.0.  verdict.py then applied that PBO
    # to a cell it had not measured.  Follow the cell that will be judged.
    best_i = None
    if best_config is not None:
        for i, lab in enumerate(labels):
            if all(lab.get(k) == v for k, v in best_config.items()):
                best_i = i
                break
    common_h = (horizons[best_i] if best_i is not None
                else Counter(horizons).most_common(1)[0][0])
    keep = [i for i, hz in enumerate(horizons) if hz == common_h]
    if len(keep) < 2:
        return {"symbol": symbol,
                "status": "fewer than two configurations share a horizon"}
    per_config = [per_config[i] for i in keep]
    labels = [labels[i] for i in keep]

    common = per_config[0][0]
    for s, _ in per_config[1:]:
        common = np.intersect1d(common, s, assume_unique=True)
    if common.size < n_blocks * 10:
        return {"symbol": symbol, "status": f"only {common.size} common start dates"}

    span_over_horizon = common.size / max(common_h, 1)
    if span_over_horizon < MIN_SPAN_OVER_HORIZON:
        return {"symbol": symbol,
                "status": f"start offsets span {common.size} bars against a "
                          f"{common_h}-bar horizon; the blocks would be the same "
                          f"price history and the split would not be a split"}

    mat = np.column_stack([
        vals[np.searchsorted(starts, common)] for starts, vals in per_config])

    res = cscv_pbo(mat, n_blocks=n_blocks)
    return {
        "symbol": symbol,
        "status": "ok",
        "horizon_bars": int(common_h),
        "span_over_horizon": round(float(span_over_horizon), 3),
        "n_configs": res.n_configs,
        "n_common_starts": int(common.size),
        "n_splits": res.n_splits,
        "pbo": res.pbo,
        "median_logit": res.median_logit,
        "degraded_fraction": res.degraded_fraction,
        "verdict": res.verdict(),
        "best_config_overall": labels[int(np.argmax(mat.mean(axis=0)))],
        # verdict.py applies this to the surface's best cell. If that cell was
        # not among the columns, the number is a measurement of other cells and
        # must not be read as clearing this one.
        "covers_reported_best": bool(best_i is not None),
    }


# --------------------------------------------------------------------------
def pbo_for_signal_hypothesis(h: Hypothesis, symbol: str, n_blocks: int = 10,
                              best_config: dict | None = None) -> dict:
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
        # There is no horizon subset on this track -- every configuration that
        # traded is a column -- but a configuration whose lookback exceeds the
        # panel is dropped, so coverage is still checked rather than assumed.
        "covers_reported_best": bool(
            best_config is None
            or any(all(lab.get(k) == v for k, v in best_config.items())
                   for lab in labels)),
    }


# --------------------------------------------------------------------------
def search_test_for(h: Hypothesis, symbol: str, observed_best: float) -> dict:
    """Is the best cell better than the best a search of this width finds in noise?

    The grid is re-run in full on each synthetic history, so the null carries
    the same search the real number came from. Anything cheaper understates the
    null and manufactures significance.
    """
    from orc.orchestrator.search_test import best_of_g

    p = panel_mod.load(symbol, "1h", development_only=True)
    configs = [c for c in h.expand() if c.symbol == symbol]
    if len(configs) < 2:
        return {"status": "fewer than two configurations"}

    if h.track == "B":
        from orc.eval.signal import SignalSpec, run_signals
        from orc.eval.signal_rules import build_signals
        from orc.kernel import metrics_fc

        def score(close):
            hi, lo = close * 1.0, close * 1.0        # a bootstrap has no wick
            best = -np.inf
            for cfg in configs:
                lb = p.bars(cfg.lookback_days)
                if lb < 2 or lb >= close.size:
                    continue
                entry, exit_ = build_signals(cfg.rule, p, lb, cfg.enter_rate, cfg.exit_rate)
                spec = SignalSpec(capital=cfg.capital, leverage=cfg.leverage,
                                  fee_bps=cfg.effective_fee_bps,
                                  slippage_bps=cfg.effective_slippage_bps,
                                  stop_loss=cfg.stop_loss, take_profit=cfg.take_profit,
                                  max_hold_bars=p.bars(cfg.max_hold_days) if cfg.max_hold_days else None)
                r = run_signals(close, hi, lo, entry, exit_, spec,
                                funding_rate=p.funding_rate, symbol=symbol)
                if r["n_trades"]:
                    v = metrics_fc.calmar(r["equity"], metrics_fc.BARS_PER_YEAR["1h"])
                    if np.isfinite(v):
                        best = max(best, v)
            return best
    else:
        def score(close):
            best = -np.inf
            for cfg in configs:
                stride, hold = p.bars(cfg.stride_days), p.bars(cfg.hold_days)
                if stride < 1 or (cfg.n_contributions - 1) * stride + hold >= close.size:
                    continue
                spec = AnalyticSpec(contribution=cfg.contribution, stride_bars=stride,
                                    n_contributions=cfg.n_contributions, hold_bars=hold,
                                    fee_bps=cfg.effective_fee_bps,
                                    slippage_bps=cfg.effective_slippage_bps,
                                    exit_fee_bps=cfg.effective_fee_bps)
                res = evaluate(close, spec)
                if res.get("n_starts", 0):
                    best = max(best, float(np.quantile(res["terminal_multiple"], 0.05)))
            return best

    return best_of_g(observed_best, score, p, len(configs))


# --------------------------------------------------------------------------
def write_report(h: Hypothesis, metric: str | None = None,
                 pbo_symbols: list[str] | None = None) -> dict:
    # Ranked on the metric that survives a horizon change, judged on the one the
    # kill conditions were pre-registered against. Section 4 asks for both.
    metric = metric or ranking_metric(h)
    surfaces = surface_from_ledger(h, metric)

    # The two numbers a reader actually wants, for the cell being reported.
    # Return is annualised so cells of different horizons can be read against
    # each other; drawdown is the section 4 definition for the track.  A Track A
    # cell scored by the closed form has no drawdown in the ledger, so it is
    # measured once here on the simulator rather than left blank.
    for sym, srf in surfaces.items():

        if h.track == "B":
            srf["headline"] = {
                "return_pa": srf.get("cagr_best"),
                "mdd": srf.get("max_drawdown_best"),
                "mdd_kind": "equity",
            }
            continue
        mdd = srf.get("dd_q50_best")
        if mdd is None:
            try:
                from orc.orchestrator.spec import TrialConfig
                params = dict(h.fixed)
                params.update(srf["best_config"])
                params.pop("symbol", None)
                mdd = drawdown_for(TrialConfig(symbol=sym, **params))
            except Exception:                                      # noqa: BLE001
                mdd = None
        srf["headline"] = {
            "return_pa": srf.get("mwrr_q05_best"),
            "return_pa_median": srf.get("mwrr_q50_best"),
            "mdd": mdd,
            "mdd_kind": "invested",
        }
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
            pbo[sym] = run_pbo(h, sym, best_config=surfaces[sym]["best_config"])
        except (ValueError, FileNotFoundError) as exc:
            pbo[sym] = {"symbol": sym, "status": str(exc)}

    # The question N exists to answer, on the cells anyone would be tempted by.
    search = {}
    for sym in ranked[:2]:
        try:
            search[sym] = search_test_for(h, sym, surfaces[sym]["best_value"])
        except Exception as exc:                                   # noqa: BLE001
            search[sym] = {"status": f"{type(exc).__name__}: {exc}"}

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
        "search_test": search,
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
