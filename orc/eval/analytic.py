"""ORC | Analytic evaluator -- every start date, in O(N).

For UNCONDITIONAL fixed-interval DCA the terminal outcome is a linear functional
of the price path, so the whole start-date ensemble collapses to prefix sums.

    units(s) = C' * SUM_{j<n} 1/P[s + jk]

Split 1/P into its k residue classes, take one cumulative sum per class, and a
single lagged difference yields the result for EVERY start offset s at once.
Cost is O(N), not O(N * starts).

Perpetual funding submits to the same treatment.  Funding paid by a long is

    SUM_t Q(t) P[t] f[t]
      = C' * ( SUM_j R[t_j] W[t_j]  -  W[T+1] * SUM_j R[t_j] )

with R = 1/P and W the suffix sum of P[t]*f[t].  Both terms are strided window
sums, so funding is also O(N).

LIMITS -- this evaluator is exact only when:
  * entry is unconditional and on a fixed stride,
  * the position is never liquidated (enforce by leverage == 1, or by checking
    the simulator), and
  * there is no path-dependent exit.
Anything else must go through orc.eval.simulate.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def strided_window_sum(a: np.ndarray, k: int, n: int) -> tuple[np.ndarray, np.ndarray]:
    """Sum of n terms taken every k steps, for every start offset.

    Returns (sums, start_index) where
        sums[i] == a[s] + a[s+k] + ... + a[s+(n-1)k],  s == start_index[i]
    Only start offsets whose whole window lies inside `a` are returned.
    """
    a = np.asarray(a, dtype=np.float64)
    N = a.size
    if n < 1 or k < 1:
        raise ValueError("k and n must be >= 1")
    if (n - 1) * k >= N:
        return np.empty(0), np.empty(0, dtype=np.int64)

    n_periods = -(-N // k)                       # ceil
    pad = n_periods * k - N
    ap = np.concatenate([a, np.zeros(pad)]) if pad else a
    grid = ap.reshape(n_periods, k)              # grid[m, r] == a[m*k + r]

    cs = np.zeros((n_periods + 1, k), dtype=np.float64)
    np.cumsum(grid, axis=0, out=cs[1:])
    win = cs[n:] - cs[:-n]                       # win[m, r] -> start s = m*k + r

    m_idx, r_idx = np.divmod(np.arange(win.size), k)
    starts = m_idx * k + r_idx
    ends = starts + (n - 1) * k
    ok = ends < N
    return win.ravel()[ok], starts[ok].astype(np.int64)


@dataclass(frozen=True)
class AnalyticSpec:
    contribution: float          # USDT per deposit
    stride_bars: int             # bars between deposits
    n_contributions: int
    hold_bars: int = 0           # bars held after the LAST deposit
    fee_bps: float = 4.5
    slippage_bps: float = 1.0
    exit_fee_bps: float = 4.5

    @property
    def entry_cost(self) -> float:
        return (self.fee_bps + self.slippage_bps) / 1e4

    @property
    def exit_cost(self) -> float:
        return (self.exit_fee_bps + self.slippage_bps) / 1e4

    @property
    def horizon_bars(self) -> int:
        return (self.n_contributions - 1) * self.stride_bars + self.hold_bars


def evaluate(
    close: np.ndarray,
    spec: AnalyticSpec,
    funding_flow: np.ndarray | None = None,
) -> dict:
    """Terminal outcome of unconditional DCA for every admissible start offset.

    `funding_flow[t]` must equal P[t] * funding_rate[t] (zero on non-settlement
    bars).  Pass None for spot-style accumulation, which pays no funding.
    """
    close = np.asarray(close, dtype=np.float64)
    N = close.size
    k, n = spec.stride_bars, spec.n_contributions
    R = 1.0 / close

    units_sum, starts0 = strided_window_sum(R, k, n)
    if starts0.size == 0:
        return {"n_starts": 0}

    # Keep only starts whose FULL horizon (deposits + hold) fits in the series.
    ends0 = starts0 + spec.horizon_bars
    fits = ends0 < N
    if not fits.any():
        return {"n_starts": 0}

    starts, ends = starts0[fits], ends0[fits]
    # Cost convention (shared with orc.eval.simulate so the two agree exactly):
    #   buys fill at P*(1+c), sells at P*(1-c), mark-to-market always at P.
    cprime = spec.contribution / (1.0 + spec.entry_cost)
    units_sum_f = units_sum[fits]
    units = cprime * units_sum_f
    invested = spec.contribution * n

    funding_paid = np.zeros_like(units)
    if funding_flow is not None:
        F = np.asarray(funding_flow, dtype=np.float64)
        if F.size != N:
            raise ValueError("funding_flow must align with close")
        # W[i] = sum_{t >= i} P[t]*f[t];  W has one extra slot so W[N] == 0.
        W = np.zeros(N + 1, dtype=np.float64)
        W[:N] = np.cumsum(F[::-1])[::-1]
        rw_sum, starts_rw = strided_window_sum(R * W[:N], k, n)
        assert starts_rw.size == starts0.size, "prefix-sum grids diverged"
        funding_paid = cprime * (rw_sum[fits] - W[ends + 1] * units_sum_f)

    gross = units * close[ends]
    terminal = gross * (1.0 - spec.exit_cost) - funding_paid

    return {
        "n_starts": int(starts.size),
        "start_idx": starts,
        "end_idx": ends,
        "units": units,
        "invested": float(invested),
        "terminal_value": terminal,
        "terminal_multiple": terminal / invested,
        "funding_paid": funding_paid,
        "avg_fill_price": invested / np.maximum(units, 1e-300),
        "final_price": close[ends],
    }


def lump_sum_reference(close: np.ndarray, spec: AnalyticSpec,
                       funding_flow: np.ndarray | None = None) -> dict:
    """Same capital, deployed entirely at the first bar.  DCA that cannot beat
    this on the metric you care about has not earned its complexity.

    `funding_flow` is not optional in spirit.  This benchmark used to have no
    way to accept it while evaluate() charged it, so runner's vs_lump_sum_q50
    subtracted an unfunded benchmark from a funded result -- and a lump sum on
    a perpetual holds full notional for the whole horizon, which is the most
    funding any schedule can pay.  On BTCUSDT at 156 weekly deposits the DCA
    was charged 5,679 USDT and the benchmark 0 against a true 30,387, and the
    reported figure went from -1.582 to +0.056: the sign of the comparison,
    not its size.  Pass None only for a genuinely spot benchmark.
    """
    close = np.asarray(close, dtype=np.float64)
    N = close.size
    starts = np.arange(0, N - spec.horizon_bars, dtype=np.int64)
    if starts.size == 0:
        return {"n_starts": 0}
    ends = starts + spec.horizon_bars
    capital = spec.contribution * spec.n_contributions
    units = capital / (close[starts] * (1.0 + spec.entry_cost))

    funding_paid = np.zeros_like(units)
    if funding_flow is not None:
        F = np.asarray(funding_flow, dtype=np.float64)
        if F.size != N:
            raise ValueError("funding_flow must align with close")
        # Same convention as evaluate(): a position pays from the bar it is
        # opened on through the bar it is closed on, inclusive.
        W = np.zeros(N + 1, dtype=np.float64)
        W[:N] = np.cumsum(F[::-1])[::-1]
        funding_paid = units * (W[starts] - W[ends + 1])

    terminal = units * close[ends] * (1.0 - spec.exit_cost) - funding_paid
    return {
        "n_starts": int(starts.size),
        "start_idx": starts,
        "end_idx": ends,
        "invested": float(capital),
        "terminal_value": terminal,
        "terminal_multiple": terminal / capital,
        "funding_paid": funding_paid,
    }
