"""ORC | Git merge driver for the ledger: a union, never a winner.

The ledger is a binary SQLite file inside the repository, and two machines write
to it -- the Actions worker every six hours and the workstation whenever a cycle
is run by hand. Git cannot merge a binary file, so a concurrent write produced a
conflict, the rebase stopped, and the push never happened: run #19 computed 112
trials over 39 minutes and lost all of them because reports/H0001_SURFACE.json
had moved underneath it.

Losing them is survivable -- a trial is deterministic, so the next cycle
recomputes it -- but the failure recurs on every collision, and the resolution
must never be "pick a side". Rows are the one thing in this project that cannot
be reconstructed by choosing: N is the denominator of every correction, taking
one side's file silently discards the other side's questions, and nothing
downstream would ever say so.

A union is well defined here because the table already declares what a duplicate
is:

    UNIQUE (config_hash, symbol, evaluator, panel_hash, code_hash)

That is the identity of a trial -- the same configuration, on the same panel,
under the same code -- so INSERT OR IGNORE across both sides is exactly right.
Same experiment, one row. Different experiment, both rows.

Rows are inserted in created_utc order so the surviving trial_id sequence still
runs roughly chronologically. It is only roughly, which is why surface.py picks
the newest row per cell by created_utc rather than by trial_id: after a merge,
"the last write wins by construction" is no longer true of the surrogate key.

Registered by .gitattributes and configured by the workflow:

    git config merge.orcledger.name   "union the ORC trial ledger"
    git config merge.orcledger.driver "python scripts/merge_ledger.py %O %A %B"

Git calls it with the common ancestor, OUR version and THEIR version, and the
result must be written over %A. Exit 0 means resolved.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

COLUMNS = ("created_utc", "run_id", "family", "hypothesis_id", "symbol",
           "evaluator", "config_hash", "config_json", "code_hash",
           "panel_hash", "holdout_state", "n_starts", "metrics_json")


def rows_of(path: Path) -> list[tuple]:
    """Every trial in a ledger file, oldest first.  An unreadable or empty file
    contributes nothing rather than aborting the merge: a side with no ledger is
    a side that recorded no trials, which is a fact and not an error."""
    if not path.exists() or path.stat().st_size == 0:
        return []
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return []
    try:
        cols = ", ".join(COLUMNS)
        return list(conn.execute(
            f"SELECT {cols} FROM trials ORDER BY created_utc, trial_id"))
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def union(ours: Path, theirs: Path, out: Path) -> tuple[int, int, int]:
    """Write the union of two ledgers to `out`.  Returns (ours, theirs, total)."""
    a, b = rows_of(ours), rows_of(theirs)
    if not a and not b:
        raise SystemExit("neither side of the merge has a readable ledger; "
                         "refusing to write an empty one over either")

    # Build from whichever side is larger so the schema, indices and existing
    # trial_id sequence come from a real file rather than being reconstructed.
    base = ours if len(a) >= len(b) else theirs
    incoming = b if base is ours else a
    if out != base:
        out.write_bytes(base.read_bytes())

    conn = sqlite3.connect(out)
    try:
        before = conn.execute("SELECT COUNT(*) FROM trials").fetchone()[0]
        cols = ", ".join(COLUMNS)
        marks = ", ".join("?" for _ in COLUMNS)
        conn.executemany(
            f"INSERT OR IGNORE INTO trials ({cols}) VALUES ({marks})", incoming)
        conn.commit()
        after = conn.execute("SELECT COUNT(*) FROM trials").fetchone()[0]
        # Fold the write-ahead log back into the file before closing.
        #
        # WAL mode is a property of the FILE, so copying the ledger's bytes
        # above carries it, and SQLite then creates `<out>-wal` and `<out>-shm`
        # beside git's temp file. Git removes the temp file it made and knows
        # nothing about the two siblings, so every merge of the ledger left a
        # pair of `.merge_file_XXXXXX-shm` / `-wal` in the repository root --
        # untracked junk that accumulates, and that precommit.py is right to
        # stop a commit over.
        conn.execute("PRAGMA journal_mode=DELETE")
    finally:
        conn.close()
    # Belt and braces: if the checkpoint above could not run, remove them by
    # name rather than leave them behind.
    for suffix in ("-wal", "-shm"):
        sidecar = out.with_name(out.name + suffix)
        try:
            sidecar.unlink(missing_ok=True)
        except OSError:                                            # pragma: no cover
            pass
    # N can only grow, and a union cannot shrink it. If it did, the driver has
    # a bug and a silent one would be a deleted experiment.
    if after < max(len(a), len(b)):
        raise SystemExit(f"the union has {after} rows, fewer than one side's "
                         f"{max(len(a), len(b))}; refusing to resolve")
    return len(a), len(b), after


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print("usage: merge_ledger.py <ancestor> <ours> <theirs>", file=sys.stderr)
        return 2
    _ancestor, ours, theirs = Path(argv[0]), Path(argv[1]), Path(argv[2])
    n_ours, n_theirs, total = union(ours, theirs, ours)
    print(f"ledger merged: ours {n_ours} + theirs {n_theirs} -> {total} unique "
          f"trial(s); {n_ours + n_theirs - total} were the same experiment",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
