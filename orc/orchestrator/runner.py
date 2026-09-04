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
from orc.eval.signal_rules import FUNDING_RULES, build_signals
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


def build_gate(spec: str, p: Panel, close: np.ndarray | None = None) -> np.ndarray | None:
    """The gate, read off `close` -- the panel's by default, a synthetic path
    when the search test needs the gate to fire on the series it is testing."""
    if spec in ("none", "", None):
        return None
    close = p.close if close is None else close
    kind, *rest = spec.split(":")
    if kind == "dip":
        drop, lookback_days = float(rest[0]), float(rest[1])
        return gate_below_trailing_peak(close, drop, p.bars(lookback_days))
    if kind == "sma":
        return gate_below_sma(close, p.bars(float(rest[0])))
    raise UnsupportedConfig(f"unknown gate {spec!r}")


def tm_q05_on_path(cfg: TrialConfig, p: Panel, close: np.ndarray) -> float:
    """One Track A cell's 5th-percentile terminal multiple on a given path.

    The search test's null has to re-run the shape it is a null for, and it was
    not: it built an AnalyticSpec from contribution, stride, n_contributions and
    hold and called the closed form, silently dropping `gate`, `leverage`,
    `take_profit`, `stop_loss` and `include_funding`.  For H0007 -- a gated,
    funded DCA -- the null was therefore an unconditional unfunded DCA, which
    carries neither the mechanism nor the width of the search whose significance
    it was being used to judge.  Routing through cfg.uses_analytic, the same
    decision a real trial makes, is the only way the two stay the same shape.

    The bootstrap has no wick, so the simulator is handed close as its low.
    That understates liquidation and stop-outs in the null, which RAISES the
    bar the observed cell has to clear, so it errs against the finding.

    Returns nan for a cell this path cannot express.
    """
    stride, hold = p.bars(cfg.stride_days), p.bars(cfg.hold_days)
    if stride < 1:
        return float("nan")
    horizon = (cfg.n_contributions - 1) * stride + hold
    if horizon >= close.size:
        return float("nan")
    fee, slip = cfg.effective_fee_bps, cfg.effective_slippage_bps

    if cfg.uses_analytic:
        spec = AnalyticSpec(contribution=cfg.contribution, stride_bars=stride,
                            n_contributions=cfg.n_contributions, hold_bars=hold,
                            fee_bps=fee, slippage_bps=slip, exit_fee_bps=fee)
        res = evaluate(close, spec,
                       funding_flow=p.funding_flow if cfg.include_funding else None)
        if not res.get("n_starts", 0):
            return float("nan")
        return float(np.quantile(res["terminal_multiple"], 0.05))

    sim = SimSpec(contribution=cfg.contribution, stride_bars=stride,
                  n_contributions=cfg.n_contributions, hold_bars=hold,
                  leverage=cfg.leverage, fee_bps=fee, slippage_bps=slip,
                  exit_fee_bps=fee, take_profit=cfg.take_profit,
                  stop_loss=cfg.stop_loss)
    step = max(p.bars(SIM_START_STRIDE_DAYS), 1)
    starts = np.arange(0, close.size - horizon - 1, step, dtype=np.int64)
    if starts.size == 0:
        return float("nan")
    out = simulate(close, close, starts, sim,
                   funding_rate=p.funding_rate if cfg.include_funding else None,
                   gate=build_gate(cfg.gate, p, close),
                   table=tier_table_for(cfg.symbol))
    tm = out["terminal_multiple"]
    return float(np.nanquantile(tm, 0.05)) if tm.size else float("nan")


def mwrr_q05_on_path(cfg: TrialConfig, p: Panel, close: np.ndarray) -> float:
    """One Track A cell's 5th-percentile annualised IRR on a given path.

    The statistic the Track A search test needs, and the one it was not using.
    `write_report` passes `surfaces[sym]["best_value"]`, which `ranking_metric`
    ranks on `mwrr_q05` -- an annualised money-weighted RETURN, around 0.14 for
    a good cell -- and the null scored every synthetic path with
    `tm_q05_on_path`, a terminal MULTIPLE, around 3.6 for the same cell.  The
    p-value was therefore the answer to "how often does a bootstrap multiple
    exceed an observed rate of return", which is a question about units.  It
    could only come back extreme in one direction, so the test that exists to
    price the width of the search was not pricing anything.

    Same shape as tm_q05_on_path in every other respect, including handing the
    simulator `close` as its low: the bootstrap has no wick, and understating
    liquidation in the null raises the bar the observed cell must clear.
    """
    stride, hold = p.bars(cfg.stride_days), p.bars(cfg.hold_days)
    if stride < 1:
        return float("nan")
    horizon = (cfg.n_contributions - 1) * stride + hold
    if horizon >= close.size:
        return float("nan")
    fee, slip = cfg.effective_fee_bps, cfg.effective_slippage_bps
    years_between = cfg.stride_days / 365.0

    if cfg.uses_analytic:
        spec = AnalyticSpec(contribution=cfg.contribution, stride_bars=stride,
                            n_contributions=cfg.n_contributions, hold_bars=hold,
                            fee_bps=fee, slippage_bps=slip, exit_fee_bps=fee)
        res = evaluate(close, spec,
                       funding_flow=p.funding_flow if cfg.include_funding else None)
        if not res.get("n_starts", 0):
            return float("nan")
        irr = mwrr_equal_interval(
            cfg.contribution, cfg.n_contributions, years_between,
            res["terminal_value"],
            horizon_years=horizon / (p.bars_per_day * 365.0))
        return float(np.nanquantile(irr, 0.05)) if np.size(irr) else float("nan")

    sim = SimSpec(contribution=cfg.contribution, stride_bars=stride,
                  n_contributions=cfg.n_contributions, hold_bars=hold,
                  leverage=cfg.leverage, fee_bps=fee, slippage_bps=slip,
                  exit_fee_bps=fee, take_profit=cfg.take_profit,
                  stop_loss=cfg.stop_loss)
    step = max(p.bars(SIM_START_STRIDE_DAYS), 1)
    starts = np.arange(0, close.size - horizon - 1, step, dtype=np.int64)
    if starts.size == 0:
        return float("nan")
    out = simulate(close, close, starts, sim,
                   funding_rate=p.funding_rate if cfg.include_funding else None,
                   gate=build_gate(cfg.gate, p, close),
                   table=tier_table_for(cfg.symbol))
    # The deposits that actually landed and the time the path actually lived,
    # exactly as run_trial prices a real cell.  Anything else would put the
    # null and the observation on different definitions of the same metric,
    # which is the defect this function exists to close.
    invested = out["invested"]
    n_real = np.maximum(np.round(invested / max(cfg.contribution, 1e-12)), 1.0)
    years_real = np.maximum(out["exit_bar"], 0.0) / (p.bars_per_day * 365.0)
    irr = mwrr_equal_interval(cfg.contribution, n_real, years_between,
                              out["terminal_equity"], horizon_years=years_real)
    return float(np.nanquantile(irr, 0.05)) if np.size(irr) else float("nan")


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
        # Both kinds of rule are refused, for two different reasons.  A carry
        # rule has nothing to read.  A price rule reads price and would run
        # perfectly well -- on a position whose funding bill the evaluator
        # would charge at zero, which is not a cheaper version of the trade but
        # a different one: KT-1 measured that bill at 36 % of capital over
        # three years on the paying side.
        why = ("a carry rule has nothing to read" if cfg.rule in FUNDING_RULES
               else "a position would be charged no funding at all, which is "
                    "not a conservative error")
        raise UnsupportedConfig(f"no funding history; {why}")

    lookback = p.bars(cfg.lookback_days)
    if lookback < 2 or lookback >= len(p):
        raise UnsupportedConfig(
            f"lookback_exceeds_history ({lookback} bars of {len(p)})")

    entry, exit_ = build_signals(cfg, p)
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
        # Both legs, never the coupon alone.  'collected 36 % of capital in
        # funding' is the number this family exists to find and it was being
        # written next to nothing that could contradict it -- including on
        # accounts that ended at zero.  The price leg is what says whether the
        # coupon was income or a rebate on a losing short.
        "funding_collected": r["funding_collected"],
        "funding_frac_of_capital": r["funding_collected"] / cfg.capital,
        "gross_collected": r["gross_collected"],
        "gross_frac_of_capital": r["gross_collected"] / cfg.capital,
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

    # The deposits that actually landed, and the time the path actually lived.
    # This branch priced every path with the REGISTERED n_contributions and the
    # NOMINAL horizon, so a programme that take-profits in week 5 was charged
    # for 151 deposits it never made: an ensemble whose true annualised IRR is
    # +415 % was recorded at the bracket floor, -0.9999. No number in the ledger
    # carries it -- of 1332 Track A rows, none has take_profit or stop_loss set,
    # and the other early exit is liquidation, which ends at terminal_equity 0
    # where the IRR is -100 % however many deposits were made. So this is a
    # latent defect being closed before the first family that would trip it,
    # which was H0008, killed on this ground before registration.
    n_real = np.maximum(np.round(invested / max(cfg.contribution, 1e-12)), 1.0)
    # exit_bar, not bars_lived: `lived` is an inclusive COUNT of bars
    # (exit_bar + 1, the denominator for frac_time_in_loss), while this
    # needs ELAPSED time from the first deposit to the measurement, which
    # is exit_bar. Using the count put an extra bar on every horizon and
    # moved 186 stored values in the fifth decimal -- small, and still a
    # silent rewrite of numbers this change was supposed to leave alone.
    years_real = np.maximum(out["exit_bar"], 0.0) / (p.bars_per_day * 365.0)
    metrics = {
        **_profile("tm", out["terminal_multiple"]),
        **_profile("mwrr", mwrr_equal_interval(cfg.contribution, n_real,
                                               years_between, out["terminal_equity"],
                                               horizon_years=years_real)),
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
    # Keyed on (symbol, clock), not on symbol.  A panel IS a symbol at a clock:
    # `fixed: {"clock": "1h"}` is the common case, but a grid is free to put
    # clock on an axis, and then every configuration after the first was scored
    # against whichever clock happened to come first -- minute rules measured on
    # hourly bars, or the reverse, with panel_hash recording the wrong panel and
    # nothing downstream able to notice.
    panels: dict[tuple[str, str], Panel] = {}
    done = new = skipped = 0
    failures: dict[str, int] = {}

    if verbose:
        print(f"{h.hypothesis_id}  {h.family}  {len(configs)} configurations")

    for cfg in configs:
        key = (cfg.symbol, cfg.clock)
        if key not in panels:
            try:
                panels[key] = panel_mod.load(cfg.symbol, cfg.clock,
                                             development_only=True)
            except (FileNotFoundError, ValueError) as exc:
                panels[key] = None                           # type: ignore[assignment]
                failures[f"panel:{type(exc).__name__}"] = failures.get(
                    f"panel:{type(exc).__name__}", 0) + 1
        p = panels[key]
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
