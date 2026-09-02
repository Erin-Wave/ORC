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
BREAK_EVEN = {"tm_q05": 1.0, "calmar": 0.0}


def disqualifiers(surface: dict, metric: str, pbo: float | None) -> list[str]:
    """Every reason this cell is not a finding.  Empty means it survives."""
    why: list[str] = []
    floor = BREAK_EVEN.get(metric)
    if floor is not None and surface["best_value"] <= floor:
        why.append(f"at or below {floor:g}")
    if surface.get("shape_diagnostic", {}).get("shape") in SPIKE_SHAPES:
        why.append("spike")
    paths = surface.get("independent_paths_best")
    if paths is not None and paths < FEW_PATHS:
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
    return why


def survivors(report: dict) -> list[tuple[str, dict]]:
    """(symbol, surface) for every cell in one hypothesis report that clears."""
    metric = report.get("metric", "tm_q05")
    pbo = {s: r.get("pbo") for s, r in report.get("pbo", {}).items()
           if r.get("status") == "ok"}
    return [(sym, s) for sym, s in report.get("surfaces", {}).items()
            if not disqualifiers(s, metric, pbo.get(sym))]
