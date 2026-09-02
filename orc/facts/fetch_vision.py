"""ORC | Free data from the official Binance archive (data.binance.vision).

No API key, no rate-limit account, no vendor bill.  Three things are pulled
that the local 1m archive does not contain and that DCA research on perpetuals
cannot be done without:

  fundingRate   what a long actually pays to hold.  On a perpetual this is
                charged on the full notional regardless of leverage, so it is
                not a rounding error -- it is often the dominant term.

  lifecycle     first and last month each symbol ever traded, INCLUDING symbols
                that were delisted.  Without this the universe is survivorship
                biased and every alt-basket result is inflated.

  markPriceKlines (optional) the price Binance actually liquidates against.

The bucket is listed via its public S3 XML interface, which is how delisted
symbols are discovered: they are absent from exchangeInfo but their historical
folders remain.
"""
from __future__ import annotations

import io
import time
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET

import polars as pl
import requests

from orc import config

BASE = "https://data.binance.vision"
S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"
UM_MONTHLY = "data/futures/um/monthly"

_SESSION = requests.Session()
_SESSION.headers["User-Agent"] = "orc-research/1.0"


def _get(url: str, tries: int = 4, timeout: int = 60) -> requests.Response | None:
    """GET with backoff.  A 404 is a fact (that month does not exist), not an error."""
    for attempt in range(tries):
        try:
            r = _SESSION.get(url, timeout=timeout)
        except requests.RequestException:
            time.sleep(1.5 * (attempt + 1))
            continue
        if r.status_code == 404:
            return None
        if r.ok:
            return r
        time.sleep(1.5 * (attempt + 1))
    return None


# --------------------------------------------------------------------------
# universe, including delisted symbols
# --------------------------------------------------------------------------
def list_symbols_ever(dataset: str = "klines") -> list[str]:
    """Every symbol that ever had a folder in the archive, delisted included."""
    prefix = f"{UM_MONTHLY}/{dataset}/"
    symbols: list[str] = []
    token = None
    while True:
        url = f"{S3}?list-type=2&delimiter=/&prefix={prefix}"
        if token:
            url += f"&continuation-token={requests.utils.quote(token, safe='')}"
        r = _get(url)
        if r is None:
            break
        root = ET.fromstring(r.content)
        for cp in root.findall(f"{NS}CommonPrefixes"):
            p = cp.findtext(f"{NS}Prefix") or ""
            name = p[len(prefix):].strip("/")
            if name:
                symbols.append(name)
        if (root.findtext(f"{NS}IsTruncated") or "false").lower() != "true":
            break
        token = root.findtext(f"{NS}NextContinuationToken")
        if not token:
            break
    return sorted(set(symbols))


def list_months(symbol: str, dataset: str = "fundingRate",
                interval: str | None = None) -> list[str]:
    """The YYYY-MM strings actually present for a symbol.

    `klines` is stored one level deeper, under an interval folder.  Passing the
    interval avoids listing every resolution of every symbol.
    """
    prefix = f"{UM_MONTHLY}/{dataset}/{symbol}/"
    if interval:
        prefix += f"{interval}/"
    months: list[str] = []
    token = None
    while True:
        url = f"{S3}?list-type=2&prefix={prefix}"
        if token:
            url += f"&continuation-token={requests.utils.quote(token, safe='')}"
        r = _get(url)
        if r is None:
            break
        root = ET.fromstring(r.content)
        for c in root.findall(f"{NS}Contents"):
            key = c.findtext(f"{NS}Key") or ""
            if key.endswith(".zip"):
                months.append(key.rsplit("-", 2)[-2] + "-" + key.rsplit("-", 1)[-1][:2])
        if (root.findtext(f"{NS}IsTruncated") or "false").lower() != "true":
            break
        token = root.findtext(f"{NS}NextContinuationToken")
        if not token:
            break
    return sorted(set(months))


# --------------------------------------------------------------------------
# funding
# --------------------------------------------------------------------------
FUNDING_COLUMNS = ["calc_time", "funding_interval_hours", "last_funding_rate"]


def _read_zip_csv(content: bytes, columns: list[str]) -> pl.DataFrame | None:
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        return None
    name = zf.namelist()[0]
    raw = zf.read(name)
    has_header = raw[:16].lstrip().lower().startswith(columns[0].encode()[:6])
    df = pl.read_csv(io.BytesIO(raw), has_header=has_header,
                     new_columns=None if has_header else columns,
                     infer_schema_length=1000)
    if has_header:
        df = df.rename({c: t for c, t in zip(df.columns, columns)})
    return df


def download_funding(symbol: str, months: list[str] | None = None) -> pl.DataFrame:
    """All available monthly funding settlements for one symbol."""
    months = months or list_months(symbol, "fundingRate")
    frames = []
    for m in months:
        url = f"{BASE}/{UM_MONTHLY}/fundingRate/{symbol}/{symbol}-fundingRate-{m}.zip"
        r = _get(url)
        if r is None:
            continue
        df = _read_zip_csv(r.content, FUNDING_COLUMNS)
        if df is not None and df.height:
            frames.append(df)
    if not frames:
        return pl.DataFrame(schema={"ts": pl.Datetime, "funding_rate": pl.Float64,
                                    "interval_hours": pl.Int64})
    out = pl.concat(frames, how="vertical_relaxed")
    return (
        out.with_columns([
            pl.col("calc_time").cast(pl.Int64).cast(pl.Datetime("ms")).alias("ts"),
            pl.col("last_funding_rate").cast(pl.Float64).alias("funding_rate"),
            pl.col("funding_interval_hours").cast(pl.Int64).alias("interval_hours"),
        ])
        .select(["ts", "funding_rate", "interval_hours"])
        .unique(subset=["ts"], keep="first")
        .sort("ts")
    )


def fetch_funding_for(symbols: list[str], out_dir: Path | None = None) -> dict:
    out_dir = out_dir or (config.FACTS / "funding")
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {}
    for i, s in enumerate(symbols, 1):
        target = out_dir / f"{s}.parquet"
        if target.exists():
            summary[s] = "cached"
            print(f"[{i}/{len(symbols)}] {s:14s} cached", flush=True)
            continue
        df = download_funding(s)
        if df.height == 0:
            summary[s] = "empty"
            print(f"[{i}/{len(symbols)}] {s:14s} EMPTY", flush=True)
            continue
        df.write_parquet(target, compression="zstd")
        summary[s] = f"{df.height} settlements {df['ts'][0]} -> {df['ts'][-1]}"
        print(f"[{i}/{len(symbols)}] {s:14s} {df.height:6d} settlements", flush=True)
    return summary


# --------------------------------------------------------------------------
# klines for symbols the local archive never had (delisted ones, mostly)
# --------------------------------------------------------------------------
KLINE_COLUMNS = ["open_time", "open", "high", "low", "close", "volume",
                 "close_time", "quote_volume", "trades",
                 "taker_buy_base", "taker_buy_quote", "ignore"]


def download_klines(symbol: str, interval: str = "1h",
                    months: list[str] | None = None) -> pl.DataFrame:
    """Monthly klines straight from the archive.

    This is how a delisted symbol is brought back into the universe.  A symbol
    that stopped trading is absent from exchangeInfo but its folders remain, and
    leaving it out is exactly the bias that makes every alt-basket backtest look
    better than the experience of holding one.
    """
    months = months or list_months(symbol, "klines", interval)
    frames = []
    for m in months:
        url = (f"{BASE}/{UM_MONTHLY}/klines/{symbol}/{interval}/"
               f"{symbol}-{interval}-{m}.zip")
        r = _get(url)
        if r is None:
            continue
        df = _read_zip_csv(r.content, KLINE_COLUMNS)
        if df is not None and df.height:
            frames.append(df.select(KLINE_COLUMNS[:9]))
    if not frames:
        return pl.DataFrame()
    out = pl.concat(frames, how="vertical_relaxed")
    return (
        out.with_columns([
            pl.col("open_time").cast(pl.Int64).cast(pl.Datetime("ms")).alias("ts"),
            pl.col("open").cast(pl.Float64), pl.col("high").cast(pl.Float64),
            pl.col("low").cast(pl.Float64), pl.col("close").cast(pl.Float64),
            pl.col("volume").cast(pl.Float64),
            pl.col("quote_volume").cast(pl.Float64),
            pl.col("trades").cast(pl.Int64),
        ])
        .select(["ts", "open", "high", "low", "close", "volume", "quote_volume", "trades"])
        .unique(subset=["ts"], keep="first")
        .sort("ts")
        .filter((pl.col("close") > 0) & (pl.col("volume") >= 0))
    )


def fetch_panels_for(symbols: list[str], interval: str = "1h") -> dict:
    """Materialise missing symbols directly into the 1h panel directory."""
    out_dir = config.FACTS / f"panel_{interval}"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {}
    for i, s in enumerate(symbols, 1):
        target = out_dir / f"{s}.parquet"
        if target.exists():
            summary[s] = "cached"
            continue
        df = download_klines(s, interval)
        if df.height == 0:
            summary[s] = "empty"
            print(f"[{i}/{len(symbols)}] {s:16s} EMPTY", flush=True)
            continue
        df.write_parquet(target, compression="zstd", compression_level=9)
        summary[s] = f"{df.height} bars"
        print(f"[{i}/{len(symbols)}] {s:16s} {df.height:7d} bars "
              f"{df['ts'][0]} -> {df['ts'][-1]}", flush=True)
    return summary


# --------------------------------------------------------------------------
# lifecycle -- the survivorship-bias fix
# --------------------------------------------------------------------------
@dataclass
class Lifecycle:
    symbol: str
    first_month: str
    last_month: str
    still_listed: bool


def build_lifecycle(archive_cutoff: date | None = None) -> pl.DataFrame:
    """First/last month per symbol from the archive, cross-checked against the
    live exchange so delistings are explicit rather than inferred from a gap."""
    cutoff = archive_cutoff or config.DATA_END
    live: set[str] = set()
    r = _get("https://fapi.binance.com/fapi/v1/exchangeInfo", tries=3, timeout=30)
    if r is not None:
        try:
            live = {s["symbol"] for s in r.json().get("symbols", [])
                    if s.get("status") == "TRADING"}
        except Exception:                                       # noqa: BLE001
            live = set()

    rows = []
    for sym in list_symbols_ever("klines"):
        months = list_months(sym, "klines", "1d")
        if not months:
            continue
        rows.append(Lifecycle(sym, months[0], months[-1], sym in live))
        print(f"  {sym:16s} {months[0]} -> {months[-1]}"
              f"{'' if sym in live else '   DELISTED'}", flush=True)

    return pl.DataFrame([{
        "symbol": r_.symbol, "first_month": r_.first_month,
        "last_month": r_.last_month, "still_listed": r_.still_listed,
    } for r_ in rows])


# --------------------------------------------------------------------------
# aligning funding onto a bar clock
# --------------------------------------------------------------------------
def funding_rate_per_bar(bar_ts: pl.Series, funding: pl.DataFrame) -> "np.ndarray":
    """Place each settlement on the bar that contains it; zero everywhere else.

    A settlement is charged on the bar it falls in, never spread across bars:
    that is how the exchange does it, and spreading would understate the pain
    of holding through a funding spike.
    """
    import numpy as np

    n = bar_ts.len()
    out = np.zeros(n, dtype=np.float64)
    if funding.height == 0:
        return out
    bars = bar_ts.to_numpy()
    fts = funding["ts"].to_numpy()
    rate = funding["funding_rate"].to_numpy().astype(np.float64)
    pos = np.searchsorted(bars, fts, side="right") - 1
    ok = (pos >= 0) & (pos < n)
    np.add.at(out, pos[ok], rate[ok])
    return out


if __name__ == "__main__":
    import sys

    config.ensure_dirs()
    args = sys.argv[1:]
    if args and args[0] == "lifecycle":
        df = build_lifecycle()
        df.write_parquet(config.FACTS / "lifecycle.parquet", compression="zstd")
        print(f"\n{df.height} symbols, {int((~df['still_listed']).sum())} delisted")
    else:
        fetch_funding_for(args or ["BTCUSDT"])
