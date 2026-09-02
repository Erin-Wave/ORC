"""ORC | The sealed holdout.

Automated search multiplies the number of looks at the data by orders of
magnitude.  The only defence that does not itself degrade with search volume is
a slice of history the search process cannot physically read.

Two mechanisms, deliberately redundant:

  1. `development_slice()` truncates every panel at HOLDOUT_START.  The worker
     panel shipped to the cloud is built from this, so a remote worker has no
     copy of the sealed period at all -- it cannot cheat even if its code is
     wrong.

  2. `final_test()` is the only door to the sealed period.  It refuses unless a
     human has written the token file by hand, it logs every opening with the
     exact configuration hash, it stops permanently after MAX_FINAL_TESTS
     openings, and -- the part that was missing until the door was checked --
     the loader refuses to hand back sealed bars outside one.  Before that,
     `panel.load(development_only=False)` was callable at any moment with no
     token, no log and no counter, so mechanism 2 protected the workstation
     exactly as much as a comment does.  Only mechanism 1 was ever real, and
     only for the cloud worker.

A final test is not a validation step you run until something passes.  It is a
single, expensive, irreversible measurement.  The counter exists to make that
literally true.
"""
from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path

import polars as pl

from orc import config

MAX_FINAL_TESTS = 3
TOKEN_FILE = config.ORC_ROOT / "FINAL_TEST_TOKEN"
LOG_FILE = config.ORC_ROOT / "ledger" / "FINAL_TEST_LOG.jsonl"
READS_FILE = config.ORC_ROOT / "ledger" / "FINAL_TEST_READS.jsonl"

TOKEN_TEXT = (
    "I am opening the sealed holdout. I understand this consumes one of three\n"
    "openings for the life of this project and cannot be undone.\n"
)


class HoldoutViolation(RuntimeError):
    pass


# Whether a sealed read is currently permitted, and what has been read under
# the opening that permitted it.  open_final_test() used to log an opening and
# grant nothing at all: panel.load(development_only=False) was callable at any
# moment by anybody, so the counter measured how many times someone had filled
# in the form, not how many times the sealed period had been looked at.  One
# opening could cover a 972-cell grid and the log would say 1.
_sealed_reads: list[str] | None = None


def sealed_reads_permitted() -> bool:
    return _sealed_reads is not None


def note_sealed_read(what: str) -> None:
    """Called by the loader before it hands back sealed bars."""
    if _sealed_reads is None:
        raise HoldoutViolation(
            f"refusing to read sealed data for {what}: no final test is open. "
            "The sealed period is reachable only inside holdout.final_test(), "
            "which consumes one of three openings for the life of the project.")
    _sealed_reads.append(what)


@contextmanager
def final_test(candidate: dict, reason: str):
    """The only door.  Consumes one opening and permits sealed reads inside it.

    Every read is recorded, so an opening that quietly measured a whole grid
    is visible afterwards as exactly that rather than as one measurement.
    """
    global _sealed_reads
    if _sealed_reads is not None:
        raise HoldoutViolation("a final test is already open")
    record = open_final_test(candidate, reason)
    _sealed_reads = []
    try:
        yield record
    finally:
        reads, _sealed_reads = _sealed_reads, None
        READS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with READS_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "opening": record["opening"],
                "candidate_sha256": record["candidate_sha256"],
                "n_sealed_reads": len(reads),
                "sealed_reads": reads,
            }) + chr(10))


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
