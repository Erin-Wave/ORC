"""ORC | What an autonomous step may not do quietly.

The suite being green is evidence, not proof, and the reason is structural: the
same agent writes the code, writes the test, runs it, reads the result and
declares it done. That is one party setting the exam, marking it and awarding
the grade. Every check in this project is worth exactly as much as its
resistance to being edited by whoever it is checking.

So this module names the things that may not be weakened silently, and
`scripts/precommit.py` enforces it in a `commit-msg` hook. Nothing here is a
ban. Each refusal has one way through: a line in the commit message that says
what is being loosened and why. That is the whole design -- moving a frozen
threshold stops being an edit nobody notices and becomes a sentence in the
permanent history, greppable with `git log --grep`, exactly the way
`Hypothesis.verify()` makes "adjust the grid until it works" a visible act.

Three separate incidents in this repository are why:

  - a provider running under `--sandbox read-only` appended four tests to
    tests/test_protocol.py during a reasoning pass, and nothing stopped it;
  - a 193-line file written by a review step went into a commit unread,
    through `git add -A`;
  - six defects entered in one session, every one of them the same habit --
    a claim made without a check that would have failed if it were false.

None of those was caught by a model thinking harder about it.
"""
from __future__ import annotations

import ast
import re

# --------------------------------------------------------------------------
# Paths whose whole job is to be the thing that says no
# --------------------------------------------------------------------------
# A change here is not forbidden -- the suite has to be able to grow, and the
# gate has to be able to get stricter. What is forbidden is a change that makes
# them check LESS, and the checks below are about direction, not about touching.
PROTECTED_PREFIXES = (
    "tests/",                  # the oracle
    "scripts/precommit.py",    # the gate
    "orc/guard.py",            # this file
    "orc/holdout.py",          # the three openings
    "ledger/",                 # N, and the final-test counter
    "configs/registry/",       # pre-registered claims and grids
    "configs/closed/",         # answered questions
)

# --------------------------------------------------------------------------
# Numbers that were frozen before results were seen
# --------------------------------------------------------------------------
# Section 11 of the constitution says every threshold is a constant with a
# comment saying when it was frozen. The comment is a promise; this is the
# check. Moving one of these after seeing a result is the single most effective
# way to manufacture a finding, and it takes one character.
FROZEN_CONSTANTS = (
    # the seal and the stop condition
    "HOLDOUT_START", "MAX_FINAL_TESTS", "TARGET_CAGR", "TARGET_MAX_DRAWDOWN",
    "MIN_SYMBOLS",
    # what a search may cost
    "MAX_CONFIGURATIONS_PER_HYPOTHESIS", "MAX_PROBE_CONFIGURATIONS",
    "MAX_REGISTRATIONS_PER_DAY",
    # what disqualifies a cell
    "PBO_USELESS", "FEW_PATHS", "SPIKE_SHAPES", "BREAK_EVEN",
    # what a candidate must survive
    "COST_STRESS_MULTIPLIERS", "MAX_RELATIVE_DRIFT", "REGIME_WINDOW_DAYS",
    # data hygiene
    "MAX_MISSING_BAR_FRACTION", "MIN_BARS_REQUIRED", "TAKER_FEE_BPS",
    "MAKER_FEE_BPS", "SLIPPAGE_BPS",
)

# --------------------------------------------------------------------------
# How much one commit may change
# --------------------------------------------------------------------------
# Not a quality metric. A large diff from an autonomous step is hard to review,
# and an unreviewed diff is where the last six defects lived. The numbers are
# generous on purpose: they should bind a session that kept going, not ordinary
# work. Reports and the ledger are excluded because they are generated.
MAX_FILES = 12
MAX_LOC = 600
GENERATED_PREFIXES = ("reports/", "ledger/", "facts/", "dist/")

# The one way through each refusal. A marker is a sentence in the permanent
# record, not a flag on a command line, so it survives the session that wrote
# it and can be found later.
MARKERS = {
    "tests": "WEAKENS-TESTS:",
    "threshold": "MOVES-A-FROZEN-THRESHOLD:",
    "budget": "BUDGET-OVERRIDE:",
    "holdout": "TOUCHES-THE-HOLDOUT:",
}

# Both of these read the SYNTAX TREE and not the text, and the first version of
# this file is why. It counted `@pytest.mark.skip` with a regex, and the tests
# written to prove the guard works contain that decorator inside a string
# literal -- so the very commit that added the guard was refused by it, for a
# skip that does not exist. A check that fires on its own documentation is worse
# than no check: it teaches whoever meets it to reach for --no-verify.
_SKIP_DECORATORS = {"skip", "skipif", "xfail"}
_SKIP_CALLS = {"skip", "xfail"}


def _dotted(node) -> str:
    """`pytest.mark.skipif` from the attribute chain, or "" for anything else."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _parse(text: str):
    try:
        return ast.parse(text or "")
    except SyntaxError:
        # A test file that does not parse cannot be reasoned about, and it does
        # not need to be: the suite check in pre-commit has already refused it.
        return None


def has_marker(message: str, kind: str) -> bool:
    """Is the loosening declared in the commit message?

    Case-sensitive and anchored at a line start: a marker has to be written on
    purpose. `git log --grep` is the reason the text matters -- these lines are
    meant to be found years later by someone asking when a threshold moved.
    """
    token = MARKERS[kind]
    return any(line.lstrip().startswith(token)
               for line in (message or "").splitlines())


def test_functions(text: str) -> set[str] | None:
    """Names of the test functions this file defines.  None if it cannot parse."""
    tree = _parse(text)
    if tree is None:
        return None
    return {n.name for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name.startswith("test_")}


def _skips(text: str) -> int | None:
    """How many tests are decorated or short-circuited out of running."""
    tree = _parse(text)
    if tree is None:
        return None
    n = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                target = dec.func if isinstance(dec, ast.Call) else dec
                name = _dotted(target)
                if name.startswith("pytest.mark.") and \
                        name.rsplit(".", 1)[-1] in _SKIP_DECORATORS:
                    n += 1
        elif isinstance(node, ast.Call):
            name = _dotted(node.func)
            if name.startswith("pytest.") and name.rsplit(".", 1)[-1] in _SKIP_CALLS:
                n += 1
    return n


def test_weakening(path: str, before: str | None, after: str | None) -> list[str]:
    """Every way this edit makes the oracle check less than it did.

    Adding tests is free and always will be. What needs a sentence in the
    message is a test that stopped existing, stopped running, or stopped being
    reached -- the three shapes of "the suite is green now".
    """
    if not path.startswith("tests/") or not path.endswith(".py"):
        return []
    if before is None:                       # a new test file adds oracle
        return []
    if after is None:
        return [f"{path} would be deleted, with "
                f"{len(test_functions(before))} test(s) in it"]

    was, now = test_functions(before), test_functions(after)
    if was is None or now is None:
        return []

    out = []
    gone = sorted(was - now)
    # A rename is not a weakening, and the first version of this could not tell
    # the two apart: renaming test_the_commit_message_gate_is_installed_as_a_hook
    # to test_the_installer_wires_both_halves_of_the_gate read as a deleted
    # test and would have demanded a WEAKENS-TESTS: line for a commit that
    # deleted nothing. A gate that cries wolf is a gate people learn to bypass,
    # so the count decides and the names only describe.
    #
    # What this deliberately cannot catch: a test deleted and replaced by a
    # weaker one, which keeps the count level. No text comparison can -- that
    # is what scripts/mutation.py is for, and it is why the mutation gate runs
    # daily rather than as a formality.
    if gone and len(now) < len(was):
        out.append(f"{path}: {len(was) - len(now)} fewer test(s); gone from this "
                   f"file: {', '.join(gone[:6])}"
                   f"{' ...' if len(gone) > 6 else ''}")
    a, b = _skips(before), _skips(after)
    if a is not None and b is not None and b > a:
        out.append(f"{path}: {b - a} new skip/xfail marker(s); a test that does "
                   "not run is not a test that passes")
    return out


def frozen_touched(diff: str) -> list[str]:
    """Frozen constants whose defining line the staged diff removes or rewrites.

    Reads the REMOVED side of the diff, because that is the half that says a
    value which already existed is going away. A new constant with one of these
    names is not a loosening and is not flagged.
    """
    hits = []
    for line in (diff or "").splitlines():
        if not line.startswith("-") or line.startswith("---"):
            continue
        body = line[1:].strip()
        for name in FROZEN_CONSTANTS:
            if re.match(rf"^{re.escape(name)}\s*(:[^=]+)?=", body):
                hits.append(f"{name}  (was: {body[:80]})")
    return sorted(set(hits))


def budget(numstat: list[tuple[int, int, str]]) -> tuple[int, int, list[str]]:
    """(files, changed LOC, paths counted).  Generated trees do not count."""
    paths = [p for _, _, p in numstat
             if not any(p.startswith(g) for g in GENERATED_PREFIXES)]
    loc = sum(a + d for a, d, p in numstat
              if not any(p.startswith(g) for g in GENERATED_PREFIXES))
    return len(paths), loc, sorted(paths)


def over_budget(numstat) -> str | None:
    files, loc, _ = budget(numstat)
    if files <= MAX_FILES and loc <= MAX_LOC:
        return None
    return (f"{files} file(s) and {loc} changed line(s), over the budget of "
            f"{MAX_FILES} files / {MAX_LOC} lines. A large autonomous diff is "
            "the one nobody reviews. Split it, or say why it has to be one "
            "commit.")


def holdout_regression(before: str | None, after: str | None) -> list[str]:
    """The counter may only go up, and the ceiling may not.

    `openings_used()` already resolves every disagreement upward so that no
    accident can manufacture a look at the sealed data. This is the same rule
    applied to the source: three openings for the life of the project is the
    strongest guarantee here and it is one edit away from four.
    """
    if before is None or after is None:
        return []

    def ceiling(text: str) -> int | None:
        m = re.search(r"^MAX_FINAL_TESTS\s*=\s*(\d+)", text or "", re.M)
        return int(m.group(1)) if m else None

    a, b = ceiling(before), ceiling(after)
    if a is not None and b is not None and b > a:
        return [f"MAX_FINAL_TESTS would go from {a} to {b}. The holdout is "
                "three openings for the life of the project."]
    return []
