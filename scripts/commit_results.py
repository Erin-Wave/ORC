"""ORC | Land the cycle's results, from wherever the cycle happened.

This was a shell block inside `.github/workflows/orc-cycle.yml`, running once,
at the END of the job -- after the resident "keep working for the rest of the
window" step. The cycle itself finishes in the first few minutes, so on
2026-09-04 H0017's ninety rows were computed at 07:07Z and would have reached
the repository at about 12:00Z: five hours in which the question was answered
and nobody could see the answer, `python -m orc.target` still said the ledger
held 6,848 trials, and the local tree still showed H0017 waiting in the queue.

Nothing about that was a fault. It was one commit step in the wrong place, and
the reason it had to be there is that it carries the merge-driver setup: the
ledger is a binary SQLite file two machines write to, and run #19 computed 112
trials over 39 minutes and lost every one of them to a rebase that stopped on
a derived report. So the setup moves here, to ONE place that can be called
twice -- right after the cycle, and again at the end of the job -- rather than
being duplicated into a second shell block, which is how two copies of a merge
policy drift and one of them is the one that runs.

    python scripts/commit_results.py                    the default message
    python scripts/commit_results.py --message "..."    a specific one
    python scripts/commit_results.py --configure-only   the merge policy, only

`--configure-only` is for the resident-window step, which commits through
forever.py's own land() and needs the drivers set in case a rebase happens
there. It used to set them with its own copy of the four git config lines --
two copies of a merge policy, and the one that drifts is the one that runs.

Exit 0 when it landed OR when there was nothing to land -- the second is the
common case for the end-of-job call, since the first one has already pushed.
Exit 1 only when three attempts could not land real work, which means the
merge drivers are not doing their job and a human has to look.
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The directories a cycle writes, named rather than swept.  `git add -A .`
# would stage whatever else happened to be in the tree -- which is how a
# 193-line file written by a review step went into a commit unread. These are
# directories rather than files because the report names are dynamic
# (H0017_SURFACE.json appears the first time H0017 is registered) and a list
# that cannot be complete would silently drop the new ones.
STAGED = ("reports", "ledger", "configs/registry", "configs/queue",
          "configs/closed")

# Rows are the one thing in this project that must never be resolved by picking
# a side, so the ledger gets a union driver and the derived reports get `ours`,
# which the next cycle regenerates anyway.
MERGE_DRIVERS = (
    ("merge.orcledger.name", "union the ORC trial ledger"),
    ("merge.orcledger.driver", "python scripts/merge_ledger.py %O %A %B"),
    ("merge.ours.name", "keep the published version"),
    ("merge.ours.driver", "true"),
)

# The collision window is the length of a cycle, and anything can land in it.
ATTEMPTS = 3


def _git(*args: str, check: bool = False,
         quiet: bool = False) -> subprocess.CompletedProcess:
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    if out and not quiet:
        print(out)
    if err and not quiet:
        print(err, file=sys.stderr)
    if check and r.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {err[:200]}")
    return r


def configure(identity: bool = True) -> None:
    """Merge policy first, identity only when there is not one already.

    On the runner there is no committer identity at all; on the workstation
    there is one and it belongs to the owner. Overwriting it would put
    `orc-cycle` on a human's commits.
    """
    for key, value in MERGE_DRIVERS:
        _git("config", key, value)
    if not identity:
        return
    if not _git("config", "user.email", quiet=True).stdout.strip():
        _git("config", "user.name", "orc-cycle")
        _git("config", "user.email", "orc-cycle@users.noreply.github.com")


def _unpushed() -> int:
    """Commits on this branch that the upstream does not have, or 0 if it
    cannot be told (no upstream, detached head, no remote)."""
    r = _git("rev-list", "--count", "@{u}..HEAD", quiet=True)
    if r.returncode != 0:
        return 0
    try:
        return int((r.stdout or "0").strip() or 0)
    except ValueError:
        return 0


def land(message: str | None = None) -> int:
    configure()
    present = [p for p in STAGED if (ROOT / p).exists()]
    if not present:
        print("nothing to stage")
        return 0
    _git("add", "-A", *present)
    if _git("diff", "--cached", "--quiet").returncode == 0:
        # Nothing to stage is NOT the same as nothing to send. A previous
        # push can have failed -- forever.py's land() reports a rejection and
        # deliberately does not retry -- leaving a real commit sitting on this
        # machine only. Returning here on "no change" is how that commit stays
        # there forever, which is the "stuck push" the notifier watches for:
        # the question exists on exactly one machine and will never be
        # answered. Found by running this script against a clone that had a
        # committed-but-unpushed ledger.
        behind = _unpushed()
        if not behind:
            print("no change")
            return 0
        print(f"nothing new to stage, but {behind} commit(s) have not been "
              "pushed; sending those")
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
        _git("commit", "-m", message or f"orc cycle {stamp}", check=True)

    for attempt in range(1, ATTEMPTS + 1):
        if _git("pull", "--rebase", "--autostash").returncode == 0:
            if _git("push").returncode == 0:
                print(f"pushed on attempt {attempt}")
                return 0
            print(f"push rejected on attempt {attempt}; someone got there first")
            continue
        print(f"rebase did not complete cleanly on attempt {attempt}")
        _git("rebase", "--abort")
        _git("status", "--short")

    print(f"::error::could not land the cycle after {ATTEMPTS} attempts. The "
          "trials are deterministic and the next cycle recomputes them, but "
          "the merge drivers or .gitattributes are not doing their job.",
          file=sys.stderr)
    return 1


def main(argv: list[str]) -> int:
    if "--configure-only" in argv:
        configure()
        print("merge drivers and committer identity configured")
        return 0
    message = None
    if "--message" in argv:
        message = argv[argv.index("--message") + 1]
    return land(message)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
