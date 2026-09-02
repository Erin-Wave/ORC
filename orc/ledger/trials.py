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


def canonical_hash(obj: Any) -> str:
    """Stable hash of a configuration.  Key order must never change the id."""
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def code_hash(paths: list[Path] | None = None) -> str:
    """Hash of the evaluation code, so a silent kernel change starts a new trial."""
    roots = paths or [
        config.ORC_ROOT / "orc" / "kernel",
        config.ORC_ROOT / "orc" / "eval",
    ]
    h = hashlib.sha256()
    for root in sorted(roots, key=str):
        for p in sorted(Path(root).rglob("*.py")):
            h.update(p.name.encode())
            h.update(p.read_bytes())
    return h.hexdigest()


class Ledger:
    def __init__(self, path: Path | None = None):
        self.path = Path(path or config.LEDGER_DB)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._migrate()
        self.conn.executescript(SCHEMA)
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
        self.conn.commit()
        if cur.rowcount:
            return int(cur.lastrowid), True
        existing = self.conn.execute(
            "SELECT trial_id FROM trials WHERE config_hash=? AND symbol=?"
            " AND evaluator=? AND panel_hash=? AND code_hash=?",
            (chash, symbol, evaluator, panel_hash, chash_code)).fetchone()
        return int(existing[0]), False

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
