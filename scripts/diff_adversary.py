"""ORC | The gate the code never had.

A hypothesis passes an adversary before it can reach the ledger, and any one
provider can refuse it. Sixteen proposals have been killed that way. CODE has
had no such gate: it lands, and a kernel review reads it a day later.

That asymmetry is the shape of 2026-09-05. Forty-four commits, seven of them
touching the evaluators, seventeen new high findings -- two of them inside
fixes landed an hour before the review that caught them. Every one was found on
a green suite, because the tests were written AFTER the review said what was
wrong.

So: the same device, pointed at a diff.

THE VENDOR THAT WROTE IT DOES NOT JUDGE IT. That is the whole mechanism and it
is not a courtesy. Two calls to the same model share its blind spots, so
Claude reviewing Claude's diff finds the mistakes neither of them makes -- which
is none of the interesting ones. The reviewer is chosen as the OTHER provider,
and if only one is available the gate says so and declines rather than
pretending a self-review happened.

WHAT IT IS ASKED. Not "is this good code". The question is the one the kernel
reviews actually answer, asked before the code lands instead of after:

  can this change make a recorded number wrong, and how

REFUSAL IS THE DEFAULT ON DOUBT. A gate that passes when unsure is a gate that
passes, and this one costs a minute against a defect that costs a day and a
generation of N.

    python scripts/diff_adversary.py            judge the staged diff
    python scripts/diff_adversary.py --range HEAD~1..HEAD
    python scripts/diff_adversary.py --install  as a pre-commit step
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    sys.stdout.reconfigure(errors="replace")
except (AttributeError, OSError):                                  # pragma: no cover
    pass

from orc import config, llm  # noqa: E402

# Beyond this the reviewer is reading a wall rather than a change, and a
# reviewer that skims is worse than none because it produces a PASS. A diff
# this large already has to justify itself to the budget check.
MAX_DIFF_CHARS = 60_000

# Paths where a defect can reach a recorded number. A change confined outside
# them can still be wrong; it cannot silently corrupt the ledger, so the gate
# reports and does not block.
RESEARCH_PATH = ("orc/kernel/", "orc/eval/", "orc/orchestrator/",
                 "orc/facts/", "orc/ledger/", "orc/holdout.py",
                 "orc/target.py", "orc/config.py")

PROMPT = """You are reviewing a code change to a research system BEFORE it
lands. You did not write it. Another model did.

Answer one question and no others:

    CAN THIS CHANGE MAKE A RECORDED NUMBER WRONG, AND HOW?

Not style. Not naming. Not whether you would have written it differently. This
project's failures are all one shape -- a plausible number where a refusal
belonged, an absence read as a value, two code paths that must agree and do
not -- and every one of them passed a green test suite.

Look hardest for:
  - a value that means two things (0.0 as "zero" and as "no record")
  - an index or a window that is bounded on one side only
  - two places that must stay in step, where only one was changed
  - a function that returns a plausible number for an input it cannot answer
  - a docstring or comment describing behaviour the code does not have
  - a check whose failure mode is to silently pass

Reply with ONE JSON object and nothing else:

{{"verdict": "PASS" or "BLOCK",
  "why": "one paragraph, concrete, naming the file and line if you can",
  "worst_case": "the wrong number this produces, or empty if PASS"}}

BLOCK if you are unsure. A gate that passes on doubt is not a gate, and this
one costs a minute against a defect that costs a day.

THE DIFF:

{diff}
"""


def staged_diff(rng: str | None = None) -> str:
    args = ["git", "diff", "--unified=3"]
    args += [rng] if rng else ["--cached"]
    r = subprocess.run(args, cwd=config.ORC_ROOT, capture_output=True,
                       text=True, encoding="utf-8", errors="replace",
                       check=False)
    return r.stdout or ""


def touches_research(diff: str) -> bool:
    for line in diff.splitlines():
        if line.startswith("+++ b/") or line.startswith("--- a/"):
            p = line[6:].strip()
            if any(p.startswith(d) for d in RESEARCH_PATH):
                return True
    return False


def reviewers(author: str | None) -> list[str]:
    """Every ready provider except the one that wrote the change.

    An empty list is the honest answer when only the author is available, and
    the caller declines rather than letting a model mark its own exam -- which
    is the exact failure section 12 lists first.
    """
    ready = [p for p, s in llm.availability().items() if s == "ready"]
    return [p for p in ready if p != author]


def judge(diff: str, author: str = "claude") -> dict:
    if not diff.strip():
        return {"verdict": "PASS", "why": "empty diff", "worst_case": ""}
    if len(diff) > MAX_DIFF_CHARS:
        return {"verdict": "BLOCK",
                "why": f"the diff is {len(diff):,} characters, past the "
                       f"{MAX_DIFF_CHARS:,} a reviewer can read without "
                       "skimming. Split it.",
                "worst_case": "a reviewer that skims returns PASS"}

    who = reviewers(author)
    if not who:
        return {"verdict": "BLOCK",
                "why": f"no provider other than {author!r} is available, and a "
                       "model reviewing its own change finds the mistakes it "
                       "does not make",
                "worst_case": "an unreviewed change to the research path"}

    try:
        out = llm.ask_json(PROMPT.format(diff=diff), provider=who[0],
                           tools=("Read", "Glob", "Grep"),
                           cwd=config.ORC_ROOT)
    except Exception as exc:                                       # noqa: BLE001
        return {"verdict": "BLOCK",
                "why": f"the reviewer ({who[0]}) could not be reached: "
                       f"{type(exc).__name__}: {exc}",
                "worst_case": "an unreviewed change to the research path"}
    out["reviewer"] = who[0]
    return out


def main(argv: list[str]) -> int:
    rng = argv[argv.index("--range") + 1] if "--range" in argv else None
    author = argv[argv.index("--author") + 1] if "--author" in argv else "claude"

    diff = staged_diff(rng)
    if not diff.strip():
        print("diff adversary: nothing staged")
        return 0
    if not touches_research(diff) and "--always" not in argv:
        print("diff adversary: nothing in the research path; not gated")
        return 0

    v = judge(diff, author=author)
    mark = "PASS " if v.get("verdict") == "PASS" else "BLOCK"
    print(f"diff adversary [{v.get('reviewer', '-')}]: {mark}")
    print(f"  {v.get('why', '')}")
    if v.get("worst_case"):
        print(f"  worst case: {v['worst_case']}")
    return 0 if v.get("verdict") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
