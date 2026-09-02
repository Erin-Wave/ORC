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

    nulls = []
    for i in range(n_paths):
        try:
            v = score_grid(synth[i])
        except Exception:                                          # noqa: BLE001
            continue
        if np.isfinite(v):
            nulls.append(float(v))

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
