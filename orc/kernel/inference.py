"""ORC | Inference under heavy search.

An automated loop will evaluate tens of thousands of configurations.  At that
volume the best result on the development data is, by construction, mostly a
measurement of how hard you searched.  Two tools are provided, and the runner
is required to use both before anything is called a finding.

1. PBO via CSCV (Bailey, Borwein, Lopez de Prado, Zhu -- "The probability of
   backtest overfitting").  Split the sample into S blocks, take every balanced
   in-sample / out-of-sample partition, and ask how often the configuration
   that wins in-sample lands below the median out-of-sample.  PBO near 0.5 means
   the selection carries no information whatsoever.

2. A best-of-G bootstrap null.  Resample the price history in blocks, re-run
   the WHOLE grid on each synthetic history, and record the best score.  That
   distribution is what "the best of G configurations" looks like when nothing
   is real.  Comparing the observed best against it is the only multiple-testing
   correction here that does not depend on a distributional assumption about
   returns -- which crypto violates comprehensively.

Neither of these rescues a result.  They tell you when to stop believing one.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

import numpy as np


# --------------------------------------------------------------------------
# resampling
# --------------------------------------------------------------------------
def circular_block_bootstrap(
    x: np.ndarray, block: int, n_paths: int, rng: np.random.Generator
) -> np.ndarray:
    """Resample a series in wrap-around blocks, preserving local dependence.

    Returns shape (n_paths, len(x)).  Blocks are the right unit here: iid
    resampling of returns destroys volatility clustering and drawdown shape,
    which is precisely the structure a DCA outcome depends on.
    """
    x = np.asarray(x, dtype=np.float64)
    n = x.size
    if block < 1 or n == 0:
        raise ValueError("block must be >= 1 and x non-empty")
    n_blocks = -(-n // block)
    starts = rng.integers(0, n, size=(n_paths, n_blocks))
    offsets = np.arange(block)
    idx = (starts[:, :, None] + offsets[None, None, :]) % n
    return x[idx.reshape(n_paths, -1)[:, :n]]


def synthetic_prices(
    close: np.ndarray, block: int, n_paths: int, rng: np.random.Generator
) -> np.ndarray:
    """Bootstrap synthetic price paths from the log returns of a real one."""
    close = np.asarray(close, dtype=np.float64)
    logret = np.diff(np.log(close))
    boots = circular_block_bootstrap(logret, block, n_paths, rng)
    return close[0] * np.exp(np.cumsum(
        np.concatenate([np.zeros((n_paths, 1)), boots], axis=1), axis=1))


# --------------------------------------------------------------------------
# PBO / CSCV
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class PBOResult:
    pbo: float                 # probability of backtest overfitting
    n_splits: int
    n_configs: int
    median_logit: float
    oos_rank_of_is_best: np.ndarray
    degraded_fraction: float   # how often OOS performance fell below IS
    # Configurations that could not be ranked at all and were left out of the
    # comparison. Not zero means this PBO describes a smaller grid than the one
    # that was searched, which is a weaker statement than it looks.
    n_dropped_non_finite: int = 0

    def verdict(self) -> str:
        if self.pbo >= 0.5:
            return "SELECTION_IS_NOISE"
        if self.pbo >= 0.25:
            return "SELECTION_WEAK"
        return "SELECTION_INFORMATIVE"


def cscv_pbo(perf: np.ndarray, n_blocks: int = 10) -> PBOResult:
    """Combinatorially symmetric cross-validation.

    `perf` is (T, G): a performance contribution per time slice per config.
    Rows must be comparable across configs -- use the same start dates and the
    same slicing for every column.
    """
    perf = np.asarray(perf, dtype=np.float64)
    if perf.ndim != 2:
        raise ValueError("perf must be 2-D (time, config)")
    T, G = perf.shape
    # np.argmax elects NaN as the maximum and np.argsort sorts it last, so one
    # non-finite column is the in-sample winner of every split and the worst
    # out-of-sample rank in every split: PBO 0.0, degraded_fraction 0.0, verdict
    # SELECTION_INFORMATIVE. On a (60, 8) matrix of normals, blanking one column
    # moves PBO from 0.457 to 0.000 -- a broken cell makes the project's central
    # overfitting guard report that the selection carries full information, which
    # is the most reassuring direction a failure can take. A column that cannot
    # be ranked is dropped and said to have been dropped.
    finite = np.isfinite(perf).all(axis=0)
    n_dropped = int((~finite).sum())
    if n_dropped:
        perf = perf[:, finite]
        T, G = perf.shape
    if G < 2:
        raise ValueError(
            "PBO needs at least two configurations to choose between"
            + (f" ({n_dropped} dropped as non-finite)" if n_dropped else ""))
    if n_blocks % 2:
        n_blocks -= 1
    if n_blocks < 4 or T < n_blocks:
        raise ValueError("need at least 4 blocks and T >= n_blocks")

    edges = np.array_split(np.arange(T), n_blocks)
    half = n_blocks // 2

    logits, ranks, degraded = [], [], 0
    for combo in combinations(range(n_blocks), half):
        is_rows = np.concatenate([edges[i] for i in combo])
        oos_rows = np.concatenate([edges[i] for i in range(n_blocks) if i not in combo])

        is_score = perf[is_rows].mean(axis=0)
        oos_score = perf[oos_rows].mean(axis=0)

        best = int(np.argmax(is_score))
        # rank of the IS winner among OOS scores, 1 == worst
        order = np.argsort(np.argsort(oos_score)) + 1
        w = order[best] / (G + 1.0)
        w = min(max(w, 1.0 / (G + 1.0)), G / (G + 1.0))
        logits.append(np.log(w / (1.0 - w)))
        ranks.append(w)
        degraded += int(oos_score[best] < is_score[best])

    logits_a = np.asarray(logits)
    return PBOResult(
        pbo=float(np.mean(logits_a <= 0.0)),
        n_splits=int(logits_a.size),
        n_configs=int(G),
        n_dropped_non_finite=n_dropped,
        median_logit=float(np.median(logits_a)),
        oos_rank_of_is_best=np.asarray(ranks),
        degraded_fraction=degraded / float(logits_a.size),
    )


# --------------------------------------------------------------------------
# best-of-G under a null
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class BestOfGResult:
    observed_best: float
    null_mean: float
    null_q95: float
    p_value: float
    n_null: int
    n_configs: int

    def verdict(self) -> str:
        return "SURVIVES_SEARCH" if self.p_value < 0.05 else "INDISTINGUISHABLE_FROM_SEARCH"


def best_of_g_pvalue(observed_best: float, null_bests: np.ndarray,
                     n_configs: int) -> BestOfGResult:
    """p-value of the observed best against the bootstrap best-of-G null.

    The null must have been generated by running the SAME grid of G configs on
    each synthetic history.  Running fewer configs understates the null and
    manufactures significance.
    """
    nb = np.asarray(null_bests, dtype=np.float64)
    nb = nb[np.isfinite(nb)]
    if nb.size == 0:
        raise ValueError("empty null distribution")
    p = float((np.sum(nb >= observed_best) + 1.0) / (nb.size + 1.0))
    return BestOfGResult(
        observed_best=float(observed_best),
        null_mean=float(nb.mean()),
        null_q95=float(np.quantile(nb, 0.95)),
        p_value=p,
        n_null=int(nb.size),
        n_configs=int(n_configs),
    )


# --------------------------------------------------------------------------
# response-surface shape: a plateau is evidence, a spike is not
# --------------------------------------------------------------------------
def plateau_score(grid: np.ndarray, ordinal_axes: list[bool] | None = None) -> dict:
    """How isolated is the maximum of a response surface?

    `grid` is the metric evaluated over an N-dimensional parameter lattice.
    A real effect degrades gently as you step away from the optimum; an
    overfit one falls off a cliff.  Reported as the mean of the immediate
    neighbours relative to the peak.

    `ordinal_axes` marks which axes have a meaningful notion of "one step
    away".  A categorical axis -- a switch that is on or off, a symbol name --
    has no neighbours, and stepping along it measures a different mechanism
    rather than a perturbation of the same one.  Those axes are skipped.
    """
    g = np.asarray(grid, dtype=np.float64)
    # The ratio asks how much of the peak the neighbours retain, which only has
    # that meaning when the peak is positive. On a surface where the best cell
    # still loses, dividing one negative by another turns a collapse into a
    # number above one: a peak of -0.04 with neighbours at -1.0 reported a
    # plateau_ratio of 25 and the label PLATEAU. Every negative-valued surface
    # was being shape-labelled backwards.
    if g.size and np.isfinite(np.nanmax(g)) and np.nanmax(g) <= 0:
        return {"peak": float(np.nanmax(g)), "plateau_ratio": float("nan"),
                "unmeasurable": "the peak is not positive; the ratio has no meaning"}
    if g.size < 3 or np.all(np.isnan(g)):
        return {"peak": float(np.nanmax(g)) if g.size else float("nan"),
                "plateau_ratio": float("nan")}
    peak_idx = np.unravel_index(np.nanargmax(g), g.shape)
    if ordinal_axes is None:
        ordinal_axes = [d > 2 for d in g.shape]

    neigh = []
    for axis, i in enumerate(peak_idx):
        if axis < len(ordinal_axes) and not ordinal_axes[axis]:
            continue
        for step in (-1, 1):
            j = i + step
            if 0 <= j < g.shape[axis]:
                sel = list(peak_idx)
                sel[axis] = j
                if not np.isnan(g[tuple(sel)]):
                    neigh.append(g[tuple(sel)])
    peak = float(g[peak_idx])
    if not neigh or peak == 0:
        return {"peak": peak, "plateau_ratio": float("nan"), "n_neighbours": len(neigh)}
    ratio = float(np.nanmean(neigh) / peak)
    return {
        "peak": peak,
        "peak_index": [int(i) for i in peak_idx],
        "neighbour_mean": float(np.nanmean(neigh)),
        "plateau_ratio": ratio,
        "n_neighbours": len(neigh),
        "shape": "PLATEAU" if ratio > 0.90 else ("SLOPE" if ratio > 0.70 else "SPIKE"),
    }
