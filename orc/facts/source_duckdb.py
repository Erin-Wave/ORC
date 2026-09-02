"""ORC | duckdb source for the panel builder.

The vendor archive ships the same market data twice: as daily 1-minute CSVs
under `1m/`, and as a single duckdb store.  They were compared bar by bar over
their whole overlap on BTCUSDT, ADAUSDT and AVAXUSDT: the timestamp sets are
identical and every field matches except one row per symbol -- the final bar of
the CSV dump, which was captured mid-minute and is therefore truncated (ADAUSDT
2025-07-23 20:00 carries 18 trades in the CSV against 2797 in the store).  The
store is the better source, and it carries 810 symbols to the CSVs' 481 and runs
a year further.

Reading it has three traps, all silent:

  * `timestamp` is BIGINT **milliseconds**.  `to_timestamp()` reads seconds and
    lands in the year 51656 without complaining.  `epoch_ms()` is correct.
  * the store's saved session timezone is `Asia/Seoul`, so `strftime` over a
    TIMESTAMPTZ shifts every bar nine hours.  The connection forces UTC and
    then checks that it took.
  * prices arrive as DECIMAL, not DOUBLE.  Left alone they propagate into numpy
    as objects.

Nothing here cleans anything.  The frozen rules in `build_panel.clean_1m` still
decide what a usable bar is, and `QA_PANEL.json` is still the record.
"""
from __future__ import annotations

import polars as pl

from orc import config

DB_PATH = config.RAW_1M.parent / "binancefuturesdata.duckdb"

# The store keeps several resolutions in one table.  ORC builds from 1-minute
# bars only, so hourly aggregation sees the true intrabar extremes.
INTERVAL_1M = 1

_FLOAT_COLS = ("open", "high", "low", "close", "volume", "quote_volume",
               "taker_buy_base", "taker_buy_quote")


def connect():
    """Read-only connection with the timezone pinned to UTC."""
    try:
        import duckdb
    except ModuleNotFoundError as exc:                              # pragma: no cover
        raise ModuleNotFoundError(
            "the panel builder needs duckdb: pip install duckdb. "
            "It is a local build dependency only -- the cloud worker consumes "
            "the published bundle and never reads this store."
        ) from exc

    if not DB_PATH.exists():
        raise FileNotFoundError(f"duckdb store not found: {DB_PATH}")

    con = duckdb.connect(str(DB_PATH), read_only=True)
    con.execute("SET TimeZone='UTC'")
    tz = con.execute("SELECT current_setting('TimeZone')").fetchone()[0]
    if tz != "UTC":                                                 # pragma: no cover
        raise RuntimeError(f"refusing to read with TimeZone={tz!r}; bars would shift")
    return con


def list_symbols(con=None) -> list[str]:
    con = con or connect()
    rows = con.execute(
        "SELECT DISTINCT symbol FROM quote WHERE interval=? ORDER BY symbol",
        [INTERVAL_1M]).fetchall()
    return [r[0] for r in rows]


def load_raw_1m(symbol: str, con=None) -> pl.DataFrame:
    """One symbol's 1-minute bars, shaped exactly like the CSV loader's output.

    `ts` is returned as the same text the CSVs carry so both sources go through
    one parser, and one set of cleaning rules, with nothing branching on which
    archive a bar came from.
    """
    con = con or connect()
    tbl = con.execute(
        """
        SELECT strftime(epoch_ms(timestamp), '%Y-%m-%d %H:%M:%S') AS ts,
               open, high, low, close, volume, quote_volume,
               taker_buy_volume       AS taker_buy_base,
               taker_buy_quote_volume AS taker_buy_quote,
               trade_count            AS trades
        FROM quote WHERE symbol=? AND interval=? ORDER BY timestamp
        """, [symbol, INTERVAL_1M]).arrow()

    df = pl.from_arrow(tbl)
    if df.height == 0:
        return df
    return df.with_columns(
        [pl.col(c).cast(pl.Float64) for c in _FLOAT_COLS]
        + [pl.col("trades").cast(pl.Int64)]
    )
