"""ORC | Fixed-capital metrics, for Track B.

Section 4 of the constitution rules CAGR, equity drawdown and Sharpe out of
Track A because DCA keeps taking deposits: there is no single starting capital
to divide by, and a "return" over a period mixes what was earned with what was
paid in.  A signal strategy has neither problem.  One capital goes in, an
equity curve comes out, and these are the right questions to ask of it.

They are still not conclusions.  A Sharpe computed on one equity curve over one
history is one experiment no matter how many bars it contains, which is why
section 4 makes the path count come from symbols and non-overlapping blocks.
"""
from __future__ import annotations

import numpy as np

# Frozen before results were seen.  Perpetuals trade every hour of every day,
# so a year is the full calendar, not 252 sessions.
BARS_PER_YEAR = {"1h": 24 * 365, "1m": 60 * 24 * 365}

# A drawdown of exactly zero would make Calmar infinite.  A strategy that never
# drew down over the whole window has not proved it cannot; report the ratio as
# undefined rather than as a triumph.
MIN_DD_FOR_CALMAR = 1e-9


def is_measurable(equity: np.ndarray) -> bool:
    """Is this curve something a ratio can honestly be computed from?

    One guard, used by all four ratios, because each of them had grown its own
    and they did not agree.  `sharpe` was the one that mattered: its bankruptcy
    guard `np.any(equity <= 0.0)` is blind to NaN -- `nan <= 0` is False -- so a
    curve with NaN in it passed, `np.log`/`np.diff` turned that into NaN
    returns, and `r = r[np.isfinite(r)]` then DELETED them and treated the
    survivors as if they were consecutive bars.  The result was a finite,
    plausible, entirely fictional Sharpe for an account whose equity was not a
    number.

    A curve that is not finite everywhere, or that reaches zero, is not a
    measurement.  Saying so once is the fix; deleting the offending bars is what
    produced the fiction.
    """
    equity = np.asarray(equity, dtype=np.float64)
    if equity.size == 0:
        return False
    return bool(np.all(np.isfinite(equity)))


def max_drawdown(equity: np.ndarray) -> float:
    """Deepest peak-to-trough fall, as a fraction of the peak."""
    equity = np.asarray(equity, dtype=np.float64)
    if equity.size == 0:
        return 0.0
    if not is_measurable(equity):
        return float("nan")
    peak = np.maximum.accumulate(equity)
    return float(np.max(1.0 - equity / np.maximum(peak, 1e-12)))


def cagr(equity: np.ndarray, bars_per_year: float) -> float:
    """Compound annual growth rate of the equity curve.

    Defined here precisely because capital is fixed: the denominator is the
    opening equity and it never changes.
    """
    equity = np.asarray(equity, dtype=np.float64)
    if equity.size < 2 or not is_measurable(equity) or equity[0] <= 0:
        return float("nan")
    years = (equity.size - 1) / float(bars_per_year)
    if years <= 0:
        return float("nan")
    ratio = equity[-1] / equity[0]
    if ratio <= 0:                      # wiped out; annualising is meaningless
        return -1.0
    return float(ratio ** (1.0 / years) - 1.0)


def sharpe(equity: np.ndarray, bars_per_year: float, rf: float = 0.0) -> float:
    """Annualised Sharpe of the per-bar log returns.

    Log returns, so a bar that halves and a bar that doubles cancel, and so a
    liquidation does not produce a finite number out of a total loss.
    """
    equity = np.asarray(equity, dtype=np.float64)
    if equity.size < 3:
        return float("nan")
    # A curve that reaches zero has no volatility-adjusted return to report.
    # The clamp turns the wipeout into one enormous log return that sets both
    # the mean and the standard deviation, and they cancel: every destroyed
    # account came out at -sqrt(bars_per_year/n) regardless of how much was
    # lost or when. The same figure for a 10,000 account and a 10,000,000 one
    # is not a measurement.
    if not is_measurable(equity) or np.any(equity <= 0.0):
        return float("nan")
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.diff(np.log(np.maximum(equity, 1e-12)))
    # No isfinite filter here on purpose.  Every value is finite by the guard
    # above, and dropping bars is what let a curve with holes in it be scored as
    # though the surviving bars were consecutive.
    sd = float(np.std(r, ddof=1))
    if r.size < 2 or sd <= 0:
        return float("nan")
    excess = float(np.mean(r)) - rf / bars_per_year
    return float(excess / sd * np.sqrt(bars_per_year))


def calmar(equity: np.ndarray, bars_per_year: float) -> float:
    """CAGR over maximum drawdown."""
    dd = max_drawdown(equity)
    if dd < MIN_DD_FOR_CALMAR:
        return float("nan")
    c = cagr(equity, bars_per_year)
    return float("nan") if not np.isfinite(c) else float(c / dd)


def summary(equity: np.ndarray, clock: str = "1h") -> dict:
    """The four ratios plus the raw pieces they are built from."""
    bpy = BARS_PER_YEAR[clock]
    equity = np.asarray(equity, dtype=np.float64)
    return {
        "cagr": cagr(equity, bpy),
        "max_drawdown": max_drawdown(equity),
        "calmar": calmar(equity, bpy),
        "sharpe": sharpe(equity, bpy),
        "total_return": float(equity[-1] / equity[0] - 1.0) if equity.size and equity[0] > 0 else float("nan"),
        "bars": int(equity.size),
        "years": float((equity.size - 1) / bpy) if equity.size else 0.0,
    }
