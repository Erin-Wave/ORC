"""ORC | A private checkout for a read-only model call.

Five steps in the reasoning pass are documented read-only and enforced for the
Claude CLI by `--allowedTools`. A second vendor has its own flags and its own
idea of a sandbox, so the promise needed a check rather than a restatement --
`llm.tree_fingerprint` is that check, and it has a hole no amount of care
closes: **the supervisor runs on the same checkout a person edits.**

On 2026-09-05 the 22:56Z pass recorded four violations by "claude" and two of
them -- `orc/orchestrator/surface.py` and `reports/H0019_SURFACE.json` -- were
the owner's own session editing the same tree at the same moment. A log that
names an innocent party is worse than no log, because its only purpose is
deciding whether a model honoured its tools. The record was made honest that
day (`attribution: "unattributed"`), which stopped it lying and did not stop
the writes.

This is the fix the honest record was standing in for. A provider gets its own
git worktree, so:

  a write lands somewhere the research never reads, and
  attribution stops being an inference: anything dirty in the sandbox was
  written by the process that had it, because nothing else can see it.

WHY NOT FROM HEAD. The obstacle recorded with the finding: a reasoning pass
reads UNCOMMITTED reports -- surfaces regenerated earlier in the same pass, a
cycle report written minutes ago. A worktree checked out at HEAD would hand the
proposer yesterday's evidence and it would propose against it. So the tracked
tree comes from HEAD and the working copy's own dirty files are layered on top,
which is what the caller actually sees on disk.

WHAT IS DELIBERATELY NOT COPIED. `facts/` is 9.7 GB and read-only to every one
of these steps; it is symlinked where the platform allows and left absent where
it does not, because a model that cannot open a panel writes a worse answer,
not a wrong one. `ledger/` is NOT copied at all: a step that wanted to write a
trial row would then write it into a database nobody reads, which is the
correct outcome for a step that was told not to.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

from orc import config

# Paths a read-only step legitimately reads and that are cheap to carry.
# reports/ and configs/ are the evidence; docs/ and CLAUDE.md are the rules.
CARRIED = ("reports", "configs", "docs", "CLAUDE.md", "orc", "scripts", "tests")

# Read-only and far too large to copy. Linked when the platform allows it.
LINKED = ("facts",)


def _git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd or config.ORC_ROOT),
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=False)


def dirty_paths() -> list[str]:
    """Tracked files the working copy has changed, plus untracked ones.

    These are layered over the HEAD checkout so a pass reads the evidence that
    exists NOW -- the surfaces it regenerated a minute ago -- rather than
    whatever was last committed.
    """
    r = _git("status", "--porcelain")
    if r.returncode != 0:
        return []
    out = []
    for line in (r.stdout or "").splitlines():
        p = line[3:].strip().strip('"')
        # A rename prints "old -> new"; the new name is the one on disk.
        if " -> " in p:
            p = p.split(" -> ", 1)[1]
        if p and not p.endswith("/"):
            out.append(p)
    return out


@contextmanager
def worktree(label: str = "provider"):
    """A private checkout, removed on exit.

    Yields the path. The caller passes it as `cwd` to the model call, and the
    model's Read/Glob/Grep see a tree that looks like the research tree and is
    not it.
    """
    base = Path(tempfile.mkdtemp(prefix=f"orc-{label}-"))
    tree = base / "tree"
    made = False
    try:
        r = _git("worktree", "add", "--detach", "-q", str(tree), "HEAD")
        if r.returncode != 0:
            # No worktree is not a reason to skip the step. The caller falls
            # back to the real tree and the honest violation record, which is
            # what it had before this file existed.
            raise RuntimeError(f"git worktree add failed: {r.stderr.strip()[:200]}")
        made = True

        for rel in dirty_paths():
            src = config.ORC_ROOT / rel
            if not src.exists():
                continue
            dst = tree / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(src, dst)
            except OSError:
                pass

        # A step told not to write must not find a ledger to write INTO. Git
        # checks the directory out because it is tracked; it is removed here so
        # a stray Ledger() lands on nothing rather than on a copy nobody reads.
        shutil.rmtree(tree / "ledger", ignore_errors=True)

        for rel in LINKED:
            src, dst = config.ORC_ROOT / rel, tree / rel
            if not src.exists() or dst.exists():
                continue
            try:
                dst.symlink_to(src, target_is_directory=True)
            except (OSError, NotImplementedError):
                # Windows needs a privilege for this. Absent is the honest
                # state and the steps that read facts/ are not these ones.
                pass

        # The baseline is taken AFTER the dirty files are layered in, or every
        # file the owner happened to be editing would be reported as the
        # provider's write -- the same misattribution this module exists to
        # end, moved one directory over.
        _BASELINE[str(tree)] = set(wrote_anything(tree))
        yield tree
    finally:
        _BASELINE.pop(str(tree), None)
        if made:
            _git("worktree", "remove", "--force", str(tree))
        shutil.rmtree(base, ignore_errors=True)


# Set once per sandbox, after setup, so `wrote()` can subtract what the setup
# itself put there.
_BASELINE: dict[str, set] = {}


def wrote_anything(tree: Path) -> list[str]:
    """Everything dirty in the sandbox, setup included. Use `wrote()`."""
    r = _git("status", "--porcelain", cwd=tree)
    if r.returncode != 0:
        return []
    return sorted({line[3:].strip().strip('"')
                   for line in (r.stdout or "").splitlines() if line[3:].strip()})


def wrote(tree: Path) -> list[str]:
    """What the PROVIDER wrote, and nothing else.

    Unlike the before/after fingerprint this replaces, the answer is
    attributable rather than inferred: nothing outside this call can see the
    directory, so a file that appeared here appeared because the model put it
    here. That is the difference between an observation and an accusation.
    """
    return sorted(set(wrote_anything(tree)) - _BASELINE.get(str(tree), set()))
