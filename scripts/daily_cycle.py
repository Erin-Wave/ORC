"""ORC | One research cycle.

This is the entry point every automated trigger calls -- a GitHub Actions cron,
a Claude Code routine, or a human at a terminal.  One invocation:

  1. picks up every hypothesis dropped in configs/queue/ by the reasoning layer,
  2. registers it (which hashes the claim and the grid BEFORE any result exists),
  3. enumerates and evaluates the whole grid, recording every trial,
  4. writes the response surface, the shape diagnostic and PBO,
  5. emits reports/CYCLE_REPORT.md -- the single document the next reasoning
     pass reads to decide what to ask next.

The loop is deliberately split: this script contains no judgement.  It cannot
decide that a result is interesting, cannot adjust a grid, and cannot open the
holdout.  Everything it does is mechanical and reproducible from the registry.
"""
from __future__ import annotations

import json
import shutil
import sys
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orc import config, holdout
from orc.facts import panel as panel_mod
from orc.ledger.trials import Ledger
from orc.orchestrator.runner import run_hypothesis
from orc.orchestrator.spec import Hypothesis, load_registry
from orc.orchestrator.surface import summarise, write_report

import notify                                                     # noqa: E402


def intake_queue() -> list[Hypothesis]:
    """Register queued hypotheses.  Registration is the moment of no return:
    after it, the claim and the grid are hashed and cannot be edited."""
    registered: list[Hypothesis] = []
    for path in sorted(config.QUEUE.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            h = Hypothesis(**raw)
            if not h.prereg_hash:
                h.register()
            h.verify()
            h.save()
            registered.append(h)
            path.unlink()
            print(f"  registered {h.hypothesis_id}  {h.family}  "
                  f"{h.size()} configurations  hash {h.prereg_hash[:12]}")
        except Exception as exc:                                  # noqa: BLE001
            bad = config.QUEUE / "rejected"
            bad.mkdir(exist_ok=True)
            shutil.move(str(path), str(bad / path.name))
            print(f"  REJECTED {path.name}: {type(exc).__name__}: {exc}")
    return registered


def run_cycle(only: list[str] | None = None, rerun_all: bool = False) -> dict:
    config.ensure_dirs()
    run_id = uuid.uuid4().hex[:12]
    started = datetime.now(timezone.utc)

    print(f"ORC cycle {run_id}  {started.isoformat()}")
    print(f"  holdout sealed from {config.HOLDOUT_START} "
          f"({holdout.openings_used()}/{holdout.MAX_FINAL_TESTS} final tests used)")

    symbols = panel_mod.available_symbols("1h")
    print(f"  panels available: {len(symbols)}")
    if not symbols:
        print("  no panels; run  python -m orc.facts.build_panel  first")
        return {"run_id": run_id, "status": "NO_PANELS"}

    print("\nqueue intake")
    fresh = intake_queue()

    todo = fresh if (fresh and not rerun_all) else load_registry()
    if only:
        todo = [h for h in todo if h.hypothesis_id in only]
    if not todo:
        print("\nnothing to run: the queue is empty and no hypothesis was selected")
        todo = []

    print(f"\nexecuting {len(todo)} hypotheses")
    results, reports = [], []
    with Ledger() as led:
        before = led.total_trials()
        for h in todo:
            try:
                results.append(run_hypothesis(h, ledger=led, run_id=run_id))
            except Exception as exc:                              # noqa: BLE001
                print(f"  {h.hypothesis_id} FAILED: {type(exc).__name__}: {exc}")
                traceback.print_exc(limit=3)
                results.append({"hypothesis_id": h.hypothesis_id,
                                "error": f"{type(exc).__name__}: {exc}"})
        after = led.total_trials()

    print("\nreports")
    for h in todo:
        try:
            rep = write_report(h)
            reports.append(rep)
            print(summarise(rep))
        except Exception as exc:                                  # noqa: BLE001
            print(f"  {h.hypothesis_id} report failed: {type(exc).__name__}: {exc}")

    summary = {
        "run_id": run_id,
        "started_utc": started.isoformat(),
        "finished_utc": datetime.now(timezone.utc).isoformat(),
        "holdout_start": str(config.HOLDOUT_START),
        "final_tests_used": holdout.openings_used(),
        "panels": len(symbols),
        "hypotheses_run": [r.get("hypothesis_id") for r in results],
        "trials_before": before,
        "trials_after": after,
        "trials_added": after - before,
        "results": results,
    }
    (config.REPORTS / "CYCLE_SUMMARY.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8")
    write_cycle_markdown(summary, reports)

    # Publish the notifier's answer rather than its thresholds.  Anything that
    # wants to raise an alarm -- a desktop toast, a phone push from a cloud
    # routine that cannot import this package -- reads this one file, so there
    # is still exactly one definition of what counts as a finding.
    news = notify.collect()
    (config.REPORTS / "NEWS.json").write_text(
        json.dumps({"generated_utc": summary["finished_utc"],
                    "run_id": run_id, "items": news}, indent=2),
        encoding="utf-8")
    print(f"news items: {len(news)}")
    print(f"\ntrials {before} -> {after}   (+{after - before})")
    print(f"written: {config.REPORTS / 'CYCLE_REPORT.md'}")
    return summary


def write_cycle_markdown(summary: dict, reports: list[dict]) -> None:
    """The hand-off document.  The next reasoning pass reads ONLY this."""
    L: list[str] = []
    L.append("# ORC cycle report")
    L.append("")
    L.append(f"- run `{summary['run_id']}` finished {summary['finished_utc']}")
    L.append(f"- trials in project: **{summary['trials_after']}** "
             f"(+{summary['trials_added']} this cycle)")
    L.append(f"- holdout sealed from **{summary['holdout_start']}**, "
             f"final tests used {summary['final_tests_used']}/{holdout.MAX_FINAL_TESTS}")
    L.append("- primary metric per track: `tm_q05` for accumulation "
             "(5th-percentile terminal multiple across start dates), "
             "`calmar` for signal positions (return over deepest drawdown)")
    L.append("")
    L.append("Every number below is development data only. The ranking is not a "
             "result; the shape column and PBO are what decide whether it means "
             "anything.")
    L.append("")

    for rep in reports:
        L.append(f"## {rep['hypothesis_id']} — {rep['family']} "
                 f"(track {rep.get('track', 'A')}, metric `{rep['metric']}`)")
        L.append("")
        L.append(f"**Claim.** {rep['claim']}")
        L.append("")
        L.append(f"**Kill condition.** {rep['kill_condition']}")
        L.append("")
        L.append(f"Trials in this family: {rep['trials_in_family']}. "
                 f"Pre-registration hash `{rep['prereg_hash'][:16]}`.")
        L.append("")
        L.append("| symbol | best | shape | neighbour/peak | start offsets | "
                 "indep. paths | best cell |")
        L.append("|---|---:|---|---:|---:|---:|---|")
        for sym, s in sorted(rep["surfaces"].items(), key=lambda kv: -kv[1]["best_value"]):
            d = s["shape_diagnostic"]
            starts = s.get("n_starts_best")
            paths = s.get("independent_paths_best")
            L.append(f"| {sym} | {s['best_value']:+.4f} | {d.get('shape', '?')} | "
                     f"{d.get('plateau_ratio', float('nan')):.3f} | "
                     f"{'n/a' if starts is None else format(starts, ',')} | "
                     f"{'n/a' if paths is None else format(paths, 'g')} | "
                     f"`{s['best_config']}` |")
        L.append("")
        # Section 6 of the constitution requires this number to be read, and
        # section 9 forbids the reasoning pass from opening anything but this
        # file.  It therefore has to be stated here, next to the value it
        # qualifies, or the rule cannot be obeyed.
        L.append("`start offsets` is how many start dates the evaluator scored. "
                 "`indep. paths` is a generous upper bound on how many of those "
                 "are genuinely separate experiments, since overlapping windows "
                 "over the same history are not independent draws. When the two "
                 "differ by three orders of magnitude, the second is the honest "
                 "sample size.")
        L.append("")
        ok = [r for r in rep["pbo"].values() if r.get("status") == "ok"]
        if ok:
            L.append("| PBO symbol | PBO | verdict | configs | splits |")
            L.append("|---|---:|---|---:|---:|")
            for r in ok:
                L.append(f"| {r['symbol']} | {r['pbo']:.3f} | {r['verdict']} | "
                         f"{r['n_configs']} | {r['n_splits']} |")
            L.append("")

    L.append("## What the next pass must do")
    L.append("")
    L.append("1. Read the shape column first. A `SPIKE` is not a finding no matter "
             "how large its value; it means the grid found a corner, not a mechanism.")
    L.append("2. Do not propose a new grid over the same rule form. Parameters are "
             "already enumerated exhaustively. Propose a different RULE SHAPE, and "
             "state who is structurally paying for it.")
    L.append("3. Every proposal needs a kill condition written before results exist.")
    L.append("4. Say the independent-path count out loud when you argue from a "
             "number. Millions of start offsets over six years of history are "
             "still only a handful of independent experiments.")
    L.append("5. The holdout stays sealed. Nothing in this document justifies opening it.")
    L.append("")
    (config.REPORTS / "CYCLE_REPORT.md").write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    raise SystemExit(0 if run_cycle(
        only=args or None,
        rerun_all="--all" in sys.argv,
    ) else 1)
