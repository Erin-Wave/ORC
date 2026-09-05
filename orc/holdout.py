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


# A second, independent record of the same count.
#
# The counter that is supposed to be irreversible was reconstructed from ONE
# file, and a file that is absent read as "never opened" rather than as "this
# is not known".  Deleting it therefore restored all three openings -- the
# strongest guarantee in the project undone by an `rm`.  One file is still one
# file, but two that must be removed together, in a directory the cycle commits
# on every run, is a materially harder accident.
STATE_NAME = "FINAL_TEST_STATE.json"


def state_file() -> Path:
    """Derived from LOG_FILE, never a constant of its own.

    The first draft made this a module constant beside LOG_FILE, and within one
    test run it had written "3 openings used" into the REAL ledger directory:
    the holdout tests redirect TOKEN_FILE and LOG_FILE to tmp_path, as they
    must, and a third path they had never heard of went straight past them to
    the live counter.  A test spending the project's irreversible openings is a
    worse defect than the one being fixed.  Deriving it means anything that
    redirects the log redirects this too, and no caller has to know it exists.
    """
    return LOG_FILE.with_name(STATE_NAME)


def _state_count() -> int:
    """The standalone record of how many openings are spent.

    Three outcomes, not two. A file that is NOT THERE is a genuine zero -- a
    fresh project has neither file. A file that is there but cannot be parsed
    is UNKNOWN, and unknown resolves to MAX_FINAL_TESTS, because every other
    way this number can be wrong makes it too small and each of those is a
    restored look at the sealed data.

    Returning 0 for both was the hole: a truncated write, a bad merge or a hand
    edit leaves an unparseable state file, and with the log also gone
    openings_used() went back to zero and handed out three fresh openings. The
    existing test covered a MISSING log against a valid state file; nothing
    covered a state file that exists and is garbage.
    """
    p = state_file()
    if not p.exists():
        return 0
    try:
        return int(json.loads(p.read_text(encoding="utf-8"))["openings_used"])
    except (OSError, ValueError, KeyError, TypeError):
        # Deliberately the maximum. This makes the project refuse every further
        # opening until a human looks at the file, which is the correct failure
        # for a counter whose only job is to be impossible to walk back.
        return MAX_FINAL_TESTS


def openings_used() -> int:
    """How many of the three are spent.

    The largest count any surviving record supports, because every way this
    number can be wrong makes it too SMALL and each of those ways is a restored
    opening:

      - the highest ordinal, so a log that has lost a line -- a bad merge, a
        hand edit, a truncated write -- cannot hand out an ordinal already
        spent;
      - the number of records, because max() over ordinals collapses two
        records that both claim opening 2 into a single opening, and every
        record is one opening that really happened;
      - the standalone state file, so losing the log alone does not reset the
        count to zero.

    A fresh project has neither file and is genuinely at zero.  Every other
    disagreement resolves upward, which is the only direction that cannot
    manufacture a look at the sealed data.
    """
    recs = _openings()
    by_ordinal = max((int(r.get("opening", 0)) for r in recs), default=0)
    return max(by_ordinal, len(recs), _state_count())


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

    # Defence in depth against the failure openings_used() now resolves upward.
    # If an ordinal about to be written is already in the log, the count that
    # produced it was too small and this call would spend an opening that has
    # already been spent.  Refuse rather than append.
    ordinal = used + 1
    if any(int(r.get("opening", 0)) == ordinal for r in _openings()):
        raise HoldoutViolation(
            f"opening {ordinal} is already recorded in {LOG_FILE.name}. The "
            "counter and the log disagree; refusing to open the seal until a "
            "human reconciles them.")

    payload = json.dumps(candidate, sort_keys=True, default=str)
    record = {
        "opening": ordinal,
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
    # The second record, written after the log so that a crash between the two
    # leaves the count too HIGH rather than too low.
    state_file().write_text(json.dumps(
        {"openings_used": ordinal, "of": MAX_FINAL_TESTS,
         "updated_utc": record["opened_at_utc"],
         "note": "A second copy of the opening count. openings_used() takes the "
                 "largest of this, the log's highest ordinal and the log's line "
                 "count. Do not edit by hand."}, indent=2) + "\n",
        encoding="utf-8")
    TOKEN_FILE.unlink()
    return record
