"""ORC | What disqualifies a cell, in one place.

Both the status screen and the notifier have to answer the same question -- is
this cell a finding or not -- and they must answer it identically.  Two copies
of the rule drift, and the copy that drifts is always the one that decides
whether to wake someone up.

The thresholds here are the ones written into the constitution, restated as
code so a reader can check them against sections 4 and 6 rather than trust a
number in a report.
"""
from __future__ import annotations

# Frozen before results were seen; each is section 6 of CLAUDE.md in code form.
PBO_USELESS = 0.5          # at 0.5 the selection carries no information at all
SPIKE_SHAPES = ("SPIKE",)  # a corner of the grid, not a mechanism
FEW_PATHS = 5.0            # below this the cell rests on almost one experiment

# The bar a cell must clear before "not disqualified" means anything.  Track A's
# terminal multiple is a multiple of contributed capital, so 1.0 is getting the
# money back; Track B's Calmar is return over drawdown, so 0.0 is not losing.
# Without these a cell that loses a third of the capital reads as surviving.
# mwrr_q05 is the annualised money-weighted return at the fifth percentile of
# start dates, so 0.0 is "the worst realistic path did not lose money".
BREAK_EVEN = {"tm_q05": 1.0, "calmar": 0.0, "mwrr_q05": 0.0}


def disqualifiers(surface: dict, metric: str, pbo: float | None,
                  search: dict | None = None) -> list[str]:
    """Every reason this cell is not a finding.  Empty means it survives."""
    why: list[str] = []
    floor = BREAK_EVEN.get(metric)
    if floor is not None and surface["best_value"] <= floor:
        why.append(f"at or below {floor:g}")
    shape = surface.get("shape_diagnostic", {}).get("shape")
    if shape is None:
        # plateau_score needs an axis with at least three levels for "one step
        # away" to exist; on a grid of two-level axes it returns no shape at
        # all. Reading that absence as "not a spike" let a cell clear the
        # strongest structural check by never being subjected to it.
        why.append("shape unmeasured")
    elif shape in SPIKE_SHAPES:
        why.append("spike")
    paths = surface.get("independent_paths_best")
    if paths is None:
        # The same rule as the shape and the PBO either side of this: a check
        # that did not run is not a check that passed. 112 rows in the ledger
        # predate _span and carry no path count at all, and whichever of a
        # cell's rows the surface happens to keep decides whether the count
        # exists -- so this was the one disqualifier a cell could clear by
        # being measured on an old row rather than by having the paths.
        why.append("path count unmeasured")
    elif paths < FEW_PATHS:
        why.append(f"{paths:g} paths")
    if pbo is None:
        # write_report computes PBO for the top-ranked cells only, and a check
        # that was never run is not a check that passed.  Treating None as
        # clearance let any cell outside that set be announced as clearing
        # "shape, path count and PBO together" with the strongest of the three
        # never computed.
        why.append("PBO unmeasured")
    elif pbo >= PBO_USELESS:
        why.append(f"PBO {pbo:.2f}")
    # The question N exists to answer. A best that a search of this width finds
    # in pure noise one time in twenty is not a finding, however it scored.
    if search is None or search.get("status") != "ok":
        why.append("search test unmeasured")
    elif not search.get("survives_search"):
        why.append(f"p={search.get('p_value', float('nan')):.3f} vs a random search")
    return why


def survivors(report: dict) -> list[tuple[str, dict]]:
    """(symbol, surface) for every cell in one hypothesis report that clears."""
    metric = report.get("metric", "tm_q05")
    # A PBO computed on a subset that does not contain this cell is a
    # measurement of other cells. On H0001 the horizon subset excluded every
    # symbol's best cell and the number cleared them anyway; an uncovered PBO
    # is therefore no PBO, which disqualifiers() already knows how to say.
    pbo = {s: r.get("pbo") for s, r in report.get("pbo", {}).items()
           if r.get("status") == "ok" and r.get("covers_reported_best")}
    search = report.get("search_test", {})
    return [(sym, s) for sym, s in report.get("surfaces", {}).items()
            if not disqualifiers(s, metric, pbo.get(sym), search.get(sym))]
