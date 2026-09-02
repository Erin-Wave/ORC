"""ORC | Panel access.

One place that assembles price and funding onto a single bar clock, applies the
holdout seal, and hands research plain numpy arrays.  Research code must not
open parquet files directly: it would bypass the seal.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import polars as pl

from orc import config, holdout

# A stride expressed in bars only means a duration if the grid is continuous.
MAX_MISSING_BAR_FRACTION = 0.005


@dataclass(frozen=True)
class Panel:
    symbol: str
    clock: str
    ts: np.ndarray            # datetime64[ms]
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    funding_rate: np.ndarray  # per bar, zero except on settlement bars
    holdout_state: str
    panel_hash: str

    def __len__(self) -> int:
        return int(self.close.size)

    @property
    def bars_per_day(self) -> int:
        return {"1m": 1440, "1h": 24}[self.clock]

    def bars(self, days: float) -> int:
        return int(round(days * self.bars_per_day))

    @property
    def funding_flow(self) -> np.ndarray:
        """P[t] * f[t], the input the analytic evaluator wants."""
        return self.close * self.funding_rate

    def has_funding(self) -> bool:
        return bool(np.any(self.funding_rate != 0.0))


def panel_path(symbol: str, clock: str) -> Path:
    return config.FACTS / f"panel_{clock}" / f"{symbol}.parquet"


def funding_path(symbol: str) -> Path:
    return config.FACTS / "funding" / f"{symbol}.parquet"


def available_symbols(clock: str = "1h") -> list[str]:
    d = config.FACTS / f"panel_{clock}"
    return sorted(p.stem for p in d.glob("*.parquet")) if d.exists() else []


def _hash_arrays(*arrays: np.ndarray) -> str:
    h = hashlib.sha256()
    for a in arrays:
        h.update(np.ascontiguousarray(a).tobytes())
    return h.hexdigest()[:32]


def load(
    symbol: str,
    clock: str = "1h",
    development_only: bool = True,
    with_funding: bool = True,
) -> Panel:
    """Load one symbol.

    `development_only=True` (the default, and the only value research may use)
    truncates the series at the seal.  Passing False is legal only from
    orc.holdout.open_final_test, which is audited.
    """
    p = panel_path(symbol, clock)
    if not p.exists():
        raise FileNotFoundError(f"no {clock} panel for {symbol}; run orc.facts.build_panel")
    df = pl.read_parquet(p)

    if development_only:
        df = holdout.development_slice(df)
        state = "DEVELOPMENT"
    else:
        state = "SEALED_INCLUDED"
    if df.height == 0:
        raise ValueError(f"{symbol}: no bars left after the holdout seal")

    # Bar index is used as a clock (a stride of 168 hourly bars must mean one
    # week).  That is only true on a continuous grid, so verify it rather than
    # assume it: a symbol with real outages would silently rescale every horizon.
    ts_h = df["ts"].to_numpy().astype("datetime64[m]").astype(np.int64)
    step = {"1m": 1, "1h": 60}[clock]
    expected = (ts_h[-1] - ts_h[0]) // step + 1
    missing = 1.0 - df.height / float(expected)
    if missing > MAX_MISSING_BAR_FRACTION:
        raise ValueError(
            f"{symbol}: {missing:.3%} of {clock} bars are missing "
            f"(limit {MAX_MISSING_BAR_FRACTION:.1%}); bar index is not a reliable clock")

    fr = np.zeros(df.height, dtype=np.float64)
    if with_funding and funding_path(symbol).exists():
        from orc.facts.fetch_vision import funding_rate_per_bar
        fund = pl.read_parquet(funding_path(symbol))
        fr = funding_rate_per_bar(df["ts"], fund)

    close = df["close"].to_numpy().astype(np.float64)
    return Panel(
        symbol=symbol, clock=clock,
        ts=df["ts"].to_numpy(),
        open=df["open"].to_numpy().astype(np.float64),
        high=df["high"].to_numpy().astype(np.float64),
        low=df["low"].to_numpy().astype(np.float64),
        close=close,
        volume=df["volume"].to_numpy().astype(np.float64),
        funding_rate=fr,
        holdout_state=state,
        # high and low decide every liquidation, stop and take-profit, so a
        # panel that differs only in a wick is different data. Hashing close
        # and funding alone meant a corrected wick left the identity unchanged,
        # the ledger's UNIQUE key matched, and the new liquidation rate was
        # discarded as a duplicate of the old one.
        panel_hash=_hash_arrays(close, fr,
                                df["high"].to_numpy().astype(np.float64),
                                df["low"].to_numpy().astype(np.float64)),
    )


def load_many(symbols: list[str], clock: str = "1h", **kw) -> dict[str, Panel]:
    out: dict[str, Panel] = {}
    for s in symbols:
        try:
            out[s] = load(s, clock, **kw)
        except (FileNotFoundError, ValueError):
            continue
    return out
