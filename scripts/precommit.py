"""ORC | Refuse a commit that has not been checked.

Six defects were introduced into this project in one session, all by the same
habit: claiming something was done without checking it. A one-line prompt
"verified" a provider whose real 2 KB payload arrived empty. A commit message
said a split vote was raised as news while nothing read the file. Another said
tm_q05 was still evaluated against its kill condition after it had fallen out
of the report. A file written by a review step was committed unread by
`git add -A`.

Resolutions do not survive a long session. Checks do, so the checkable part of
that habit lives here and runs on every commit:

  tests          the suite must be green. It takes three seconds and it is the
                 only thing standing between a claim and a regression.
  weakening      a commit that makes the ORACLE check less -- a deleted test, a
                 new skip, a frozen threshold moved, the holdout ceiling raised
                 -- is refused unless the message says so in a marker line. Not
                 a ban: a declaration. The agent that writes the code must not
                 also be able to quietly edit what decides whether it worked.
  budget         a diff over orc.guard.MAX_FILES / MAX_LOC is refused unless the
                 message says why it had to be one commit. A large autonomous
                 diff is the one nobody reviews.
  new files      a file appearing at the top level, or anywhere unexpected, has
                 to be named on purpose. AGENTS.md arrived that way -- 193 lines
                 written into the tree by a review step that was documented as
                 read-only -- and went into a commit without being read.
  ledger         ledger/trials.sqlite may not shrink. N can only grow, and a
                 commit that removes rows is a deleted experiment.
  conflicts      no file with conflict markers, ever.

The suite check runs in `pre-commit`; the marker checks run in `commit-msg`,
because a pre-commit hook cannot see the message it is about to be given --
`.git/COMMIT_EDITMSG` still holds the PREVIOUS commit's text at that point, so
a marker read there would be answering about the wrong commit.

Install:  python scripts/precommit.py --install
Bypass:   git commit --no-verify   (and say why in the message)
"""
from __future__ import annotations

import os
import subprocess
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orc import guard                                              # noqa: E402

# Where a new file may appear without being announced. Anything else -- a new
# top-level file above all -- has to be deliberate, because that is where a tool
# writing into the tree lands.
EXPECTED_DIRS = ("orc/", "scripts/", "tests/", "configs/", "reports/",
                 "ledger/", ".github/")

ALLOWED_TOP_LEVEL = {
    "CLAUDE.md", "AGENTS.md", "README.md", "MANUAL_SETUP.md", "LICENSE",
    "requirements.txt", ".gitignore", ".gitattributes", "pyproject.toml",
    "pytest.ini", "setup.cfg",
}

HOOK = """#!/bin/sh
exec python "$(git rev-parse --show-toplevel)/scripts/precommit.py"
"""

MSG_HOOK = """#!/bin/sh
exec python "$(git rev-parse --show-toplevel)/scripts/precommit.py" --message "$1"
"""


def _git(*args: str) -> str:
    r = subprocess.run(["git", *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=ROOT)
    return r.stdout


def staged() -> list[tuple[str, str]]:
    """(status, path) for everything staged.  A = added, M = modified, D = deleted."""
    out = []
    for line in _git("diff", "--cached", "--name-status").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            out.append((parts[0][:1], parts[-1]))
    return out


def check_new_files(rows) -> list[str]:
    bad = []
    for status, path in rows:
        if status != "A":
            continue
        if "/" not in path:
            if path not in ALLOWED_TOP_LEVEL:
                bad.append(f"new top-level file {path!r}. This is where a tool "
                           f"writing into the tree lands: read it, then add it "
                           f"to ALLOWED_TOP_LEVEL in scripts/precommit.py if it "
                           f"belongs here.")
            continue
        if not any(path.startswith(d) for d in EXPECTED_DIRS):
            bad.append(f"new file {path!r} is outside every expected directory "
                       f"({', '.join(EXPECTED_DIRS)})")
    return bad


def check_ledger(rows) -> list[str]:
    """N can only grow.  A commit that removes rows is a deleted experiment."""
    if not any(p == "ledger/trials.sqlite" for _, p in rows):
        return []
    head = _git("show", "HEAD:ledger/trials.sqlite")
    if not head:                      # first commit of the ledger, or unreadable
        return []
    try:
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as fh:
            old = Path(fh.name)
        r = subprocess.run(["git", "show", "HEAD:ledger/trials.sqlite"],
                           capture_output=True, cwd=ROOT)
        old.write_bytes(r.stdout)

        def count(p: Path) -> int:
            c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
            try:
                return int(c.execute("SELECT COUNT(*) FROM trials").fetchone()[0])
            finally:
                c.close()

        before, after = count(old), count(ROOT / "ledger" / "trials.sqlite")
        old.unlink(missing_ok=True)
    except (sqlite3.Error, OSError):
        return []
    if after < before:
        return [f"the ledger would go from {before} rows to {after}. N can only "
                f"grow; {before - after} experiment(s) would be deleted. If two "
                f"machines wrote it, union them with scripts/merge_ledger.py."]
    return []


def check_conflict_markers(rows) -> list[str]:
    bad = []
    for status, path in rows:
        if status == "D":
            continue
        f = ROOT / path
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except (OSError, UnicodeError):
            continue
        if "\n<<<<<<< " in text or text.startswith("<<<<<<< "):
            bad.append(f"{path} still has conflict markers")
    return bad


def check_tests() -> list[str]:
    r = subprocess.run([sys.executable, "-m", "pytest", "tests", "-q"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=ROOT,
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    if r.returncode == 0:
        return []
    tail = "\n".join((r.stdout or "").strip().splitlines()[-12:])
    return [f"the test suite is not green:\n{tail}"]


def _blob(rev: str, path: str) -> str | None:
    """A file's text at a revision, or None if it did not exist there."""
    r = subprocess.run(["git", "show", f"{rev}:{path}"], capture_output=True,
                       cwd=ROOT)
    if r.returncode != 0:
        return None
    return r.stdout.decode("utf-8", errors="replace")


def _staged_text(path: str) -> str | None:
    """The text as it will be committed -- the INDEX, not the working tree.

    Reading the working file would check something the commit does not contain:
    `git add` then edit, and the two differ.  The whole point of this gate is
    to describe the commit, so it has to read what the commit is made of.
    """
    r = subprocess.run(["git", "show", f":{path}"], capture_output=True, cwd=ROOT)
    if r.returncode != 0:
        return None
    return r.stdout.decode("utf-8", errors="replace")


def numstat() -> list[tuple[int, int, str]]:
    out = []
    for line in _git("diff", "--cached", "--numstat").splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        a, d = parts[0], parts[1]
        # binary files report "-"; they carry no line count to budget.
        out.append((int(a) if a.isdigit() else 0,
                    int(d) if d.isdigit() else 0, parts[-1]))
    return out


def check_message(message: str) -> list[str]:
    """The refusals that need to read the commit message.

    Every one of them has the same shape: something that decides whether the
    work was correct is being made to decide less, and the commit does not say
    so.  The marker is not a bypass -- it is the declaration, and it stays in
    the history where `git log --grep` can find it.
    """
    rows = staged()
    problems: list[str] = []

    weak: list[str] = []
    for status, path in rows:
        if not path.startswith("tests/"):
            continue
        before = None if status == "A" else _blob("HEAD", path)
        after = None if status == "D" else _staged_text(path)
        weak += guard.test_weakening(path, before, after)
    if weak and not guard.has_marker(message, "tests"):
        problems.append(
            "this commit weakens the test suite:\n      "
            + "\n      ".join(weak)
            + f"\n    Add a line starting `{guard.MARKERS['tests']}` saying which "
              "test and why it is no longer worth running. A test deleted "
              "without a sentence is the oracle quietly getting easier.")

    frozen = guard.frozen_touched(_git("diff", "--cached", "-U0"))
    if frozen and not guard.has_marker(message, "threshold"):
        problems.append(
            "this commit moves a threshold that was frozen before results were "
            "seen:\n      " + "\n      ".join(frozen)
            + f"\n    Add a line starting `{guard.MARKERS['threshold']}` naming "
              "it and saying what evidence justifies the new value. Section 11: "
              "a threshold moved after seeing a result is how a search "
              "manufactures a finding.")

    hold = guard.holdout_regression(_blob("HEAD", "orc/holdout.py"),
                                    _staged_text("orc/holdout.py"))
    if hold and not guard.has_marker(message, "holdout"):
        problems.append("\n      ".join(hold)
                        + f"\n    If this is deliberate, say so with "
                          f"`{guard.MARKERS['holdout']}`.")

    over = guard.over_budget(numstat())
    if over and not guard.has_marker(message, "budget"):
        problems.append(over + f"\n    If it genuinely has to be one commit, say "
                               f"why with `{guard.MARKERS['budget']}`.")
    return problems


def main(argv: list[str]) -> int:
    if "--install" in argv:
        for name, body in (("pre-commit", HOOK), ("commit-msg", MSG_HOOK)):
            hook = ROOT / ".git" / "hooks" / name
            hook.write_text(body, encoding="utf-8")
            try:
                hook.chmod(0o755)
            except OSError:                                        # pragma: no cover
                pass
            print(f"installed {hook}")
        return 0

    if "--message" in argv:
        # The commit-msg half. Reads what is staged and what the message says
        # about it; the suite ran in pre-commit and is not re-run here.
        path = argv[argv.index("--message") + 1]
        try:
            message = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return 0
        problems = check_message(message)
        if not problems:
            return 0
        print(file=sys.stderr)
        print("the commit was refused:", file=sys.stderr)
        print(file=sys.stderr)
        for pr in problems:
            print(f"  - {pr}", file=sys.stderr)
        print(file=sys.stderr)
        print("Nothing here forbids the change. Each refusal has one way "
              "through: say in the commit message what is being loosened and "
              "why, so it is in the record instead of only in this session.",
              file=sys.stderr)
        print(file=sys.stderr)
        return 1

    rows = staged()
    if not rows:
        return 0
    problems = (check_conflict_markers(rows) + check_new_files(rows)
                + check_ledger(rows) + check_tests())
    if not problems:
        return 0
    print("\nthe commit was refused:\n", file=sys.stderr)
    for p in problems:
        print(f"  - {p}", file=sys.stderr)
    print("\nFix it, or bypass with `git commit --no-verify` and say why in the "
          "message.\n", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
