"""ORC | The sealed holdout.

Automated search multiplies the number of looks at the data by orders of
magnitude.  The only defence that does not itself degrade with search volume is
a slice of history the search process cannot physically read.

Two mechanisms, deliberately redundant:

  1. `development_slice()` truncates every panel at HOLDOUT_START.  The worker
     panel shipped to the cloud is built from this, so a remote worker has no
     copy of the sealed period at all -- it cannot cheat even if its code is
     wrong.

  2. `open_final_test()` is the only door to the sealed period.  It refuses
     unless a human has written the token file by hand, it logs every opening
     with the exact configuration hash, and it stops permanently after
     MAX_FINAL_TESTS openings.

A final test is not a validation step you run until something passes.  It is a
single, expensive, irreversible measurement.  The counter exists to make that
literally true.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path

import polars as pl

from orc import config

MAX_FINAL_TESTS = 3
TOKEN_FILE = config.ORC_ROOT / "FINAL_TEST_TOKEN"
LOG_FILE = config.ORC_ROOT / "ledger" / "FINAL_TEST_LOG.jsonl"

TOKEN_TEXT = (
    "I am opening the sealed holdout. I understand this consumes one of three\n"
    "openings for the life of this project and cannot be undone.\n"
)


class HoldoutViolation(RuntimeError):
    pass


def holdout_start() -> date:
    return config.HOLDOUT_START


def development_slice(df: pl.DataFrame, ts_col: str = "ts") -> pl.DataFrame:
    """Everything strictly before the seal.  This is all research may see."""
    cut = datetime.combine(config.HOLDOUT_START, datetime.min.time())
    return df.filter(pl.col(ts_col) < cut)


def sealed_slice(df: pl.DataFrame, ts_col: str = "ts") -> pl.DataFrame:
    cut = datetime.combine(config.HOLDOUT_START, datetime.min.time())
    return df.filter(pl.col(ts_col) >= cut)


def assert_development_only(df: pl.DataFrame, ts_col: str = "ts") -> None:
    """Fail loudly if a frame carries sealed bars into a research path."""
    if df.height == 0:
        return
    cut = datetime.combine(config.HOLDOUT_START, datetime.min.time())
    last = df[ts_col].max()
    if last is not None and last >= cut:
        raise HoldoutViolation(
            f"frame reaches {last}, at or past the seal at {config.HOLDOUT_START}. "
            "Research code must call development_slice() first."
        )


def _openings() -> list[dict]:
    if not LOG_FILE.exists():
        return []
    return [json.loads(line) for line in
            LOG_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]


def openings_used() -> int:
    return len(_openings())


def open_final_test(candidate: dict, reason: str) -> dict:
    """Consume one opening of the sealed period.

    Requires TOKEN_FILE to exist with the exact acknowledgement text.  The token
    is deleted on use so that a second opening needs a second deliberate act.
    """
    used = openings_used()
    if used >= MAX_FINAL_TESTS:
        raise HoldoutViolation(
            f"all {MAX_FINAL_TESTS} final-test openings are spent. "
            "The sealed period is closed for the life of this project."
        )
    if not TOKEN_FILE.exists():
        raise HoldoutViolation(
            "no FINAL_TEST_TOKEN. To open the sealed holdout, write this file by\n"
            f"hand at {TOKEN_FILE} containing exactly:\n\n{TOKEN_TEXT}"
        )
    if TOKEN_FILE.read_text(encoding="utf-8").strip() != TOKEN_TEXT.strip():
        raise HoldoutViolation("FINAL_TEST_TOKEN text does not match; refusing to open.")

    payload = json.dumps(candidate, sort_keys=True, default=str)
    record = {
        "opening": used + 1,
        "of": MAX_FINAL_TESTS,
        "opened_at_utc": datetime.now(timezone.utc).isoformat(),
        "holdout_start": str(config.HOLDOUT_START),
        "reason": reason,
        "candidate": candidate,
        "candidate_sha256": hashlib.sha256(payload.encode()).hexdigest(),
    }
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, default=str) + "\n")
    TOKEN_FILE.unlink()
    return record
