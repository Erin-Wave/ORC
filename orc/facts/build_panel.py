"""ORC | Panel builder.

Turns the read-only vendor archive of daily 1-minute CSVs into two frozen
research panels:

  facts/panel_1m/<SYM>.parquet   full resolution, stays on this machine.
                                 Feeds the analytic (all-start-date) evaluator
                                 and the final execution-realism pass.

  facts/panel_1h/<SYM>.parquet   the simulation clock, aggregated FROM the 1m
                                 bars so intrabar extremes survive.  Small
                                 enough to ship to a free cloud worker.

The archive contains pre-listing padding: bars whose OHLC are all identical and
whose volume is zero (verified on BTCUSDT_2019-09-08, a flat 10000.00 with zero
volume).  Those bars are DROPPED, never forward-filled: a synthetic flat stretch
at the head of a series manufactures free profit for a dip-buying rule.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

import polars as pl

from orc import config

COLUMNS = ["ts", "open", "high", "low", "close",
           "volume", "quote_volume", "taker_buy_base", "taker_buy_quote", "trades"]

SCHEMA = {
    "ts": pl.String, "open": pl.Float64, "high": pl.Float64, "low": pl.Float64,
    "close": pl.Float64, "volume": pl.Float64, "quote_volume": pl.Float64,
    "taker_buy_base": pl.Float64, "taker_buy_quote": pl.Float64, "trades": pl.Int64,
}

KEEP = ["ts", "open", "high", "low", "close", "volume", "quote_volume", "trades"]


@dataclass
class SymbolQA:
    symbol: str
    rows_raw: int
    rows_dropped_padding: int
    rows_dropped_duplicate: int
    rows_final: int
    first_ts: str
    last_ts: str
    gap_count: int
    largest_gap_minutes: int
    nonpositive_price_rows: int
    ohlc_violation_rows: int
    usable: bool
    reject_reason: str | None = None


def symbol_dir(symbol: str) -> Path:
    return config.RAW_1M / symbol


def list_symbols() -> list[str]:
    return sorted(p.name for p in config.RAW_1M.iterdir() if p.is_dir())


def load_raw_1m(symbol: str) -> pl.DataFrame:
    glob = str(symbol_dir(symbol) / (symbol + "_*.csv")).replace("\\", "/")
    lf = pl.scan_csv(glob, has_header=False, new_columns=COLUMNS,
                     schema_overrides=SCHEMA, ignore_errors=True)
    return lf.collect()


def clean_1m(df: pl.DataFrame) -> tuple[pl.DataFrame, dict]:
    """Apply the frozen cleaning rules and report exactly what was removed."""
    rows_raw = df.height

    df = df.with_columns(
        pl.col("ts").str.to_datetime("%Y-%m-%d %H:%M:%S", strict=False).alias("ts")
    ).drop_nulls("ts")

    if config.DROP_ZERO_VOLUME_FLAT:
        padding = (
            (pl.col("open") == pl.col("high"))
            & (pl.col("high") == pl.col("low"))
            & (pl.col("low") == pl.col("close"))
            & (pl.col("volume") <= 0.0)
        )
        n_padding = int(df.select(padding.sum()).item() or 0)
        df = df.filter(~padding)
    else:
        n_padding = 0

    before = df.height
    df = df.unique(subset=["ts"], keep="first").sort("ts")
    n_dupes = before - df.height

    nonpos = int(df.select(
        ((pl.col("open") <= 0) | (pl.col("high") <= 0)
         | (pl.col("low") <= 0) | (pl.col("close") <= 0)).sum()
    ).item() or 0)
    df = df.filter((pl.col("open") > 0) & (pl.col("high") > 0)
                   & (pl.col("low") > 0) & (pl.col("close") > 0))

    violation = int(df.select(
        ((pl.col("high") < pl.col("low"))
         | (pl.col("high") < pl.col("open")) | (pl.col("high") < pl.col("close"))
         | (pl.col("low") > pl.col("open")) | (pl.col("low") > pl.col("close"))).sum()
    ).item() or 0)

    gaps = df.select(
        (pl.col("ts").diff().dt.total_minutes() - 1).clip(lower_bound=0).alias("g")
    )["g"].drop_nulls()
    gap_count = int((gaps > 0).sum())
    largest_gap = int(gaps.max() or 0)

    stats = dict(rows_raw=rows_raw, rows_dropped_padding=n_padding,
                 rows_dropped_duplicate=n_dupes, rows_final=df.height,
                 gap_count=gap_count, largest_gap_minutes=largest_gap,
                 nonpositive_price_rows=nonpos, ohlc_violation_rows=violation)
    return df, stats


def to_hourly(df: pl.DataFrame) -> pl.DataFrame:
    """Aggregate 1m to 1h.  high/low are the true intrabar extremes, so a
    liquidation test on the hourly bar sees what the minute bars saw."""
    return (
        df.sort("ts")
          .group_by_dynamic("ts", every="1h", closed="left", label="left")
          .agg([
              pl.col("open").first().alias("open"),
              pl.col("high").max().alias("high"),
              pl.col("low").min().alias("low"),
              pl.col("close").last().alias("close"),
              pl.col("volume").sum().alias("volume"),
              pl.col("quote_volume").sum().alias("quote_volume"),
              pl.col("trades").sum().alias("trades"),
              pl.len().alias("minutes_present"),
          ])
    )


def build_symbol(symbol: str, out_1m: Path, out_1h: Path) -> SymbolQA:
    df = load_raw_1m(symbol)
    if df.height == 0:
        return SymbolQA(symbol, 0, 0, 0, 0, "", "", 0, 0, 0, 0,
                        usable=False, reject_reason="no rows in archive")

    clean, st = clean_1m(df)
    if clean.height < config.MIN_BARS_REQUIRED:
        return SymbolQA(symbol, st["rows_raw"], st["rows_dropped_padding"],
                        st["rows_dropped_duplicate"], clean.height, "", "",
                        st["gap_count"], st["largest_gap_minutes"],
                        st["nonpositive_price_rows"], st["ohlc_violation_rows"],
                        usable=False,
                        reject_reason="only %d bars, need %d" % (clean.height, config.MIN_BARS_REQUIRED))

    out_1m.parent.mkdir(parents=True, exist_ok=True)
    out_1h.parent.mkdir(parents=True, exist_ok=True)
    slim = clean.select(KEEP)
    slim.write_parquet(out_1m, compression="zstd", compression_level=9)
    to_hourly(slim).write_parquet(out_1h, compression="zstd", compression_level=9)

    return SymbolQA(symbol, st["rows_raw"], st["rows_dropped_padding"],
                    st["rows_dropped_duplicate"], clean.height,
                    str(clean["ts"][0]), str(clean["ts"][-1]),
                    st["gap_count"], st["largest_gap_minutes"],
                    st["nonpositive_price_rows"], st["ohlc_violation_rows"],
                    usable=True)


def build_all(symbols=None, limit=None):
    config.ensure_dirs()
    syms = symbols or list_symbols()
    if limit:
        syms = syms[:limit]
    d1m = config.FACTS / "panel_1m"
    d1h = config.FACTS / "panel_1h"
    report = []
    for i, s in enumerate(syms, 1):
        try:
            qa = build_symbol(s, d1m / (s + ".parquet"), d1h / (s + ".parquet"))
        except Exception as exc:                                   # noqa: BLE001
            qa = SymbolQA(s, 0, 0, 0, 0, "", "", 0, 0, 0, 0,
                          usable=False, reject_reason=type(exc).__name__ + ": " + str(exc))
        report.append(qa)
        flag = "OK  " if qa.usable else "SKIP"
        tail = "" if qa.usable else "  <- " + str(qa.reject_reason)
        print("[%d/%d] %-14s %s rows=%9d pad=%7d gaps=%5d%s"
              % (i, len(syms), s, flag, qa.rows_final, qa.rows_dropped_padding,
                 qa.gap_count, tail), flush=True)

    (config.FACTS / "QA_PANEL.json").write_text(
        json.dumps([asdict(r) for r in report], indent=2, default=str), encoding="utf-8")
    return report


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0].isdigit():
        build_all(limit=int(args[0]))
    elif args:
        build_all(symbols=args)
    else:
        build_all()
