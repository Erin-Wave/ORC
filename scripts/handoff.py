"""ORC | A hypothesis from outside the loop, checked before it costs anything.

The reasoning layer runs on whatever CLI is installed. A subscription that has
no CLI -- a ChatGPT Plus seat, a colleague, a paper -- can still feed this
project, because nothing downstream cares where an idea came from: intake
hashes the claim and the grid before any result exists, and the guards that
matter are all mechanical. What it cannot do is register something the
evaluator cannot express. Three of the first five proposals died exactly there,
naming parameters the config types do not have, and each one had already spent
a model call and a day.

So this does two things and neither of them is judgement:

  python scripts/handoff.py            write reports/HANDOFF.md -- everything an
                                       outside model needs, including the exact
                                       field names it may use, and nothing it
                                       is not allowed to see
  python scripts/handoff.py --accept <file.json>
                                       expand the answer and say whether it
                                       could run, then place it in the queue

The point of the second one is the turnaround. An unexpandable grid comes back
in a second here instead of six hours later from the worker, with the day's
registration slot already spent.

The holdout is not involved and cannot be: the handoff carries the cycle report
and the field names, which is development-side information only.
"""
from __future__ import annotations

import json
import sys
from dataclasses import fields as dataclass_fields
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    sys.stdout.reconfigure(errors="replace")
except (AttributeError, OSError):                                  # pragma: no cover
    pass

from orc import config                                             # noqa: E402
from orc.eval.signal_rules import RULES                            # noqa: E402
from orc.orchestrator.spec import (SignalTrialConfig, TrialConfig,  # noqa: E402
                                   closed_families, next_hypothesis_id)

# Everything an outside proposer must not have to guess at.  A field that is
# not on this list does not exist, and a grid that names one cannot be run.
SKIP = {"symbol"}                       # supplied by `universe`, never by the grid


def _axes(cls) -> list[str]:
    return [f.name for f in dataclass_fields(cls) if f.name not in SKIP]


def taken_ids() -> dict[str, str]:
    """Every id already spent, and what happened to it. Reusing one overwrites
    the record of why the first was rejected."""
    out = {}
    for state, d in (("registered", config.REGISTRY),
                     ("queued", config.QUEUE),
                     ("killed", config.CONFIGS / "killed"),
                     ("closed", config.CONFIGS / "closed"),
                     ("proposed", config.CONFIGS / "proposed")):
        if d.exists():
            for p in sorted(d.glob("H*.json")):
                out[p.stem] = state
    return out


def write_handoff() -> Path:
    report = config.REPORTS / "CYCLE_REPORT.md"
    if not report.exists():
        raise SystemExit("no reports/CYCLE_REPORT.md yet; run a cycle first")

    ids = taken_ids()
    closed = closed_families()
    L: list[str] = []
    L.append("# ORC hand-off: propose one hypothesis")
    L.append("")
    L.append("You are proposing research on Binance USD-M perpetuals for a project "
             "whose deliverable is a MAP OF WHERE RULES BREAK, not an optimal "
             "setting. A result of FAIL is publishable and closing a family is a "
             "success. Read the rules, then the state of play, then answer with "
             "one JSON object and nothing else.")
    L.append("")
    L.append("## Rules that will get your proposal rejected mechanically")
    L.append("")
    L.append("1. **Name who is structurally paying, and why they keep paying "
             "even though it is known.** \"This pattern backtests well\" is "
             "rejected without being run. A payer with no choice about timing "
             "(a liquidated leveraged long, a hedger who needs immediacy) is a "
             "mechanism; a payer who is simply wrong is not.")
    L.append("2. **Propose a different rule SHAPE, never a finer grid over a "
             "shape already tested.** The parameter space is enumerated "
             "exhaustively, so a narrower grid is noise mining by definition.")
    L.append("3. **Write the kill condition BEFORE any number exists**, as "
             "something computable from the metrics below. It must be able to "
             "close your own family.")
    L.append("4. **Every configuration you enumerate enters an append-only "
             "ledger** whose row count N is the denominator of the "
             f"multiple-testing correction. N is currently **{_n_trials()}** and "
             "can never be reduced. The grid ceiling is "
             f"**{config.MAX_CONFIGURATIONS_PER_HYPOTHESIS}** configurations and a "
             "grid over it is refused whole, not trimmed.")
    L.append("5. **At least one grid axis must have three or more NUMERIC "
             "levels**, or the shape diagnostic cannot run, and an unmeasured "
             "shape is an automatic disqualifier -- every cell would cost N and "
             "none could ever be a finding.")
    L.append("6. Data begins 2020 and **everything from "
             f"{config.HOLDOUT_START} onward is sealed** and physically absent. "
             "Do not propose anything that needs it.")
    L.append("")
    L.append("## Established results -- do not re-litigate these")
    L.append("")
    L.append("- **KT-1**: a long perpetual DCA pays a median funding bill of "
             "**36 % of contributed capital** over three years, 87 % of BTC "
             "settlements positive. Long-side perp accumulation is CLOSED. Worse "
             "than stated: routed through the simulator, the funded 1x long "
             "liquidates on 0.69 of ADAUSDT start dates and 0.82 of SOLUSDT's.")
    L.append("- **KT-2**: liquidation reaches **100 % at 2x and above** for "
             "averaging down. Leverage above 1x is CLOSED for that shape.")
    L.append("- **KT-3**: 986 symbols ever traded, 481 archived, 266 delisted; "
             "the usable delisted sample is still too small. **No alt-basket "
             "hypothesis** until that is resolved.")
    for hid, rec in sorted(closed.items()):
        L.append(f"- **{hid} `{rec.get('family')}`** is CLOSED. "
                 f"{' '.join(str(rec.get('reason', '')).split())[:600]}")
    L.append("")
    L.append("## The fields the evaluator can actually express")
    L.append("")
    L.append("A grid or `fixed` block naming anything not on these lists cannot "
             "be run and will be killed before registration. This is the single "
             "most common way a good idea is wasted here.")
    L.append("")
    L.append("**Track A** (`track: \"A\"`, accumulation: deposits arrive on a "
             "schedule, judged on `tm_q05` and annualised MWRR because there is "
             "no fixed capital to compute a CAGR against):")
    L.append("")
    L.append("```\n" + "\n".join(f"  {a}" for a in _axes(TrialConfig)) + "\n```")
    L.append("`gate` is a string: `\"none\"`, `\"dip:<drop>:<lookback_days>\"` "
             "(e.g. `\"dip:0.20:30\"`), or `\"sma:<days>\"`. `take_profit` and "
             "`stop_loss` are fractions of the position's own margin.")
    L.append("")
    L.append("**Track B** (`track: \"B\"`, one position at a time from fixed "
             "capital, entered long or short on a signal and closed on a signal, "
             "stop or liquidation; judged on Calmar, CAGR, max equity drawdown "
             "and Sharpe):")
    L.append("")
    L.append("```\n" + "\n".join(f"  {a}" for a in _axes(SignalTrialConfig)) + "\n```")
    L.append(f"`rule` must be one of: {sorted(RULES)}. A rule that does not "
             "exist in the code cannot be proposed -- if your idea needs a new "
             "signal generator, say so in the claim and it will be written "
             "first, rather than registering a grid that cannot run.")
    L.append("")
    L.append("## What counts as a finding")
    L.append("")
    L.append("A cell must clear ALL of: shape not SPIKE (a peak whose "
             "neighbours are worse and of the opposite sign is a grid corner, "
             "not a mechanism); enough effective independent paths (millions of "
             "overlapping start offsets over six years are still a handful of "
             "experiments); PBO below 0.5 (at 0.5 the selection carries no "
             "information at all); a p-value against a null built by re-running "
             "the SAME grid on bootstrapped histories; and a robustness gate of "
             "doubled costs, walk-forward, regime split and minute-bar "
             "execution. Nothing has cleared all of them yet.")
    L.append("")
    L.append("## Answer with exactly this, and nothing else")
    L.append("")
    L.append("```json")
    L.append(json.dumps({
        "hypothesis_id": next_hypothesis_id(),
        "track": "B",
        "family": "short_lowercase_with_underscores",
        "claim": "Who is structurally paying, why they keep paying even though "
                 "it is known, and what would have to be true for this to be a "
                 "mechanism rather than a pattern. Several sentences.",
        "kill_condition": "The computable result that would close this family, "
                          "written now, before any number exists.",
        "universe": ["BTCUSDT", "ETHUSDT"],
        "grid": {"an_axis_from_the_lists_above": [1, 2, 3]},
        "fixed": {"another_field_from_the_lists_above": 1.0},
    }, indent=2))
    L.append("```")
    L.append("")
    L.append(f"Ids already spent, do not reuse: "
             f"{', '.join(f'{k} ({v})' for k, v in sorted(ids.items())) or 'none'}. "
             f"Use `{next_hypothesis_id()}`.")
    L.append("")
    L.append("---")
    L.append("")
    L.append("## The state of play")
    L.append("")
    L.append("Everything below is development data. The ranking is not a result; "
             "read the shape column and the independent-path count first.")
    L.append("")
    L.append(report.read_text(encoding="utf-8"))

    out = config.REPORTS / "HANDOFF.md"
    out.write_text("\n".join(L), encoding="utf-8")
    return out


def _n_trials() -> int:
    try:
        from orc.ledger.trials import Ledger
        with Ledger() as led:
            return led.total_trials()
    except Exception:                                              # noqa: BLE001
        return 0


def accept(path: Path) -> int:
    """Expand an outside proposal and say whether it could run.

    This is the same check the reasoning layer runs before its own proposals
    reach the queue, and it is deliberately mechanical: it asks whether the
    machine can express the hypothesis, never whether the hypothesis is any
    good. Judgement stays with the adversary.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from reasoning import expandable

    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        print(f"cannot read {path}: {exc}")
        return 2

    hid = raw.get("hypothesis_id", "")
    spent = taken_ids()
    if hid in spent:
        print(f"REJECTED  {hid} is already {spent[hid]}; reusing the id would "
              f"overwrite the record of it. Use {next_hypothesis_id()}.")
        return 1

    staged = config.CONFIGS / "proposed" / f"{hid or 'UNNAMED'}.json"
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
    why = expandable(staged)
    if why:
        print(f"REJECTED  {hid}: {why}")
        print("\nNothing was registered and N is unchanged. Fix the proposal and "
              "run this again; the field lists in reports/HANDOFF.md are what "
              "the evaluator can express.")
        staged.unlink()
        return 1

    from orc.orchestrator.spec import Hypothesis
    h = Hypothesis(**json.loads(staged.read_text(encoding="utf-8")))
    h.register()
    print(f"EXPANDS   {hid}  {h.family}  {h.size()} configurations, "
          f"track {h.track}")
    print(f"          left in configs/proposed/{staged.name}")
    print("\nIt can run. Whether it SHOULD is the adversary's call, which is the "
          "next reasoning cycle -- it reviews what is waiting in "
          "configs/proposed/ before asking for anything new, and every available "
          "provider gets a veto. Nothing has entered the ledger yet.")
    return 0


def main(argv: list[str]) -> int:
    if argv and argv[0] == "--accept":
        if len(argv) < 2:
            print("usage: python scripts/handoff.py --accept <file.json>")
            return 2
        return accept(Path(argv[1]))
    out = write_handoff()
    print(f"written: {out}  ({out.stat().st_size:,} bytes)")
    print("\nPaste it whole into any model. Save the JSON it answers with and run:")
    print("  python scripts/handoff.py --accept <that file>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
