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
from orc.orchestrator.spec import (Hypothesis, closed_families, load_registry,
                                   probe_ceiling)
from orc.orchestrator.surface import summarise, write_report
from orc.orchestrator.verdict import disqualifiers

import notify                                                     # noqa: E402
from robustness import main as robustness_main                    # noqa: E402


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

            # N is the denominator of every correction this project will ever
            # apply and it can only grow.  A grid is refused whole rather than
            # trimmed: trimming would edit a pre-registered grid, which is the
            # one thing section 3 forbids outright.
            # Depth is earned by a result. A mechanism with no rows in the
            # ledger has survived nothing and gets a probe; a family that has
            # been tested and not closed may go wide under a new id.
            ceiling = probe_ceiling(h.family)
            if h.size() > ceiling:
                raise ValueError(
                    f"{h.size()} configurations exceeds the ceiling of {ceiling} "
                    f"for this family"
                    + (" -- it has no rows in the ledger, so it gets a probe of at "
                       f"most {config.MAX_PROBE_CONFIGURATIONS} before it may be "
                       "enumerated wide"
                       if ceiling == config.MAX_PROBE_CONFIGURATIONS else "")
                    + ". Propose a smaller grid under a new id; the grid of a "
                    "registered hypothesis cannot be trimmed after the fact.")

            # A grid with no ordinal axis returns no shape, and an unmeasured
            # shape is a disqualifier: every cell would enter N and none could
            # ever be a finding.  H0006 and H0007 cost 126 trials between them
            # for exactly this, both reporting '?' on all nine symbols.
            if not h.shape_is_measurable():
                raise ValueError(
                    'no grid axis has three or more numeric levels, so the shape '
                    'diagnostic can never run and no cell in this family can ever '
                    'clear. Restate the axis you expect to matter as numbers -- '
                    'a five-level string axis does not count.')

            # A queue file that is byte-identical to what is already registered
            # is a re-drop, not an edit -- the worker and the reasoning layer
            # both push, and a rebase can put the same file back.  Consume it
            # and carry on; save() below refuses anything that actually differs.
            prior = config.REGISTRY / f"{h.hypothesis_id}.json"
            if prior.exists() and json.loads(
                    prior.read_text(encoding="utf-8")).get("prereg_hash") == h.prereg_hash:
                path.unlink()
                print(f"  already registered {h.hypothesis_id}  hash {h.prereg_hash[:12]}")
                continue

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


def blocked_by_findings() -> list[dict]:
    """High-severity findings that stand between the code and a trial.

    The reasoning layer has refused to run on code known to be wrong since
    17:25 yesterday.  This step -- the one that actually books trials -- did
    not, and it is the irreversible half: a reasoning pass that reads a bad
    report can be re-run, but a row in the ledger is permanent and counts
    toward N forever.  The worker fires every six hours and would have booked
    1044 Track B trials at 09:00 KST on an evaluator whose own review says it
    records a funding-driven wipeout as an ordinary signal exit.
    """
    import findings as ledger
    return ledger.blocking()


def run_cycle(only: list[str] | None = None, rerun_all: bool = False,
              ignore_findings: bool = False) -> dict:
    config.ensure_dirs()
    run_id = uuid.uuid4().hex[:12]
    started = datetime.now(timezone.utc)

    blocked = [] if ignore_findings else blocked_by_findings()
    if blocked:
        print(f"ORC cycle {run_id}  BLOCKED")
        print("An unaddressed high-severity finding stands. Nothing was "
              "evaluated and nothing was written; the queue is untouched.")
        for f in blocked:
            print(f"  {f['id']}  {f['file']}:{f.get('line')}  "
                  f"{str(f['what'])[:90]}")
        print("Fix it, or record the decision:")
        print("  python scripts/findings.py wontfix <id> <reason>")
        return {"run_id": run_id, "status": "BLOCKED",
                "blocked_by": [f["id"] for f in blocked]}

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

    # Evaluate what is new; report on everything registered.  Section 9 forbids
    # the reasoning pass from reading anything but CYCLE_REPORT.md, and on a
    # cycle that picked up fresh hypotheses this wrote a report listing only
    # those -- asking the next pass to decide "continue or close" for families
    # that had vanished from the only document it may open.  It righted itself
    # six hours later when the queue was empty again, which made it a
    # scheduling accident rather than a guarantee.  Reporting re-reads the
    # ledger; it does not re-run a trial.
    to_report = todo if only else load_registry()

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
    for h in to_report:
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
    # The gate belongs in the cycle, not in a command someone has to remember.
    # A robustness check that only runs when asked is a robustness check that
    # runs after the decision it was supposed to inform.
    try:
        robustness_main([])
    except Exception as exc:                                      # noqa: BLE001
        print(f"  robustness gate failed: {type(exc).__name__}: {exc}")

    # A Korean-language briefing, regenerated every cycle and committed, so the
    # owner can read where the research stands from a phone without running
    # anything. It reads the reports this cycle just wrote and never the ledger:
    # hunting a maximum across every trial ever recorded is the selection bias
    # the whole protocol exists to contain.
    try:
        import briefing
        (config.REPORTS / "BRIEFING.md").write_text(briefing.build(), encoding="utf-8")
        print("written: reports/BRIEFING.md")
    except Exception as exc:                                      # noqa: BLE001
        print(f"  briefing failed: {type(exc).__name__}: {exc}")

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

    # The two figures anyone reading this actually wants, in one place, with
    # the reason each one is not yet a result attached to it. Putting them at
    # the top is not a concession to impatience: a return quoted without its
    # drawdown and its disqualifiers is the exact shape of a bad decision.
    L.append("## Headline")
    L.append("")
    L.append("Best cell per family per symbol, ranked on the metric that "
             "survives a horizon change. `return p.a.` is the annualised "
             "money-weighted return at the 5th percentile of start dates on "
             "track A, and the CAGR of the single equity curve on track B. "
             "`max drawdown` is drawdown on invested capital on track A -- "
             "peak-to-trough of profit over contributed capital, so it can "
             "exceed 100% -- and conventional equity drawdown on track B. The "
             "two are not comparable and are labelled.")
    L.append("")
    L.append("| family | symbol | return p.a. | max drawdown | basis | not a finding because |")
    L.append("|---|---|---:|---:|---|---|")
    any_clear = False
    for rep in reports:
        m = rep["metric"]
        pbo_ok = {sy: r.get("pbo") for sy, r in rep.get("pbo", {}).items()
                  if r.get("status") == "ok" and r.get("covers_reported_best")}
        search = rep.get("search_test", {})
        rows = sorted(rep["surfaces"].items(),
                      key=lambda kv: -(kv[1].get("headline", {}).get("return_pa") or -9e9))
        for sym, srf in rows:
            hd = srf.get("headline", {})
            why = disqualifiers(srf, m, pbo_ok.get(sym), search.get(sym))
            if not why:
                any_clear = True
            r_pa, mdd = hd.get("return_pa"), hd.get("mdd")
            L.append(
                f"| {rep['hypothesis_id']} | {sym} | "
                f"{'n/a' if r_pa is None else format(r_pa * 100, '+.1f') + '%'} | "
                f"{'n/a' if mdd is None else format(mdd * 100, '.1f') + '%'} | "
                f"{hd.get('mdd_kind', '?')} | "
                f"{'**CLEARS EVERY CHECK**' if not why else ', '.join(why)} |")
    L.append("")
    if not any_clear:
        L.append("No cell clears every check. Nothing in this table is a result.")
    L.append("")

    # A closed family disappears from every table above, and section 9 lets the
    # next reasoning pass read nothing but this document.  Without this section
    # the family is simply gone: the proposer, told to name a mechanism nobody
    # has tested, has no way to know that funding_carry_short was tested and
    # answered, and re-proposing it is the likeliest single mistake it can make.
    closed = closed_families()
    if closed:
        L.append("## Closed families -- answered, do not re-propose")
        L.append("")
        L.append("These are not gaps in the map. Each was closed against its "
                 "own pre-registered kill condition and its grid is no longer "
                 "enumerated. The reason is the finding.")
        L.append("")
        L.append("| family | closed because | post-mortem |")
        L.append("|---|---|---|")
        for hid, rec in sorted(closed.items()):
            reason = " ".join(str(rec.get("reason", "")).split())
            L.append(f"| {hid} `{rec.get('family', '?')}` | "
                     f"{reason[:400]}{'...' if len(reason) > 400 else ''} | "
                     f"`reports/{rec.get('postmortem', 'not written')}` |")
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
        refused = [r for r in rep["pbo"].values() if r.get("status") != "ok"]
        if ok:
            L.append("| PBO symbol | PBO | verdict | covers best cell | "
                     "configs | splits |")
            L.append("|---|---:|---|---|---:|---:|")
            for r in ok:
                covers = r.get("covers_reported_best")
                L.append(f"| {r['symbol']} | {r['pbo']:.3f} | {r['verdict']} | "
                         f"{'yes' if covers else '**no**'} | "
                         f"{r['n_configs']} | {r['n_splits']} |")
            L.append("")
            # A PBO computed on a horizon group that does not contain the cell
            # in the table above is a measurement of other cells. It reads as
            # that cell clearing the check; verdict.py no longer lets it, and
            # the reader of this document should not be misled either.
            if any(not r.get("covers_reported_best") for r in ok):
                L.append("A **no** under `covers best cell` means that PBO was "
                         "computed on configurations that do not include the best "
                         "cell in the table above. It says nothing about that cell, "
                         "and the check counts as not run.")
                L.append("")
        for r in refused:
            # A refusal is a result: it says the split could not be made, which
            # is not the same as a selection that carried information.
            L.append(f"- PBO on **{r.get('symbol')}** could not be computed: "
                     f"{r.get('status')}")
        if refused:
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
    result = run_cycle(only=args or None, rerun_all="--all" in sys.argv,
                       ignore_findings="--ignore-findings" in sys.argv)
    # A cycle that found no panels evaluated nothing.  It used to return a dict
    # like any other, which is truthy, so the run went green and the only trace
    # was a line of stdout nobody reads -- a worker whose bundle failed to
    # unpack would have reported success every six hours indefinitely.
    # BLOCKED exits non-zero for the same reason, and because the workflow's
    # commit step is not `if: always()`: a refused cycle must not commit.
    raise SystemExit(1 if result.get("status") in ("NO_PANELS", "BLOCKED") else 0)
