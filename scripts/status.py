"""ORC | Where the research stands, in one screen.

Reads `reports/` and nothing else -- the same files the reasoning layer is
allowed to open.  Deliberately never scans the ledger for a maximum: hunting
the best row across every trial ever recorded is the selection bias the whole
protocol exists to contain, and a convenience command is exactly how that
creeps back in.

Because of that, a value never appears on its own.  Every best cell is printed
with the three things that decide whether it means anything:

  tm_q05  terminal multiple at the 5th percentile of start dates: what you
          hold at the end per unit contributed, on a start date worse than 95%
          of them.  1.0 is breaking even.  It grows with the horizon, so it is
          only comparable between cells that hold for the same length of time.
  IRR/yr  the same outcome annualised (money-weighted, so the deposits are
          time-weighted properly).  This is the number that compares across
          horizons; CAGR cannot, because DCA has no single starting capital.
  shape   SPIKE is a corner of the grid, not a mechanism.
  paths   how many genuinely independent experiments are under it.  Start
          offsets overlap; six years of history is a handful of experiments.
  PBO     at 0.5 the selection carries no information at all.

Usage:  python scripts/status.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orc import config, holdout                                    # noqa: E402

# Frozen before results were seen.  A cell has to clear all three to be worth a
# sentence, and these are the same lines drawn in CLAUDE.md sections 4 and 6.
PBO_USELESS = 0.5
SPIKE_SHAPES = ("SPIKE",)
FEW_PATHS = 5.0


def _load(name: str):
    p = config.REPORTS / name
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def main() -> int:
    summary = _load("CYCLE_SUMMARY.json")
    if summary is None:
        print("no cycle has run yet; nothing to report")
        return 1

    print(f"last cycle   {summary['finished_utc'][:19]}Z   run {summary['run_id']}")
    print(f"trials (N)   {summary['trials_after']}  (+{summary['trials_added']} that cycle)")
    print(f"holdout      sealed from {summary['holdout_start']}, "
          f"{summary['final_tests_used']}/{holdout.MAX_FINAL_TESTS} openings used")
    print(f"panels       {summary['panels']}")

    survivors = 0
    for res in summary["results"]:
        rep = _load(f"{res['hypothesis_id']}_SURFACE.json")
        if rep is None:
            continue
        print(f"\n{rep['hypothesis_id']}  {rep['family']}   "
              f"({rep['trials_in_family']} trials)")
        print(f"  kill: {rep['kill_condition']}")

        pbo = {s: r.get("pbo") for s, r in rep.get("pbo", {}).items()
               if r.get("status") == "ok"}
        print(f"  {'symbol':10s} {'tm_q05':>8s} {'IRR/yr':>8s} {'horizon':>8s} "
              f"{'shape':8s} {'paths':>7s} {'PBO':>6s}   verdict")
        for sym, s in sorted(rep["surfaces"].items(),
                             key=lambda kv: -kv[1]["best_value"]):
            shape = s["shape_diagnostic"].get("shape", "?")
            paths = s.get("independent_paths_best")
            p = pbo.get(sym)

            why = []
            if shape in SPIKE_SHAPES:
                why.append("spike")
            if paths is not None and paths < FEW_PATHS:
                why.append(f"{paths:g} paths")
            if p is not None and p >= PBO_USELESS:
                why.append(f"PBO {p:.2f}")
            verdict = "not a finding: " + ", ".join(why) if why else "survives these checks"
            survivors += not why

            irr, hz = s.get("mwrr_q05_best"), s.get("horizon_days_best")
            print(f"  {sym:10s} {s['best_value']:8.4f} "
                  f"{'n/a' if irr is None else format(irr * 100, '+.1f') + '%':>8s} "
                  f"{'n/a' if hz is None else format(hz / 365.0, '.2f') + 'y':>8s} "
                  f"{shape:8s} "
                  f"{'n/a' if paths is None else format(paths, 'g'):>7s} "
                  f"{'n/a' if p is None else format(p, '.3f'):>6s}   {verdict}")

    print(f"\n{survivors} cell(s) clear shape, path count and PBO together.")
    if not survivors:
        print("Nothing here is a result. That is a finding about DCA, not a delay.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
