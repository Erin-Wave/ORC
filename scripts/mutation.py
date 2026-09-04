"""ORC | Are the tests load-bearing, or do they just pass?

A green suite says the code satisfies the tests. It does not say the tests
would notice if the code were wrong, and those are different claims: coverage
and mutation score on generated suites are known not to track defect detection
reliably. The only way to find out is to break the code on purpose and see
whether anything fails.

So this file carries a fixed list of DEFECTS THAT HAVE ACTUALLY HAPPENED HERE,
or that would void every result if they did:

  a fill that can be taken by a price printed before the position existed
  a settlement charged to a position that did not yet exist
  a stop and a target in one bar resolved in our own favour
  a 4-hour candle readable three hours before it closes
  CCI scaled by a standard deviation instead of the mean absolute deviation
  the holdout seal simply not applied

Each is applied, the suite is run, and the mutation is KILLED if something
fails and SURVIVED if nothing does. A survivor is not a bug in the code -- the
code is correct, the mutation was reverted -- it is a hole in the oracle, which
is worse, because it is the shape of every future defect nobody will catch.

Two properties make this safe to run unattended, and both are deliberate:

  it never touches the live tree   The 24-hour supervisor is running from this
                                   working copy. Mutating a file in place, even
                                   with a restore in `finally`, means a cycle
                                   can execute a knowingly broken kernel. The
                                   whole run happens in a throwaway copy.
  the baseline defines pass        Some tests are about THIS checkout -- the
                                   scheduled tasks, the installed git hooks --
                                   and cannot pass in a copy. Rather than a
                                   hand-maintained skip list that rots, the
                                   copy is run once unmutated and whatever
                                   fails there is deselected for every mutant.
                                   A mutation is then judged only against tests
                                   that were green a moment earlier.

    python scripts/mutation.py           run them all, write reports/MUTATION.json
    python scripts/mutation.py --list    what is checked, without running it

Exit 0 if every mutation was killed, 1 if any survived, 2 if the baseline
itself could not be made green -- in which case the run measured nothing and
says so rather than reporting kills.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(errors="replace")
except (AttributeError, OSError):                                  # pragma: no cover
    pass

from orc import config                                             # noqa: E402

# What gets copied. facts/ is 9.7 GB and is pointed at through ORC_FACTS
# instead; .git/hooks is 4 KB and two tests read it.
COPIED = ("orc", "tests", "scripts", "configs")
COPIED_FILES = ("CLAUDE.md", "AGENTS.md", "requirements.txt", "pytest.ini")

# A mutation is (id, file, exactly this text, replaced by this, why it matters).
# `old` must appear EXACTLY ONCE in the file: a mutation that matches two
# places is testing something other than what it says, and one that matches
# none is testing nothing at all. Both are refused at load, and
# test_every_mutation_still_applies fails the day the kernel moves underneath
# one of them -- which is how this list stays honest without anyone auditing it.
MUTATIONS = [
    {
        "id": "fill_bar_extremes",
        "file": "orc/eval/signal.py",
        "old": "        scan = slice(a + 1, b + 1)",
        "new": "        scan = slice(a, b + 1)",
        "why": "lets a target be hit by a wick that printed BEFORE the fill. "
               "This is a defect that really happened: a flat series with "
               "high[5]=130 and a fill at close[5]=100 returned a closed trade "
               "with bars_held 0 and +20%.",
    },
    {
        "id": "funding_before_the_fill",
        "file": "orc/eval/signal.py",
        "old": "        funding = -side * qty * float(flow_cum[b + 1] - flow_cum[a + 1])",
        "new": "        funding = -side * qty * float(flow_cum[b + 1] - flow_cum[a])",
        "why": "credits a full-notional settlement to a position that did not "
               "yet exist, on roughly one trade in eight, in a family whose "
               "entire subject is funding income.",
    },
    {
        "id": "target_wins_the_tie",
        "file": "orc/eval/signal.py",
        "old": '_PRIORITY = {"liquidation": 0, "stop": 1, "take_profit": 2, "signal": 3}',
        "new": '_PRIORITY = {"liquidation": 0, "take_profit": 1, "stop": 2, "signal": 3}',
        "why": "an hourly bar cannot say whether the stop or the target was "
               "touched first, and resolving it in our own favour is how a "
               "backtest invents money.",
    },
    {
        "id": "higher_timeframe_lookahead",
        "file": "orc/eval/signal_rules.py",
        "old": '    available = np.searchsorted(b_end_ms, ms + step_ms, side="right") - 1',
        "new": '    available = np.searchsorted(b_end_ms, ms + tf_ms, side="right") - 1',
        "why": "makes the 00:00-04:00 candle readable at 01:00, so the rule "
               "decides on the high, low and close of hours that have not "
               "happened. It looks like a working strategy because it is one, "
               "for someone who can see three hours ahead.",
    },
    {
        "id": "cci_scaled_by_stdev",
        "file": "orc/eval/signal_rules.py",
        "old": "        d = np.abs(w - m[:, None]).mean(axis=1)",
        "new": "        d = w.std(axis=1)",
        "why": "a standard deviation runs about 1.25x the mean absolute "
               "deviation, so every level a hypothesis pre-registered would "
               "mean about 80 % of what it says.",
    },
    {
        "id": "cci_partial_window",
        "file": "orc/eval/signal_rules.py",
        "old": "    if n < period:\n        return mean, mad",
        "new": "    if n < 1:\n        return mean, mad",
        "why": "a statistic computed on however many observations happened to "
               "exist is a statistic fitted to the start of the archive.",
    },
    {
        "id": "carry_reads_the_bar_not_the_settlement",
        "file": "orc/eval/signal_rules.py",
        "old": "        out = np.where(count > 0, total / count, np.nan)",
        "new": "        out = np.where(count > 0, total / window, np.nan)",
        "why": "divides by the window instead of by the settlements in it, so "
               "0.0001 stops meaning 0.01 % per settlement and every "
               "pre-registered threshold silently means something else.",
    },
    {
        "id": "drawdown_upside_down",
        "file": "orc/kernel/metrics_fc.py",
        "old": "    return float(np.max(1.0 - equity / np.maximum(peak, 1e-12)))",
        "new": "    return float(np.max(equity / np.maximum(peak, 1e-12) - 1.0))",
        "why": "max drawdown is half of the owner's stop condition. Inverted it "
               "reports ~0 for every curve, and every candidate clears "
               "TARGET_MAX_DRAWDOWN.",
    },
    {
        "id": "the_seal_is_not_applied",
        "file": "orc/facts/panel.py",
        "old": "        df = holdout.development_slice(df)",
        "new": "        df = df",
        "why": "research would read the sealed period on every load. Nothing "
               "else in this project matters if this one is not caught.",
    },
    {
        "id": "unmeasured_counts_as_passed",
        "file": "orc/orchestrator/verdict.py",
        "old": '    if pbo is None:',
        "new": '    if pbo is None and False:',
        "why": "a check that never ran becomes a check that passed, which is "
               "the easiest possible way for a cell to clear every bar.",
    },
]

FAILED_LINE = re.compile(r"^FAILED (\S+)", re.M)
SUMMARY = re.compile(r"(\d+) failed", re.M)


def verify_targets() -> list[str]:
    """Every mutation must match its file exactly once, or it tests nothing."""
    bad = []
    for m in MUTATIONS:
        try:
            text = (ROOT / m["file"]).read_text(encoding="utf-8")
        except OSError as exc:
            bad.append(f"{m['id']}: {m['file']} unreadable ({exc})")
            continue
        n = text.count(m["old"])
        if n != 1:
            bad.append(f"{m['id']}: its target appears {n} time(s) in "
                       f"{m['file']}; a mutation that matches none tests "
                       "nothing and one that matches several tests something "
                       "other than what it says")
    return bad


def make_copy(dest: Path) -> Path:
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache")
    for d in COPIED:
        src = ROOT / d
        if src.exists():
            shutil.copytree(src, dest / d, ignore=ignore)
    for f in COPIED_FILES:
        if (ROOT / f).exists():
            shutil.copy2(ROOT / f, dest / f)
    (dest / "reports").mkdir(exist_ok=True)
    (dest / "ledger").mkdir(exist_ok=True)
    for name in ("FINDINGS.json", "CYCLE_SUMMARY.json", "TARGET.json"):
        if (config.REPORTS / name).exists():
            shutil.copy2(config.REPORTS / name, dest / "reports" / name)
    hooks = ROOT / ".git" / "hooks"
    if hooks.exists():
        shutil.copytree(hooks, dest / ".git" / "hooks")
    return dest


def run_suite(copy: Path, deselect: list[str]) -> tuple[int, list[str]]:
    cmd = [sys.executable, "-m", "pytest", "tests", "-q", "--tb=no", "-p",
           "no:cacheprovider"]
    for d in deselect:
        cmd += ["--deselect", d]
    env = {
        **__import__("os").environ,
        "PYTHONIOENCODING": "utf-8",
        # The real panels, read-only; 9.7 GB is not copied per mutation.
        "ORC_FACTS": str(config.FACTS),
        # A ledger of its own, so a mutant can never write to the real N.
        "ORC_LEDGER": str(copy / "ledger" / "trials.sqlite"),
    }
    r = subprocess.run(cmd, cwd=copy, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env, timeout=1800)
    out = (r.stdout or "") + (r.stderr or "")
    return r.returncode, FAILED_LINE.findall(out)


def main(argv: list[str]) -> int:
    if "--list" in argv:
        for m in MUTATIONS:
            print(f"  {m['id']:34s} {m['file']}")
            print(f"  {'':34s} {' '.join(m['why'].split())[:110]}")
        return 0

    broken = verify_targets()
    if broken:
        print("the mutation list no longer matches the code:")
        for b in broken:
            print(f"  - {b}")
        print("\nNothing was measured. Fix the list before trusting a green run.")
        return 2

    work = Path(config.ORC_ROOT / ".mutation")
    started = time.time()
    print(f"copying the tree to {work} (the live one is never mutated)")
    copy = make_copy(work)

    print("baseline: running the suite unmutated")
    rc, baseline_failures = run_suite(copy, [])
    if baseline_failures:
        print(f"  {len(baseline_failures)} test(s) cannot pass in a copy "
              f"(they are about this checkout); deselecting them:")
        for f in baseline_failures[:8]:
            print(f"    {f}")
        rc, still = run_suite(copy, baseline_failures)
        if still or rc != 0:
            print(f"  the baseline is still not green ({len(still)} failing). "
                  "This run measures nothing.")
            return 2
    print(f"  baseline green in {time.time() - started:.0f}s")

    results = []
    for m in MUTATIONS:
        target = copy / m["file"]
        original = target.read_text(encoding="utf-8")
        assert original.count(m["old"]) == 1
        target.write_text(original.replace(m["old"], m["new"], 1), encoding="utf-8")
        try:
            t0 = time.time()
            rc, failed = run_suite(copy, baseline_failures)
        finally:
            target.write_text(original, encoding="utf-8")
        killed = bool(failed) or rc != 0
        results.append({"id": m["id"], "file": m["file"], "why": m["why"],
                        "killed": killed, "killed_by": failed[:4],
                        "seconds": round(time.time() - t0, 1)})
        mark = "KILLED  " if killed else "SURVIVED"
        by = failed[0].split("::")[-1] if failed else "nothing failed"
        print(f"  {mark} {m['id']:34s} {by}")

    survivors = [r for r in results if not r["killed"]]
    report = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "mutations": len(results),
        "killed": len(results) - len(survivors),
        "survived": [r["id"] for r in survivors],
        "baseline_deselected": baseline_failures,
        "seconds": round(time.time() - started, 1),
        "results": results,
    }
    (config.REPORTS / "MUTATION.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    shutil.rmtree(work, ignore_errors=True)

    print(f"\n{report['killed']}/{len(results)} mutations killed in "
          f"{report['seconds']:.0f}s -> reports/MUTATION.json")
    if survivors:
        print("\nSURVIVORS -- the code is fine and the ORACLE is not. Each of "
              "these is a defect the suite would not notice:")
        for r in survivors:
            print(f"  - {r['id']}: {' '.join(r['why'].split())}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
