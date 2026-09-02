"""ORC | Trial execution.

Routes each configuration to the evaluator that can express it, computes the
cash-flow metrics, and writes one immutable row per trial.

Routing rule: unconditional, unlevered, no path exit -> the closed-form
evaluator, which returns EVERY admissible start date.  Anything else -> the
path simulator on a coarser start grid, because those shapes genuinely require
walking the bars.

The primary objective is the FIFTH PERCENTILE terminal multiple across start
dates, not the mean.  A DCA outcome distribution is strongly right-skewed; the
mean is dominated by the handful of start dates that caught a bull market from
the bottom, which is not a repeatable experience.  The left tail is what an
investor actually risks living through.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

import numpy as np

from orc import config
from orc.eval.analytic import AnalyticSpec, evaluate, lump_sum_reference
from orc.eval.simulate import (SimSpec, gate_below_sma, gate_below_trailing_peak,
                               simulate)
from orc.eval.signal import SignalSpec, run_signals
from orc.eval.signal_rules import build_signals
from orc.facts import panel as panel_mod
from orc.facts.panel import Panel
from orc.kernel import metrics_fc
from orc.kernel.liquidation import tier_table_for
from orc.kernel.metrics_cf import mwrr_equal_interval, start_date_profile
from orc.ledger.trials import Ledger, code_hash
from orc.orchestrator.spec import SignalTrialConfig, Hypothesis, TrialConfig

# Path-dependent variants are simulated from one start per day.  Finer grids buy
# almost nothing: neighbouring start dates share nearly all of their history.
SIM_START_STRIDE_DAYS = 1.0


class UnsupportedConfig(RuntimeError):
    pass


def build_gate(spec: str, p: Panel) -> np.ndarray | None:
    if spec in ("none", "", None):
        return None
    kind, *rest = spec.split(":")
    if kind == "dip":
        drop, lookback_days = float(rest[0]), float(rest[1])
        return gate_below_trailing_peak(p.close, drop, p.bars(lookback_days))
    if kind == "sma":
        return gate_below_sma(p.close, p.bars(float(rest[0])))
    raise UnsupportedConfig(f"unknown gate {spec!r}")


@dataclass
class TrialOutcome:
    cfg: TrialConfig
    evaluator: str
    n_starts: int
    metrics: dict


def _profile(prefix: str, values: np.ndarray) -> dict:
    prof = start_date_profile(values)
    return {f"{prefix}_{k}": v for k, v in prof.items()}


def _span(p: Panel, starts: np.ndarray, horizon: int) -> dict:
    """Calendar span the start dates cover, and how much history each path sees.

    Reported on every trial because it is the honest denominator.  A three-year
    horizon on six years of archive leaves start dates spanning only the
    remaining three, and those paths overlap almost completely -- the effective
    number of independent experiments is a handful, not the millions of start
    offsets the evaluator returns.
    """
    if starts.size == 0:
        return {}
    first, last = p.ts[int(starts.min())], p.ts[int(starts.max())]
    span_days = float((last - first) / np.timedelta64(1, "D"))
    horizon_days = horizon / float(p.bars_per_day)
    return {
        "start_first": str(first)[:10],
        "start_last": str(last)[:10],
        "start_span_days": span_days,
        "horizon_days": horizon_days,
        # overlapping paths are not independent; this is a generous upper bound
        "effective_independent_paths": round(span_days / max(horizon_days, 1.0) + 1.0, 2),
    }


def run_signal_trial(cfg: "SignalTrialConfig", p: Panel | None = None) -> TrialOutcome:
    """Track B: one equity curve per symbol, judged on fixed-capital ratios."""
    p = p or panel_mod.load(cfg.symbol, cfg.clock, development_only=True)
    if not p.has_funding():
        raise UnsupportedConfig("no funding history; a carry rule has nothing to read")

    lookback = p.bars(cfg.lookback_days)
    if lookback < 2 or lookback >= len(p):
        raise UnsupportedConfig(
            f"lookback_exceeds_history ({lookback} bars of {len(p)})")

    entry, exit_ = build_signals(cfg.rule, p, lookback, cfg.enter_rate, cfg.exit_rate)
    spec = SignalSpec(
        capital=cfg.capital, leverage=cfg.leverage,
        fee_bps=cfg.effective_fee_bps, slippage_bps=cfg.effective_slippage_bps,
        stop_loss=cfg.stop_loss, take_profit=cfg.take_profit,
        max_hold_bars=p.bars(cfg.max_hold_days) if cfg.max_hold_days else None)
    r = run_signals(p.close, p.high, p.low, entry, exit_, spec,
                    funding_rate=p.funding_rate, symbol=cfg.symbol)

    if r["n_trades"] == 0:
        raise UnsupportedConfig("no_trades_fired")

    m = metrics_fc.summary(r["equity"], cfg.clock)
    span_days = float((p.ts[-1] - p.ts[0]) / np.timedelta64(1, "D"))
    metrics = {
        **m,
        "n_trades": r["n_trades"],
        "win_rate": r["win_rate"],
        "funding_collected": r["funding_collected"],
        "funding_frac_of_capital": r["funding_collected"] / cfg.capital,
        "n_liquidations": r["n_liquidations"],
        "liquidation_rate": r["n_liquidations"] / r["n_trades"],
        "final_equity": r["final_equity"],
        "start_first": str(p.ts[0])[:10],
        "start_last": str(p.ts[-1])[:10],
        "start_span_days": span_days,
        # One equity curve is one path.  Each trade is a separate decision, so
        # the trade count is the generous upper bound on how many independent
        # experiments are underneath -- generous because they all share one
        # price history and one regime, exactly as Track A's overlapping start
        # offsets do.
        "effective_independent_paths": float(r["n_trades"]),
        "evaluator": "signal",
    }
    return TrialOutcome(cfg, "signal", 1, metrics)


def run_trial(cfg, p: Panel | None = None) -> TrialOutcome:
    """Dispatch on what kind of thing the configuration describes."""
    if isinstance(cfg, SignalTrialConfig):
        return run_signal_trial(cfg, p)
    return run_dca_trial(cfg, p)


def run_dca_trial(cfg: TrialConfig, p: Panel | None = None) -> TrialOutcome:
    p = p or panel_mod.load(cfg.symbol, cfg.clock, development_only=True)
    stride = p.bars(cfg.stride_days)
    hold = p.bars(cfg.hold_days)
    if stride < 1:
        raise UnsupportedConfig("stride rounds to zero bars on this clock")

    horizon = (cfg.n_contributions - 1) * stride + hold
    if horizon >= len(p):
        raise UnsupportedConfig(
            f"horizon_exceeds_history ({horizon} bars needed, {len(p)} available)")

    flow = p.funding_flow if cfg.include_funding else None
    fee, slip = cfg.effective_fee_bps, cfg.effective_slippage_bps
    years_between = cfg.stride_days / 365.0

    if cfg.uses_analytic:
        spec = AnalyticSpec(contribution=cfg.contribution, stride_bars=stride,
                            n_contributions=cfg.n_contributions, hold_bars=hold,
                            fee_bps=fee, slippage_bps=slip, exit_fee_bps=fee)
        res = evaluate(p.close, spec, funding_flow=flow)
        if res.get("n_starts", 0) == 0:
            raise UnsupportedConfig("no_admissible_start_dates")

        tm = res["terminal_multiple"]
        invested = res["invested"]
        # The same funding the DCA is charged. Without it the comparison was
        # a funded schedule against an unfunded one.
        lump = lump_sum_reference(p.close, spec, funding_flow=flow)
        metrics = {
            **_profile("tm", tm),
            # horizon_years, or the IRR is annualised over the time of the last
            # deposit instead of the time the value was measured.  With
            # hold_days set, that is the one metric section 4 calls
            # horizon-robust silently not being so.
            **_profile("mwrr", mwrr_equal_interval(cfg.contribution, cfg.n_contributions,
                                                   years_between, res["terminal_value"],
                                                   horizon_years=horizon / (p.bars_per_day * 365.0))),
            **_profile("funding_frac", res["funding_paid"] / invested),
            "invested_usdt": invested,
            "liquidation_rate": 0.0,
            "vs_lump_sum_q50": float(np.median(tm) - np.median(lump["terminal_multiple"])),
            **_span(p, res["start_idx"], horizon),
            "evaluator": "analytic",
        }
        return TrialOutcome(cfg, "analytic", res["n_starts"], metrics)

    # ---- path-dependent -------------------------------------------------
    sim = SimSpec(contribution=cfg.contribution, stride_bars=stride,
                  n_contributions=cfg.n_contributions, hold_bars=hold,
                  leverage=cfg.leverage, fee_bps=fee, slippage_bps=slip,
                  exit_fee_bps=fee, take_profit=cfg.take_profit,
                  stop_loss=cfg.stop_loss)
    step = max(p.bars(SIM_START_STRIDE_DAYS), 1)
    starts = np.arange(0, len(p) - horizon - 1, step, dtype=np.int64)
    if starts.size == 0:
        raise UnsupportedConfig("no_admissible_start_dates")

    out = simulate(p.close, p.low, starts, sim,
                   funding_rate=p.funding_rate if cfg.include_funding else None,
                   gate=build_gate(cfg.gate, p),
                   table=tier_table_for(cfg.symbol))
    invested = out["invested"]
    metrics = {
        **_profile("tm", out["terminal_multiple"]),
        **_profile("mwrr", mwrr_equal_interval(cfg.contribution, cfg.n_contributions,
                                               years_between, out["terminal_equity"],
                                               horizon_years=horizon / (p.bars_per_day * 365.0))),
        **_profile("dd", out["max_dd_total"]),
        **_profile("funding_frac", out["funding_paid"] / np.maximum(invested, 1e-9)),
        "invested_usdt": float(np.median(invested)),
        "liquidation_rate": out["liquidation_rate"],
        "frac_time_in_loss_q50": float(np.median(out["frac_time_in_loss"])),
        **_span(p, starts, horizon),
        "evaluator": "simulate",
    }
    return TrialOutcome(cfg, "simulate", out["n_starts"], metrics)


# --------------------------------------------------------------------------
def run_hypothesis(
    h: Hypothesis,
    ledger: Ledger | None = None,
    run_id: str | None = None,
    verbose: bool = True,
) -> dict:
    """Execute every configuration a hypothesis enumerates, and record all of them.

    Failures are recorded as skips rather than dropped: a grid point that could
    not be evaluated is information about the grid, and silently shrinking the
    denominator is how a search flatters itself.
    """
    h.verify()
    own_ledger = ledger is None
    ledger = ledger or Ledger()
    run_id = run_id or uuid.uuid4().hex[:12]
    ch = code_hash()

    configs = h.expand()
    panels: dict[str, Panel] = {}
    done = new = skipped = 0
    failures: dict[str, int] = {}

    if verbose:
        print(f"{h.hypothesis_id}  {h.family}  {len(configs)} configurations")

    for cfg in configs:
        if cfg.symbol not in panels:
            try:
                panels[cfg.symbol] = panel_mod.load(cfg.symbol, cfg.clock,
                                                    development_only=True)
            except (FileNotFoundError, ValueError) as exc:
                panels[cfg.symbol] = None                    # type: ignore[assignment]
                failures[f"panel:{type(exc).__name__}"] = failures.get(
                    f"panel:{type(exc).__name__}", 0) + 1
        p = panels[cfg.symbol]
        if p is None:
            skipped += 1
            continue
        try:
            outcome = run_trial(cfg, p)
        except (UnsupportedConfig, ValueError) as exc:
            skipped += 1
            key = str(exc).split("(")[0].strip()[:48]
            failures[key] = failures.get(key, 0) + 1
            continue

        _, was_new = ledger.record(
            run_id=run_id, family=h.family, symbol=cfg.symbol,
            evaluator=outcome.evaluator, cfg=cfg.to_dict(),
            metrics=outcome.metrics, n_starts=outcome.n_starts,
            panel_hash=p.panel_hash, holdout_state=p.holdout_state,
            hypothesis_id=h.hypothesis_id, code=ch)
        done += 1
        new += int(was_new)
        if verbose and done % 200 == 0:
            print(f"  {done}/{len(configs)} evaluated", flush=True)

    summary = {
        "hypothesis_id": h.hypothesis_id,
        "family": h.family,
        "run_id": run_id,
        "configurations": len(configs),
        "evaluated": done,
        "new_trials": new,
        "skipped": skipped,
        "skip_reasons": failures,
        "ledger_total_trials": ledger.total_trials(),
    }
    if verbose:
        print(f"  evaluated {done}, new {new}, skipped {skipped}")
        print(f"  ledger now holds {summary['ledger_total_trials']} trials")
    if own_ledger:
        ledger.close()
    return summary
