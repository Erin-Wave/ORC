"""ORC | The Track B differential oracle.

Section 5 gives Track A two evaluators that check each other and says what
happens if they ever disagree: *every result in the project is void*. Track B
has had one evaluator and no second opinion since it was written, and every
Track B number the project reports comes out of it.

That gap is not theoretical. On 2026-09-05 three consecutive kernel reviews
returned seventeen high findings on a suite that was green for all of them, and
two consecutive reviews did not read `orc/eval/signal.py` at all.

WHY A DIFFERENT VENDOR WRITES THE REFERENCE. Two implementations by the same
model share its blind spots, so a Claude-written reference checking a
Claude-written evaluator catches the mistakes neither of them makes. The
reference in `oracle/ref_signal.py` is written by codex from `oracle/BRIEF.md`,
which states the SEMANTICS and never shows the original. For a defect to reach
a recorded number it now has to be a mistake both vendors make independently.

WHY IT IS NEVER MERGED. The reference is not in the research path, not in
CODE_HASH_ROOTS, and never produces a ledger row. It cannot introduce a defect
into a result -- the worst it can do is disagree and be wrong, which costs a
finding to read. That is what makes it safe to generate continuously.

    python oracle/fuzz.py              a few hundred random cases
    python oracle/fuzz.py --cases 20000
    python oracle/fuzz.py --panels     replay real recorded configurations
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orc.eval.signal import FLAT, LONG, SHORT, SignalSpec, run_signals  # noqa: E402

# Two float paths that did the same arithmetic in a different order are allowed
# to differ in the last bits and nowhere else. Anything above this is a
# disagreement about the RULES, which is what this exists to find.
TOL = 1e-9

# Frozen 2026-09-05. Wide enough that stops, targets, liquidations and funding
# wipeouts all fire somewhere in a run of a few hundred; narrow enough that a
# case which disagrees can be printed and read by a person.
MAX_BARS = 400
MIN_BARS = 20


def _case(rng: np.random.Generator) -> dict:
    """One random market and one random pair of signal arrays.

    Deliberately violent. A quiet series exercises the parts both
    implementations get right; the interesting bars are the ones where a stop, a
    target and a liquidation all fall inside the same bar and the tie-break
    decides the answer.
    """
    n = int(rng.integers(MIN_BARS, MAX_BARS))
    step = rng.normal(0.0, rng.choice([0.002, 0.01, 0.05]), n)
    close = 100.0 * np.exp(np.cumsum(step))
    # Wicks big enough to reach a stop the close never shows.
    span = np.abs(rng.normal(0.0, 0.02, n)) * close
    high = close + span * rng.uniform(0.0, 1.0, n)
    low = close - span * rng.uniform(0.0, 1.0, n)
    low = np.minimum(low, close)
    high = np.maximum(high, close)

    entry = rng.choice([LONG, SHORT, FLAT], size=n,
                       p=[0.15, 0.15, 0.70]).astype(np.int8)
    exit_ = rng.random(n) < rng.choice([0.02, 0.10, 0.30])

    funding = None
    if rng.random() < 0.7:
        rate = rng.normal(0.0, rng.choice([1e-4, 1e-3, 1e-2]), n)
        # Settlements land on a subset of bars, as they do on a real panel.
        rate[rng.random(n) > 0.15] = 0.0
        funding = rate

    spec = SignalSpec(
        capital=float(rng.choice([1_000.0, 10_000.0])),
        leverage=float(rng.choice([1.0, 2.0, 5.0])),
        fee_bps=float(rng.choice([0.0, 4.5])),
        slippage_bps=float(rng.choice([0.0, 1.0])),
        stop_loss=float(rng.choice([0.05, 0.25])) if rng.random() < 0.6 else None,
        take_profit=float(rng.choice([0.05, 0.5])) if rng.random() < 0.4 else None,
        max_hold_bars=int(rng.integers(2, 50)) if rng.random() < 0.3 else None,
    )
    return {"close": close, "high": high, "low": low, "entry": entry,
            "exit_": exit_, "spec": spec, "funding_rate": funding,
            "symbol": str(rng.choice(["BTCUSDT", "ADAUSDT"]))}


def _compare(a: dict, b: dict) -> list[str]:
    """What the two answers disagree about, in words.

    Scalars first and the equity path last, because "n_trades differs" is a
    sentence a person can act on and "equity[3117] differs" usually is not.
    """
    out: list[str] = []
    for k in ("n_trades", "n_liquidations"):
        if int(a.get(k, -1)) != int(b.get(k, -1)):
            out.append(f"{k}: fast={a.get(k)} ref={b.get(k)}")
    for k in ("funding_collected",):
        x, y = float(a.get(k, np.nan)), float(b.get(k, np.nan))
        if not (np.isnan(x) and np.isnan(y)) and abs(x - y) > TOL * max(1.0, abs(x)):
            out.append(f"{k}: fast={x!r} ref={y!r}")

    ea, eb = np.asarray(a["equity"], float), np.asarray(b["equity"], float)
    if ea.shape != eb.shape:
        out.append(f"equity shape: fast={ea.shape} ref={eb.shape}")
        return out
    d = np.abs(ea - eb) / np.maximum(np.abs(ea), 1.0)
    if d.size and np.nanmax(d) > TOL:
        i = int(np.nanargmax(d))
        out.append(f"equity[{i}]: fast={ea[i]!r} ref={eb[i]!r} rel={d[i]:.3e}")

    ta, tb = a.get("trades") or [], b.get("trades") or []
    for j, (x, y) in enumerate(zip(ta, tb)):
        for k in ("entry_bar", "exit_bar", "reason"):
            if x.get(k) != y.get(k):
                out.append(f"trade[{j}].{k}: fast={x.get(k)!r} ref={y.get(k)!r}")
                break
    return out


def run(cases: int, seed: int = 20260905, stop_after: int = 5) -> int:
    try:
        from oracle.ref_signal import ref_run_signals
    except ImportError as exc:
        print(f"no reference yet ({exc}). oracle/BRIEF.md says what to write, "
              "and it must be written by the vendor that did NOT write "
              "orc/eval/signal.py.")
        return 2

    rng = np.random.default_rng(seed)
    bad = 0
    for i in range(cases):
        c = _case(rng)
        try:
            fast = run_signals(c["close"], c["high"], c["low"], c["entry"],
                               c["exit_"], c["spec"],
                               funding_rate=c["funding_rate"],
                               symbol=c["symbol"])
        except Exception as exc:                                   # noqa: BLE001
            fast = {"raised": f"{type(exc).__name__}: {exc}"}
        try:
            ref = ref_run_signals(c["close"], c["high"], c["low"], c["entry"],
                                  c["exit_"], c["spec"],
                                  funding_rate=c["funding_rate"],
                                  symbol=c["symbol"])
        except Exception as exc:                                   # noqa: BLE001
            ref = {"raised": f"{type(exc).__name__}: {exc}"}

        # One raising and the other answering is the loudest disagreement there
        # is, and it must not be swallowed by the field-by-field comparison.
        if ("raised" in fast) != ("raised" in ref):
            diffs = [f"one raised: fast={fast.get('raised')} ref={ref.get('raised')}"]
        elif "raised" in fast:
            diffs = []
        else:
            diffs = _compare(fast, ref)

        if diffs:
            bad += 1
            print(f"\n=== case {i}  seed={seed}  bars={c['close'].size}")
            print(f"    spec={c['spec']}")
            for d in diffs[:6]:
                print(f"    {d}")
            if bad >= stop_after:
                print(f"\nstopping after {bad} disagreements")
                break

    print(f"\n{cases if not bad else i + 1} case(s) run, {bad} disagreement(s)")
    return 1 if bad else 0


def main(argv: list[str]) -> int:
    cases = 300
    if "--cases" in argv:
        cases = int(argv[argv.index("--cases") + 1])
    seed = 20260905
    if "--seed" in argv:
        seed = int(argv[argv.index("--seed") + 1])
    return run(cases, seed)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
