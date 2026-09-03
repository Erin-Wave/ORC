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
  new files      a file appearing at the top level, or anywhere unexpected, has
                 to be named on purpose. AGENTS.md arrived that way -- 193 lines
                 written into the tree by a review step that was documented as
                 read-only -- and went into a commit without being read.
  ledger         ledger/trials.sqlite may not shrink. N can only grow, and a
                 commit that removes rows is a deleted experiment.
  conflicts      no file with conflict markers, ever.

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


def main(argv: list[str]) -> int:
    if "--install" in argv:
        hook = ROOT / ".git" / "hooks" / "pre-commit"
        hook.write_text(HOOK, encoding="utf-8")
        try:
            hook.chmod(0o755)
        except OSError:                                            # pragma: no cover
            pass
        print(f"installed {hook}")
        return 0

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
