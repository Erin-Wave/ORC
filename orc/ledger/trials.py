"""ORC | The trial ledger.

Every backtest ever run lands here, once.  This is not logging: the row count
is an input to the statistics.  A result selected as the best of N trials is not
the same evidence as the same result obtained on the first try, and the only way
to know N is to have counted every trial including the ones nobody looked at.

Append-only.  A SQL trigger blocks UPDATE and DELETE so a later cycle cannot
quietly retire the trials that make its own discovery look lucky.

Insertion is idempotent on (config_hash, symbol, evaluator, panel_hash,
code_hash): re-running an identical trial does not inflate N, but changing
anything about the configuration, the data OR the evaluation code creates a new
trial, as it must -- a result produced by a since-modified kernel is a different
measurement, not the same one.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from orc import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS trials (
    trial_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    created_utc    TEXT    NOT NULL,
    run_id         TEXT    NOT NULL,
    family         TEXT    NOT NULL,
    hypothesis_id  TEXT,
    symbol         TEXT    NOT NULL,
    evaluator      TEXT    NOT NULL,
    config_hash    TEXT    NOT NULL,
    config_json    TEXT    NOT NULL,
    code_hash      TEXT    NOT NULL,
    panel_hash     TEXT    NOT NULL,
    holdout_state  TEXT    NOT NULL,
    n_starts       INTEGER NOT NULL,
    metrics_json   TEXT    NOT NULL,
    UNIQUE (config_hash, symbol, evaluator, panel_hash, code_hash)
);

CREATE INDEX IF NOT EXISTS ix_trials_family ON trials(family);
CREATE INDEX IF NOT EXISTS ix_trials_run    ON trials(run_id);

-- Which hypotheses enumerated a given measurement.
--
-- A trial row is a MEASUREMENT and is deduped on what determines the number:
-- (config_hash, symbol, evaluator, panel_hash, code_hash).  A hypothesis is a
-- QUESTION, and two questions are free to enumerate the same cell.  Because
-- hypothesis_id sits on the trial row but not in its uniqueness key, the second
-- question's insert was silently IGNORE'd, the row kept the FIRST question's
-- id, and surface_from_ledger's `WHERE hypothesis_id=?` then reported those
-- cells as never run -- a hypothesis with a full grid of real measurements
-- behind it reading as empty.
--
-- Putting hypothesis_id in the trial key instead would have recorded the same
-- number twice and inflated N, which is the one thing that must stay honest.
-- So the measurement is stored once and the attribution is a set beside it.
CREATE TABLE IF NOT EXISTS trial_hypotheses (
    trial_id       INTEGER NOT NULL REFERENCES trials(trial_id),
    hypothesis_id  TEXT    NOT NULL,
    first_seen_utc TEXT    NOT NULL,
    UNIQUE (trial_id, hypothesis_id)
);

CREATE INDEX IF NOT EXISTS ix_th_hypothesis ON trial_hypotheses(hypothesis_id);

CREATE TRIGGER IF NOT EXISTS trials_no_update
BEFORE UPDATE ON trials
BEGIN
    SELECT RAISE(ABORT, 'the trial ledger is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trials_no_delete
BEFORE DELETE ON trials
BEGIN
    SELECT RAISE(ABORT, 'the trial ledger is append-only');
END;
"""


def _canonical(obj: Any) -> Any:
    """A configuration reduced to VALUES, not to how they happen to be spelled.

    config_hash is the identity of a cell, and it was being decided by JSON
    representation rather than by content.  `json.dumps` writes 7 as "7" and
    7.0 as "7.0", and a numpy scalar is not JSON-serialisable at all, so
    `default=str` turned np.int64(7) into the STRING "7".  One cell could
    therefore carry three different identities depending on where its value
    came from -- a literal in the queue file, a float after arithmetic, or a
    numpy scalar out of a grid axis -- and each identity was a separate row, a
    separate contribution to N, and a dedupe that had silently stopped working.

    Non-finite floats get a name rather than a spelling because `json.dumps`
    emits bare NaN/Infinity, which is not JSON and does not round-trip.
    """
    if isinstance(obj, dict):
        return {str(k): _canonical(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_canonical(v) for v in obj]
    # bool is checked before int because in Python it IS an int, and True must
    # not collapse into 1.
    if isinstance(obj, bool):
        return obj
    if not isinstance(obj, (str, bytes)) and hasattr(obj, "item"):
        try:                                   # a numpy scalar -> a Python one
            obj = obj.item()
        except (AttributeError, ValueError):   # pragma: no cover
            pass
        if isinstance(obj, bool):
            return obj
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        if math.isnan(obj):
            return "__nan__"
        if math.isinf(obj):
            return "__inf__" if obj > 0.0 else "__-inf__"
        # 7.0 is the same setting as 7, so it must be the same cell.
        return int(obj) if obj.is_integer() else obj
    if obj is None or isinstance(obj, str):
        return obj
    return str(obj)


def canonical_hash(obj: Any) -> str:
    """Stable hash of a configuration.  Key order must never change the id."""
    return hashlib.sha256(
        json.dumps(_canonical(obj), sort_keys=True, separators=(",", ":"),
                   default=str).encode()
    ).hexdigest()


# Everything whose content can change a number written to a row.
#
# A module constant rather than a literal inside the function because the list
# is the whole of the guarantee and nothing could check it: scripts/mutation.py
# deleted "orc/eval" from it on 2026-09-04 and the entire 254-test suite stayed
# green. That is the defect the comment below describes, made silent -- a
# corrected evaluator re-runs, matches the old UNIQUE key, is discarded by
# INSERT OR IGNORE and prints "new 0", which reads as correct deduplication
# rather than as a correction thrown away.
CODE_HASH_ROOTS = (
    "orc/kernel",
    "orc/eval",
    # The metrics are assembled in the orchestrator and the data in the panel
    # loader, so hashing only the evaluators meant a corrected metric was
    # silently dropped.
    "orc/orchestrator/runner.py",
    # spec.py defines the fee actually applied (effective_fee_bps), the
    # evaluator a configuration is routed to (uses_analytic) and how a grid
    # expands. Change any of them and every metric moves while config_hash,
    # panel_hash and evaluator all stay put.
    "orc/orchestrator/spec.py",
    "orc/facts/panel.py",
)


def code_hash(paths: list[Path] | None = None) -> str:
    """Hash of the evaluation code, so a silent kernel change starts a new trial."""
    # Everything that can change a number written to a row.  The metrics are
    # assembled in the orchestrator and the data in the panel loader, so hashing
    # only the evaluators meant a corrected metric re-ran, matched the UNIQUE
    # key, was discarded by INSERT OR IGNORE, and printed "new 0" -- which reads
    # as correct deduplication rather than as a correction thrown away.
    roots = paths or [config.ORC_ROOT / p for p in CODE_HASH_ROOTS]
    h = hashlib.sha256()
    for root in sorted(roots, key=str):
        root = Path(root)
        # A root that is not there used to contribute nothing and raise
        # nothing: `is_file()` is False for a missing path, and rglob over a
        # missing directory yields an empty iterator. So a renamed or moved
        # root silently left the hash, and with every root gone the function
        # returned e3b0c44298fc... -- the SHA-256 of nothing, a perfectly
        # well-formed digest computed over no code at all.
        #
        # The consequence is the exact failure this hash exists to prevent,
        # made permanent: a corrected evaluator would key on a constant, match
        # its own old rows, and be discarded by INSERT OR IGNORE while printing
        # "new 0". Refusing is the only safe answer, because there is no digest
        # that honestly represents code that was not read.
        if not root.exists():
            raise FileNotFoundError(
                f"code_hash: {root} does not exist. A root that vanishes "
                "leaves the hash silently, and every later correction to the "
                "code it covered would be discarded as a duplicate. Fix "
                "CODE_HASH_ROOTS or restore the path.")
        files = [root] if root.is_file() else sorted(root.rglob("*.py"))
        if not files:
            raise FileNotFoundError(
                f"code_hash: {root} contains no .py files; it cannot be "
                "contributing to a hash that is supposed to identify code.")
        for p in files:
            h.update(p.name.encode())
            # Normalise line endings before hashing.  git on this workstation
            # runs with core.autocrlf=true, so a checkout rewrites these files
            # with CRLF while the Linux runner keeps LF.  Hashing raw bytes
            # therefore gave the same commit two different code hashes, one per
            # platform, and trials run locally could never dedupe against the
            # worker's -- every crossing silently added a fresh copy of the
            # same measurement to N.  The hash has to identify the code, not
            # the bytes a particular checkout happens to have left on disk.
            h.update(p.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()


# An empty ledger is not an empty result -- it is the multiple-testing
# correction switched off.
#
# sqlite3.connect() CREATES a database rather than failing on a path that is
# not there, and every reader here then works perfectly against it: the schema
# builds, the queries run, N comes back 0, and `verdict.disqualifiers()`
# corrects every result against zero prior looks. There is no error anywhere.
#
# The evidence this is reachable is a 0-byte `ledger/trials.db` sitting in this
# repository, created 2026-09-05 17:32 by a read-only adversary probe that
# guessed the filename (the real one is trials.sqlite). That probe used
# sqlite3 directly so this guard would not have caught it, but the same typo
# through ORC_LEDGER -- or a checkout that did not pull the 16 MB file --
# reaches the project's own reader and is silent all the way to a report.
#
# So the CONFIGURED ledger is never brought into existence as a side effect of
# opening it. A caller that names its own path (a test, a sandbox, a scratch
# copy) is doing so deliberately and keeps the old behaviour, which is why no
# call site had to change -- two of the 34 are inside CODE_HASH_ROOTS and
# touching them would re-run the entire registry.
ALLOW_EMPTY_LEDGER_ENV = "ORC_ALLOW_EMPTY_LEDGER"


class Ledger:
    def __init__(self, path: Path | None = None,
                 create_if_missing: bool | None = None):
        self.path = Path(path or config.LEDGER_DB)
        if create_if_missing is None:
            create_if_missing = self.path != Path(config.LEDGER_DB)
        if (not create_if_missing and not self.path.exists()
                and not os.environ.get(ALLOW_EMPTY_LEDGER_ENV)):
            raise FileNotFoundError(
                f"the ledger is not at {self.path}. Refusing to create an "
                "empty one: N would read 0 and every result would be corrected "
                "against zero prior looks, with nothing failing anywhere. "
                "ledger/trials.sqlite is committed, so a real checkout has it "
                "-- check ORC_LEDGER and ORC_ROOT. To start a genuinely new "
                f"project set {ALLOW_EMPTY_LEDGER_ENV}=1.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._migrate()
        self.conn.executescript(SCHEMA)
        # Every row written before trial_hypotheses existed carries exactly one
        # attribution -- the hypothesis that got there first -- and it is on the
        # row itself.  Carry it across so a surface built from an old ledger is
        # not empty.  INSERT OR IGNORE, so this is a no-op on every later open.
        self.conn.execute(
            "INSERT OR IGNORE INTO trial_hypotheses (trial_id, hypothesis_id,"
            " first_seen_utc) SELECT trial_id, hypothesis_id, created_utc"
            " FROM trials WHERE hypothesis_id IS NOT NULL")
        self.conn.commit()

    def _migrate(self) -> None:
        """Rebuild a ledger written before code_hash joined the uniqueness key.

        Rows are carried over unchanged.  This is the only operation in the
        project allowed to touch an existing trials table, and it neither drops
        nor edits a single row.
        """
        row = self.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='trials'"
        ).fetchone()
        if not row or "code_hash)" in (row[0] or ""):
            return
        cols = ("created_utc, run_id, family, hypothesis_id, symbol, evaluator,"
                " config_hash, config_json, code_hash, panel_hash, holdout_state,"
                " n_starts, metrics_json")
        self.conn.executescript(
            "DROP TRIGGER IF EXISTS trials_no_update;"
            "DROP TRIGGER IF EXISTS trials_no_delete;"
            "ALTER TABLE trials RENAME TO trials_legacy;")
        self.conn.executescript(SCHEMA)
        self.conn.execute(
            f"INSERT OR IGNORE INTO trials ({cols}) SELECT {cols} FROM trials_legacy")
        self.conn.executescript(
            "DROP TRIGGER IF EXISTS trials_no_update;"
            "DROP TRIGGER IF EXISTS trials_no_delete;"
            "DROP TABLE trials_legacy;")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ----------------------------------------------------------------
    def record(
        self,
        run_id: str,
        family: str,
        symbol: str,
        evaluator: str,
        cfg: dict,
        metrics: dict,
        n_starts: int,
        panel_hash: str,
        holdout_state: str = "DEVELOPMENT",
        hypothesis_id: str | None = None,
        code: str | None = None,
    ) -> tuple[int, bool]:
        """Insert one trial.  Returns (trial_id, was_new)."""
        chash = canonical_hash(cfg)
        chash_code = code or code_hash()
        row = (
            datetime.now(timezone.utc).isoformat(), run_id, family, hypothesis_id,
            symbol, evaluator, chash,
            json.dumps(cfg, sort_keys=True, default=str), chash_code, panel_hash,
            holdout_state, int(n_starts),
            json.dumps(metrics, sort_keys=True, default=float),
        )
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO trials (created_utc, run_id, family, hypothesis_id,"
            " symbol, evaluator, config_hash, config_json, code_hash, panel_hash,"
            " holdout_state, n_starts, metrics_json)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", row)
        if cur.rowcount:
            trial_id, was_new = int(cur.lastrowid), True
        else:
            existing = self.conn.execute(
                "SELECT trial_id FROM trials WHERE config_hash=? AND symbol=?"
                " AND evaluator=? AND panel_hash=? AND code_hash=?",
                (chash, symbol, evaluator, panel_hash, chash_code)).fetchone()
            trial_id, was_new = int(existing[0]), False
        # Attribution is recorded whether or not the measurement was new.  This
        # is the whole point: a second hypothesis that enumerates a cell an
        # earlier one already measured adds no row to `trials` -- N does not
        # move, because no new experiment was performed -- but it must still be
        # able to see its own grid.
        if hypothesis_id is not None:
            self.conn.execute(
                "INSERT OR IGNORE INTO trial_hypotheses (trial_id, hypothesis_id,"
                " first_seen_utc) VALUES (?,?,?)",
                (trial_id, hypothesis_id, row[0]))
        self.conn.commit()
        return trial_id, was_new

    def record_many(self, rows: list[dict]) -> int:
        new = 0
        for r in rows:
            _, was_new = self.record(**r)
            new += int(was_new)
        return new

    # ----------------------------------------------------------------
    def total_trials(self) -> int:
        """N.  The number every multiple-testing correction must consume."""
        return int(self.conn.execute("SELECT COUNT(*) FROM trials").fetchone()[0])

    def newest_trial_utc(self) -> str | None:
        """When a question nobody had asked before was last answered.

        The worker re-runs the whole registry every six hours whether or not
        anything new was proposed, so a fresh cycle report and trials_added: 0
        are what a healthy loop and a dead one look like alike.  This moves
        only when a genuinely new trial is inserted, which makes it the one
        clock that can tell the two apart.
        """
        row = self.conn.execute("SELECT MAX(created_utc) FROM trials").fetchone()
        return row[0] if row and row[0] else None

    def runs(self, limit: int = 10) -> list[dict]:
        """When research actually happened, newest first.

        A run appears here only if it INSERTED a row, which is the property
        that makes this the honest record of research time: the worker fires
        every six hours whether or not anything was proposed, and a cycle over
        an unchanged registry dedupes to zero inserts and leaves no trace.
        Wall-clock span is min..max of the rows, so it measures the evaluation
        and not the checkout, install and panel download around it.
        """
        rows = self.conn.execute(
            "SELECT run_id, MIN(created_utc), MAX(created_utc), COUNT(*),"
            " GROUP_CONCAT(DISTINCT hypothesis_id)"
            " FROM trials GROUP BY run_id ORDER BY MIN(created_utc) DESC LIMIT ?",
            (int(limit),)).fetchall()
        return [{"run_id": r[0], "first_utc": r[1], "last_utc": r[2],
                 "trials": int(r[3]),
                 "hypotheses": sorted((r[4] or "").split(",")) if r[4] else []}
                for r in rows]

    def trials_in_family(self, family: str) -> int:
        return int(self.conn.execute(
            "SELECT COUNT(*) FROM trials WHERE family=?", (family,)).fetchone()[0])

    def families(self) -> list[tuple[str, int]]:
        return [(r[0], int(r[1])) for r in self.conn.execute(
            "SELECT family, COUNT(*) FROM trials GROUP BY family ORDER BY 2 DESC")]

    def best(self, family: str | None, metric: str, limit: int = 20) -> list[dict]:
        """Top trials by a metric stored inside metrics_json."""
        expr = "json_extract(metrics_json, '$.' || ?)"
        sql = (f"SELECT trial_id, family, symbol, config_json, metrics_json, {expr} AS m"
               f" FROM trials WHERE {expr} IS NOT NULL")
        args: list = [metric, metric]
        if family:
            sql += " AND family = ?"
            args.append(family)
        sql += " ORDER BY m DESC LIMIT ?"
        args.append(limit)
        out = []
        for r in self.conn.execute(sql, args):
            out.append({
                "trial_id": r[0], "family": r[1], "symbol": r[2],
                "config": json.loads(r[3]), "metrics": json.loads(r[4]), metric: r[5],
            })
        return out

    def summary(self) -> dict:
        return {
            "total_trials": self.total_trials(),
            "families": dict(self.families()),
            "ledger_path": str(self.path),
        }
