"""ORC | Cash-flow-aware metrics.

DCA takes external contributions, so fixed-capital metrics are wrong here:

  * CAGR has no well-defined denominator once capital keeps arriving.
  * Drawdown measured against account equity is flattered by later
    contributions, which refill the account exactly when it is deepest under.

Everything below is therefore stated against *invested capital*.
Time axis is axis 0; every function accepts an ensemble of start dates on axis 1.
"""
from __future__ import annotations

import numpy as np

EPS = 1e-12


# --------------------------------------------------------------------------
# Money-weighted return
# --------------------------------------------------------------------------
def mwrr_equal_interval(
    contribution: float,
    n_contributions: int,
    years_between: float,
    terminal_value: np.ndarray,
    horizon_years: float | None = None,
    lo: float = -0.9999,
    hi: float = 1000.0,
    iters: int = 90,
) -> np.ndarray:
    """Annualised money-weighted return (IRR) for equal, equally spaced deposits.

    Closed-form NPV via the geometric series, so the whole start-date ensemble
    is solved with O(1) work per path and a vectorised bisection:

        NPV(r) = V*(1+r)^-T  -  C * (1 - q^n)/(1 - q),   q = (1+r)^-h

    NPV is decreasing in r whenever T >= every deposit time, which holds by
    construction, so bisection is exact rather than merely convergent.
    """
    V = np.asarray(terminal_value, dtype=np.float64)
    h = float(years_between)
    n = int(n_contributions)
    T = float(horizon_years) if horizon_years is not None else h * (n - 1)
    T = max(T, h * (n - 1))

    def npv(r: np.ndarray) -> np.ndarray:
        base = 1.0 + r
        q = base ** (-h)
        # (1 - q^n)/(1 - q), continuous at q == 1
        near_one = np.abs(q - 1.0) < 1e-12
        denom = np.where(near_one, 1.0, 1.0 - q)
        series = np.where(near_one, float(n), (1.0 - q ** n) / denom)
        return V * base ** (-T) - contribution * series

    a = np.full(V.shape, lo, dtype=np.float64)
    b = np.full(V.shape, hi, dtype=np.float64)
    fa = npv(a)
    for _ in range(iters):
        m = 0.5 * (a + b)
        fm = npv(m)
        go_right = np.sign(fm) == np.sign(fa)
        a = np.where(go_right, m, a)
        fa = np.where(go_right, fm, fa)
        b = np.where(go_right, b, m)
    r = 0.5 * (a + b)
    # A total wipeout has no interior root; report -100 % rather than the bracket.
    return np.where(V <= EPS, -1.0, r)


def mwrr_irregular(cashflows: np.ndarray, times_years: np.ndarray,
                   lo: float = -0.9999, hi: float = 1000.0,
                   iters: int = 200) -> float:
    """IRR for arbitrary signed cash flows.  Reference implementation; the
    equal-interval solver above is checked against this in the test suite."""
    cf = np.asarray(cashflows, dtype=np.float64)
    t = np.asarray(times_years, dtype=np.float64)

    def npv(r: float) -> float:
        return float(np.sum(cf * (1.0 + r) ** (-t)))

    a, b = lo, hi
    fa = npv(a)
    if np.sign(fa) == np.sign(npv(b)):
        return float("nan")
    for _ in range(iters):
        m = 0.5 * (a + b)
        if np.sign(npv(m)) == np.sign(fa):
            a, fa = m, npv(m)
        else:
            b = m
    return 0.5 * (a + b)


# --------------------------------------------------------------------------
# Drawdown against invested capital
# --------------------------------------------------------------------------
def drawdown_on_invested(equity: np.ndarray, contributed: np.ndarray) -> dict:
    """Drawdown of net profit, expressed against capital actually put in.

    Two denominators are reported because they answer different questions:

      running  -- against capital invested *so far*.  This is what the
                  investor actually feels at that moment.
      total    -- against total capital eventually invested.  Comparable
                  across configurations with different deposit counts.
    """
    equity = np.asarray(equity, dtype=np.float64)
    contributed = np.asarray(contributed, dtype=np.float64)
    if contributed.ndim < equity.ndim:
        contributed = contributed.reshape(contributed.shape + (1,) * (equity.ndim - contributed.ndim))

    pnl = equity - contributed
    peak = np.maximum.accumulate(pnl, axis=0)
    dd_abs = peak - pnl

    total_invested = np.max(contributed, axis=0)
    dd_running = dd_abs / np.maximum(contributed, 1.0)
    dd_total = dd_abs / np.maximum(total_invested, EPS)

    return {
        "max_dd_abs": np.max(dd_abs, axis=0),
        "max_dd_running": np.max(dd_running, axis=0),
        "max_dd_total": np.max(dd_total, axis=0),
        "frac_time_in_loss": np.mean(pnl < 0.0, axis=0),
        "frac_time_below_peak": np.mean(pnl < peak - EPS, axis=0),
    }


def terminal_multiple(terminal_value: np.ndarray, total_invested: float | np.ndarray) -> np.ndarray:
    """Terminal wealth per unit of capital contributed."""
    return np.asarray(terminal_value, dtype=np.float64) / np.maximum(
        np.asarray(total_invested, dtype=np.float64), EPS)


# --------------------------------------------------------------------------
# Start-date distribution -- the primary object of DCA research
# --------------------------------------------------------------------------
START_QUANTILES = (0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99)


def start_date_profile(values: np.ndarray, quantiles=START_QUANTILES) -> dict:
    """Summarise an outcome across every start date.

    The mean is reported but must not be used for judgement: DCA outcomes are
    strongly right-skewed and the decision lives in the left tail.
    """
    v = np.asarray(values, dtype=np.float64).ravel()
    v = v[np.isfinite(v)]
    if v.size == 0:
        return {"n": 0}
    qs = np.quantile(v, quantiles)
    out = {f"q{int(q * 100):02d}": float(x) for q, x in zip(quantiles, qs)}
    out.update(n=int(v.size), mean=float(v.mean()), std=float(v.std(ddof=1)) if v.size > 1 else 0.0,
               worst=float(v.min()), best=float(v.max()))
    return out
