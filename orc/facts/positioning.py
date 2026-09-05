"""ORC | Open interest and taker flow, from the official Binance archive.

Section 7b says the open family is a PARTIAL test and says exactly why:

    The liquidation stream itself is not in this archive. A displaced price is
    evidence of forced flow, not a measurement of it, and ordinary aggressive
    trading displaces price too.

That objection is about one missing distinction, not about liquidations as
such. A forced close and an aggressive open look the same in an OHLCV bar --
price moves, volume rises -- and they are opposite events in the only variable
that separates them: **open interest**. Positions closing REDUCES it; new
positions opening RAISES it. Every one of the scout's forced-flow candidates
asks for that same distinction in different words, and entry 29 states it
outright: "Trade prints and per-symbol open interest to confirm the flow is
position-closing rather than new."

Binance publishes it. `data/futures/um/daily/metrics` carries, every five
minutes and with no API key:

    sum_open_interest                 contracts outstanding
    sum_open_interest_value           the same in USD
    count_toptrader_long_short_ratio  top accounts, by account
    sum_toptrader_long_short_ratio    top accounts, by position
    count_long_short_ratio            all accounts
    sum_taker_long_short_vol_ratio    taker buy volume over taker sell volume

Measured 2026-09-05: BTCUSDT runs 2020-09-01 to the present, which is 1,277
days before the seal; symbols listed later start 2021-12-01 and give 821. That
is the development window this can be researched on.

WHAT THIS IS NOT. It is still not the liquidation stream, and a fall in open
interest is not proof that the closes were compulsory -- a voluntary exit
reduces it identically. What it buys is the ability to REFUTE: a move on which
open interest rises cannot be a liquidation cascade, whatever the price did.
A claim that reads more into it than that is claiming something it did not
measure, which is the sentence section 7b already wrote.

THE SEAL. This module reads through `load()` and `load()` truncates, exactly as
`panel.load` does and for the same reason -- and it is a separate module rather
than an addition to panel.py precisely so that the seal is the only thing they
share: panel.py is in CODE_HASH_ROOTS, so editing it would move code_hash and
re-run every trial ever recorded as a new row.

    python -m orc.facts.positioning BTCUSDT ETHUSDT     fetch
    python -m orc.facts.positioning --universe          fetch the nine
    python -m orc.facts.positioning --status            what is held
"""
from __future__ import annotations

import io
import sys
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

import polars as pl

from orc import config, holdout
from orc.facts.fetch_vision import BASE, _get

# One row per five minutes, so a day is 288 (289 with the closing stamp).
# Anything far below that is a day the venue did not publish in full, and a
# gap-filled average would be a number this project invented.
ROWS_PER_DAY = 288

# Frozen 2026-09-05, before any hypothesis read this data. A day missing more
# than a quarter of its rows is dropped rather than interpolated: open interest
# is a level, so a hole in it is not noise around a mean, it is a level nobody
# recorded.
MAX_MISSING_FRACTION = 0.25

# The columns Binance publishes, in file order.
COLUMNS = [
    "create_time", "symbol", "sum_open_interest", "sum_open_interest_value",
    "count_toptrader_long_short_ratio", "sum_toptrader_long_short_ratio",
    "count_long_short_ratio", "sum_taker_long_short_vol_ratio",
]

DATASET = "data/futures/um/daily/metrics"

# One thread per in-flight download. These wait on a socket rather than on a
# core, so this is unrelated to the null's worker pool and must not be sized
# from cpu_count. Modest on purpose: data.binance.vision is free and unmetered,
# and that is a thing to spend carefully rather than as fast as possible.
#
# Ten because that is fetch_vision._SESSION's connection pool. Going wider
# would make urllib3 discard and rebuild connections it could not park, which
# is slower than the number suggests -- and raising the pool would mean this
# module reaching into another module's shared session to do it.
DOWNLOAD_THREADS = 10


def store() -> Path:
    return config.FACTS / "positioning"


def path_for(symbol: str) -> Path:
    return store() / f"{symbol}.parquet"


def _day_frame(symbol: str, day: date) -> pl.DataFrame | None:
    """One day of five-minute metrics, or None if the venue has no such file.

    A 404 is a fact about that day and not an error, which is the same
    convention fetch_vision already uses.
    """
    url = f"{BASE}/{DATASET}/{symbol}/{symbol}-metrics-{day.isoformat()}.zip"
    r = _get(url)
    if r is None:
        return None
    try:
        z = zipfile.ZipFile(io.BytesIO(r.content))
        raw = z.read(z.namelist()[0]).decode("utf-8")
    except (zipfile.BadZipFile, IndexError, UnicodeDecodeError):
        return None

    df = pl.read_csv(io.StringIO(raw), has_header=True)
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        # The venue changed the schema. Silently returning the columns that
        # survived would put a differently-shaped day into the same parquet.
        raise ValueError(f"{symbol} {day}: metrics is missing {missing}")

    # Parse, THEN clean, THEN count -- in that order, because the venue ships
    # days with an empty string where a ratio should be (ADAUSDT has whole
    # files of them) and a strict cast turns that into an exception rather than
    # into the fact it is. An absent ratio is null; it is not zero, and a zero
    # long/short ratio would read downstream as "everyone is short".
    df = df.select(
        pl.col("create_time").str.to_datetime("%Y-%m-%d %H:%M:%S").alias("ts"),
        pl.col("sum_open_interest").cast(pl.Float64, strict=False)
          .alias("open_interest"),
        pl.col("sum_open_interest_value").cast(pl.Float64, strict=False)
          .alias("open_interest_usd"),
        pl.col("count_toptrader_long_short_ratio").cast(pl.Float64, strict=False)
          .alias("toptrader_accounts_ls"),
        pl.col("sum_toptrader_long_short_ratio").cast(pl.Float64, strict=False)
          .alias("toptrader_positions_ls"),
        pl.col("count_long_short_ratio").cast(pl.Float64, strict=False)
          .alias("accounts_ls"),
        pl.col("sum_taker_long_short_vol_ratio").cast(pl.Float64, strict=False)
          .alias("taker_buy_sell"),
    )

    # Open interest is the column this module exists for, so a row without it
    # is not a row. The ratios are allowed to be null: they are secondary, and
    # dropping a whole day because one auxiliary series was not published would
    # throw away the measurement that was.
    df = df.filter(pl.col("open_interest").is_not_null())

    if df.height < ROWS_PER_DAY * (1.0 - MAX_MISSING_FRACTION):
        return None
    return df


def fetch(symbol: str, start: date | None = None,
          end: date | None = None, verbose: bool = True) -> pl.DataFrame:
    """Download every published day for one symbol and write it to the store.

    Resumes: days already held are not re-downloaded, so this is safe to run
    repeatedly and cheap to run daily.

    The FULL history is written, sealed days included, exactly as the panels
    hold theirs -- `load()` is the door that truncates. Storing a pre-truncated
    file would make this the one source a final test could not use, and would
    put a second rule about the seal next to the one that already exists.
    """
    out = path_for(symbol)
    held = pl.read_parquet(out) if out.exists() else None
    have = set(held["ts"].dt.date().unique().to_list()) if held is not None else set()

    start = start or date(2020, 1, 1)
    end = end or (date.today() - timedelta(days=1))

    wanted = []
    day = start
    while day <= end:
        if day not in have:
            wanted.append(day)
        day += timedelta(days=1)

    # Threads, not processes: every one of these is a socket waiting on
    # Binance, so this costs no CPU and must not be sized like the null's pool.
    # Sequentially the nine symbols took about an hour of pure round-trip.
    # DOWNLOAD_THREADS is deliberately modest -- the archive is a free service
    # and hammering it is how a free service stops being one.
    frames: list[pl.DataFrame] = []
    if wanted:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=DOWNLOAD_THREADS) as pool:
            got = list(pool.map(lambda d: _day_frame(symbol, d), wanted))
        frames = [f for f in got if f is not None]

    if not frames:
        if verbose:
            print(f"  {symbol}: nothing new")
        return held if held is not None else pl.DataFrame()

    fresh = pl.concat(frames)
    full = pl.concat([held, fresh]) if held is not None else fresh
    full = full.unique(subset=["ts"], keep="last").sort("ts")

    out.parent.mkdir(parents=True, exist_ok=True)
    full.write_parquet(out)
    if verbose:
        days = full["ts"].dt.date().n_unique()
        print(f"  {symbol}: +{fresh.height} rows, now {full.height} "
              f"over {days} days ({full['ts'].min()} .. {full['ts'].max()})")
    return full


def load(symbol: str, development_only: bool = True) -> pl.DataFrame:
    """Positioning for one symbol.  The only supported way to read this store.

    `development_only=True` is the default and the only value research may use:
    it truncates at the seal through the same `holdout.development_slice` the
    panels go through. The assertion afterwards is not belt-and-braces, it is
    the check that would fire if `development_slice` were ever weakened --
    2026-09-04 is on record as the day a mutation deleted the truncation from
    panel.load and all 248 tests stayed green.
    """
    p = path_for(symbol)
    if not p.exists():
        raise FileNotFoundError(
            f"no positioning data for {symbol}; run "
            f"`python -m orc.facts.positioning {symbol}` first")

    df = pl.read_parquet(p).sort("ts")
    if not development_only:
        if not holdout.sealed_reads_permitted():
            raise holdout.HoldoutViolation(
                "positioning.load(development_only=False) needs an open final "
                "test; there is no other way to read past the seal")
        holdout.note_sealed_read(f"positioning:{symbol}")
        return df

    df = holdout.development_slice(df, "ts")
    holdout.assert_development_only(df, "ts")
    return df


def registered_universe() -> list[str]:
    """Every symbol some registered hypothesis names.

    Read from the registry rather than kept as a list here, because a constant
    would be a second place the universe is written down and the two would
    drift -- and the one that matters is the one the hypotheses actually use.
    """
    import json

    seen: set[str] = set()
    d = config.REGISTRY
    for p in sorted(d.glob("*.json")) if d.exists() else []:
        try:
            seen.update(json.loads(p.read_text(encoding="utf-8"))
                        .get("universe") or [])
        except (OSError, ValueError):
            continue
    return sorted(seen)


def status() -> list[dict]:
    """What the store actually holds, per symbol, development side only."""
    out = []
    d = store()
    for p in sorted(d.glob("*.parquet")) if d.exists() else []:
        sym = p.stem
        try:
            df = load(sym)
        except (OSError, ValueError, holdout.HoldoutViolation) as exc:
            out.append({"symbol": sym, "status": str(exc)[:80]})
            continue
        out.append({
            "symbol": sym,
            "rows": df.height,
            "days": df["ts"].dt.date().n_unique() if df.height else 0,
            "first": str(df["ts"].min()) if df.height else None,
            "last": str(df["ts"].max()) if df.height else None,
        })
    return out


def main(argv: list[str]) -> int:
    if "--status" in argv:
        rows = status()
        if not rows:
            print("positioning: nothing held yet")
            return 0
        print(f"positioning store: {store()}   (seal {config.HOLDOUT_START})")
        for r in rows:
            if "rows" not in r:
                print(f"  {r['symbol']:12s} {r['status']}")
                continue
            print(f"  {r['symbol']:12s} {r['rows']:>8,} rows over {r['days']:>5,} "
                  f"days   {str(r['first'])[:10]} .. {str(r['last'])[:10]}")
        return 0

    symbols = [a for a in argv if not a.startswith("-")]
    if "--universe" in argv:
        symbols = registered_universe()
    if not symbols:
        print(__doc__)
        return 2

    print(f"positioning: {len(symbols)} symbol(s) -> {store()}")
    for s in symbols:
        fetch(s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
