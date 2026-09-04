"""ORC | The question N exists to answer, finally asked.

The ledger counts every trial and calls that count N, and the constitution says
N feeds the multiple-testing correction applied to every result. The counting
worked. The correction was never implemented: `best_of_g_pvalue`,
`circular_block_bootstrap` and `synthetic_prices` sat in the kernel unreferenced
by anything, tests included, while N was printed at the end of each cycle and
consumed by nothing.

So every verdict up to now asked whether a cell was a spike, whether it rested
on enough independent paths, whether the selection carried information, and
whether it cleared break-even -- and never once asked the question underneath
all of them: given that this many configurations were tried, how surprising is
the best of them?

The answer needs a null with the same search in it. The grid is re-run on
synthetic histories bootstrapped from the symbol's own returns in wrap-around
blocks, so each synthetic keeps the volatility clustering and drawdown shape of
the real series but none of its structure. Taking the best cell on each
synthetic builds the distribution of "best of G by luck alone", and the real
best is compared against it.

Running fewer configurations against the null than were tried for real
understates it and manufactures significance, so the same grid runs both times.
That is what makes this expensive and what makes it worth anything.
"""
from __future__ import annotations

import os
import pickle
from concurrent.futures import ProcessPoolExecutor
from functools import partial

import numpy as np

from orc.kernel.inference import best_of_g_pvalue, synthetic_prices

# Frozen before any family cleared. A day of hourly bars keeps the local
# dependence a DCA or a hold-for-days rule actually experiences; shorter blocks
# resample away the drawdowns that decide the left tail.
BOOTSTRAP_BLOCK_BARS = 24

# Enough for a 5% threshold to mean something without the run costing an hour:
# with 199 synthetics the smallest reportable p-value is 1/200.
N_SYNTHETIC_PATHS = 199

# A best that a random search would beat one time in twenty is not a finding.
ALPHA = 0.05


def n_workers(n_tasks: int) -> int:
    """How many processes to spread the null over.

    The synthetic paths are independent by construction -- that is what makes
    the null a null -- so this is the one genuinely embarrassing parallelism in
    the project, and it sits on the single most expensive thing it does.
    Measured on H0001/BTCUSDT: 4.77s for one path over the grid, 15.8 minutes
    for 199, 31.7 for the two symbols a report covers.  That was the research
    cycle: a 24-core workstation running one core.

    ORC_WORKERS overrides, because the GitHub runner has far fewer cores than
    the workstation and a pool wider than the machine is slower, not faster.
    """
    env = os.environ.get("ORC_WORKERS", "").strip()
    if env:
        try:
            n = int(env)
        except ValueError:
            n = 0
        if n > 0:
            return max(1, min(n, n_tasks))
    return max(1, min(os.cpu_count() or 1, n_tasks))


def _safe_score(score_grid, close) -> float:
    """One synthetic path, scored, with a failure reported as nan.

    A path the grid cannot express is information about the grid and must not
    take the run down -- the serial loop caught this inline, and a pool has to
    catch it INSIDE the worker or the exception surfaces when the result is
    consumed and kills the whole null.
    """
    try:
        v = float(score_grid(close))
    except Exception:                                              # noqa: BLE001
        return float("nan")
    return v if np.isfinite(v) else float("nan")


def _is_picklable(obj) -> bool:
    """Can this scorer cross a process boundary?

    The scorers in surface.py are objects precisely so that they can.  A plain
    closure -- what a test or a one-off analysis naturally writes -- cannot, and
    must quietly fall back to the serial path rather than raising.
    """
    try:
        pickle.dumps(obj)
        return True
    except Exception:                                              # noqa: BLE001
        return False


def best_of_g(observed_best: float, score_grid, panel, n_configs: int,
              seed: int = 20260902,
              n_paths: int = N_SYNTHETIC_PATHS,
              block: int = BOOTSTRAP_BLOCK_BARS) -> dict:
    """Compare the observed best against the best a search finds in noise.

    `score_grid(close)` runs the whole grid on one price series and returns the
    best value it finds. It is called once per synthetic path, so it carries
    the cost of the entire search -- which is the point.
    """
    rng = np.random.default_rng(seed)
    synth = synthetic_prices(panel.close, block, n_paths, rng)

    # Every path is drawn up front from one seeded generator and the results are
    # consumed IN ORDER, so the pool changes how long this takes and nothing
    # about what it answers: the same seed gives the same nulls, serial or not.
    paths = [synth[i] for i in range(n_paths)]
    workers = n_workers(len(paths))
    scored: list[float] = []
    if workers > 1 and _is_picklable(score_grid):
        chunk = max(1, len(paths) // (workers * 4))
        with ProcessPoolExecutor(max_workers=workers) as pool:
            scored = list(pool.map(partial(_safe_score, score_grid), paths,
                                   chunksize=chunk))
    else:
        scored = [_safe_score(score_grid, close) for close in paths]

    nulls = [v for v in scored if np.isfinite(v)]

    if len(nulls) < n_paths // 2:
        return {"status": f"only {len(nulls)} of {n_paths} synthetic searches scored; "
                          f"the null is too thin to compare against"}

    r = best_of_g_pvalue(observed_best, np.array(nulls), n_configs)
    return {
        "status": "ok",
        "observed_best": r.observed_best,
        "null_mean": r.null_mean,
        "null_q95": r.null_q95,
        "p_value": r.p_value,
        "n_null": r.n_null,
        "n_configs": r.n_configs,
        "block_bars": block,
        "verdict": r.verdict(),
        # The null was built by running the same grid, so a p-value at or above
        # alpha says a search this wide finds this good a cell in pure noise
        # about that often.
        "survives_search": bool(r.p_value < ALPHA),
    }
