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

# What `holdout_state` on a Panel and on every ledger row can say.  Named here
# because the ledger stores the string and code elsewhere has to select on it:
# `orc.target` asks for development rows only, and a stop condition that could
# be satisfied by a sealed measurement would be circular in the one place it
# must not be.  A literal in two files is a rename away from silently matching
# nothing, which reads as "no rows meet the target" -- the safe-looking answer.
DEVELOPMENT = "DEVELOPMENT"
SEALED_ONLY = "SEALED_ONLY"
SEALED_INCLUDED = "SEALED_INCLUDED"

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
    # Which bars a settlement actually landed on. A settlement whose rate was
    # exactly 0.0 is a settlement; funding_rate cannot say so and this can.
    funding_settled: np.ndarray
    holdout_state: str
    panel_hash: str
    # Contracts outstanding, one level per bar, or None when the caller did not
    # ask for it. Opt-in rather than always loaded because the positioning
    # store covers the researched symbols and not the other ~470, and a Panel
    # that silently carried zeros for the rest would be the funding defect
    # again in a new column.
    open_interest: np.ndarray | None = None

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

    def has_positioning(self) -> bool:
        """Is there an open-interest series on this panel at all?

        None and an array of zeros are different facts, for the same reason
        has_funding exists: a rule that reads open interest must be refused on
        a panel that has none, rather than handed a column of zeros it will
        read as "nobody held a position".
        """
        return self.open_interest is not None

    def has_funding(self) -> bool:
        # A symbol every one of whose settlements printed 0.0 still has a
        # funding history; asking the rate array cannot tell that apart from
        # a symbol that has none, and a carry rule was refused on the strength
        # of it with "no funding history; a carry rule has nothing to read".
        return bool(np.any(self.funding_settled))


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


def _assert_bar_index_is_a_clock(df, symbol: str, clock: str) -> None:
    """Bar index is used as a clock, so verify that it is one.

    A stride of 168 hourly bars must mean one week, and that is only true on a
    grid that is ordered, unique and on its own step.  A symbol with real
    outages would otherwise silently rescale every horizon in the project.

    Its own function so that it can be tested on a frame rather than only
    through a parquet file on disk -- the three ways it can be violated all
    describe files that must never be written, so there is nothing on disk to
    point it at.
    """
    ts_h = df["ts"].to_numpy().astype("datetime64[m]").astype(np.int64)
    step = {"1m": 1, "1h": 60}[clock]

    # Order and uniqueness FIRST, because the missing-bar fraction below cannot
    # see either.  `missing = 1 - height/expected` only goes positive when bars
    # are SHORT, so a duplicated bar or a non-monotonic timestamp made height
    # meet or exceed expected, drove `missing` NEGATIVE, and sailed through the
    # one check standing between a broken file and "bar index is a clock".  A
    # duplicated bar shifts every later index by one: a 168-bar stride stops
    # being a week from that point on, and nothing downstream can tell.
    if ts_h.size >= 2:
        d = np.diff(ts_h)
        if np.any(d <= 0):
            n_bad = int(np.count_nonzero(d <= 0))
            raise ValueError(
                f"{symbol}: {n_bad} of {df.height} {clock} bars are duplicated or "
                "out of order; bar index is not a reliable clock")
        # Gaps are tolerated up to the fraction below, but a gap that is not a
        # whole number of bars means the grid itself is off its step, and no
        # count of missing bars can express that.
        off = int(np.count_nonzero(d % step != 0))
        if off:
            raise ValueError(
                f"{symbol}: {off} {clock} bar gap(s) are not a whole multiple of "
                f"{step}m; the bar grid is not aligned to its own clock")

    expected = (ts_h[-1] - ts_h[0]) // step + 1
    missing = 1.0 - df.height / float(expected)
    if missing > MAX_MISSING_BAR_FRACTION:
        raise ValueError(
            f"{symbol}: {missing:.3%} of {clock} bars are missing "
            f"(limit {MAX_MISSING_BAR_FRACTION:.1%}); bar index is not a reliable clock")


def load(
    symbol: str,
    clock: str = "1h",
    development_only: bool = True,
    with_funding: bool = True,
    sealed_only: bool = False,
    with_positioning: bool = False,
) -> Panel:
    """Load one symbol.

    `development_only=True` (the default, and the only value research may use)
    truncates the series at the seal.  Anything else raises unless a final test
    is open -- see orc.holdout.final_test -- and every such read is recorded
    against the opening that permitted it.

    `sealed_only=True` is what a final test actually wants: the sealed span on
    its own.  The gated door originally offered only development_only=False,
    which returns the two spans concatenated -- 39,243 development bars against
    21,505 sealed ones on BTCUSDT, so 64.6 percent of the window is the data the
    candidate was selected on.  A metric over that is not an out-of-sample
    measurement, it just looks like one, and there are three of them for the
    life of the project.
    """
    if sealed_only and not development_only:
        raise ValueError("pass sealed_only=True on its own; the two spans are different measurements")
    p = panel_path(symbol, clock)
    if not p.exists():
        raise FileNotFoundError(f"no {clock} panel for {symbol}; run orc.facts.build_panel")
    df = pl.read_parquet(p)

    if sealed_only:
        # Refuses unless a final test is open. This used to be a docstring.
        holdout.note_sealed_read(f"{symbol}/{clock} sealed")
        df = holdout.sealed_slice(df)
        state = SEALED_ONLY
    elif development_only:
        df = holdout.development_slice(df)
        state = DEVELOPMENT
    else:
        holdout.note_sealed_read(f"{symbol}/{clock} full")
        state = SEALED_INCLUDED
    if df.height == 0:
        raise ValueError(
            f"{symbol}: no bars left in the {state} span")

    _assert_bar_index_is_a_clock(df, symbol, clock)

    fr = np.zeros(df.height, dtype=np.float64)
    settled = np.zeros(df.height, dtype=bool)
    if with_funding and not funding_path(symbol).exists():
        # kernel_review 2026-09-05. The earlier fix covered a funding table
        # that starts LATE and left the one that is absent entirely: 38 of the
        # 325 hourly panels have no funding parquet at all, and many are the
        # delisted symbols KT-3 has just made admissible. Those came back with
        # funding_rate all 0.0, and run_dca_trial does not check has_funding()
        # -- so AUDIOUSDT recorded tm_q05=0.3646 with funding_frac_q50 exactly
        # 0.00000000 as an ordinary trial. KT-1 measured that bill at 36% of
        # contributed capital.
        #
        # `with_funding=True` is the default, so this refuses rather than
        # returning zeros: a caller that genuinely does not need funding says
        # so, and a grid point that cannot be evaluated is information about
        # the grid rather than a cheap version of the trade.
        raise FileNotFoundError(
            f"{symbol}: no funding history, and with_funding=True would charge "
            "the position nothing at all -- which is not a conservative error. "
            "Fetch it (`python -m orc.facts.fetch_vision {symbol}`) or pass "
            "with_funding=False and say why in the claim.")
    if with_funding and funding_path(symbol).exists():
        from orc.facts.fetch_vision import funding_rate_per_bar
        fund = pl.read_parquet(funding_path(symbol))

        # Bars BEFORE the funding record begins used to be filled with
        # funding_rate 0.0 and funding_settled False and handed to research
        # unchanged, and has_funding() answered True because settlements exist
        # later in the same panel. So "funding was zero here" and "there is no
        # funding record here" were the same panel, and the difference is the
        # dominant term for Track A: KT-1 measured the funding bill at 36% of
        # contributed capital.
        #
        # Measured 2026-09-05 over the nine researched symbols: BTCUSDT had
        # 2,739 such bars (6.98% of its development window) and ETHUSDT 832
        # (2.23%). Seven had none. Those bars were being charged nothing.
        #
        # funding_settled cannot rescue this downstream. Funding settles every
        # eight hours, so False is the ordinary state of a bar and carries no
        # information about whether a record exists.
        #
        # The panel therefore STARTS where the funding record starts. That is
        # not a loss of data, it is the end of the span this data can answer a
        # funding question about, and it applies only when funding was asked
        # for -- with_funding=False is untouched.
        if fund.height:
            first = fund["ts"].min()
            keep = df["ts"] >= first
            n_before = int(df.height - keep.sum())
            if n_before:
                df = df.filter(keep)
                if df.height == 0:
                    raise ValueError(
                        f"{symbol}: the funding record starts at {first}, "
                        f"after every bar in the {state} span")
                _assert_bar_index_is_a_clock(df, symbol, clock)
        fr, settled = funding_rate_per_bar(df["ts"], fund)

    oi = None
    if with_positioning and sealed_only:
        # kernel_review 2026-09-05, in code written an hour earlier. Line 177
        # refuses sealed_only together with development_only=False, so
        # development_only is necessarily True here and was passed straight to
        # positioning.load -- which truncates at the seal. The bars would come
        # from the sealed span and the open-interest column from before it,
        # forward-filled, so a final test would measure the out-of-sample
        # period against a frozen 2024-02-29 reading.
        #
        # Refused rather than wired, because there are three openings for the
        # life of the project and none has been used: the right time to build
        # the sealed positioning path is when a candidate actually needs it,
        # with the numbers in front of whoever is spending the opening.
        raise ValueError(
            "sealed_only with_positioning is not wired: the positioning store "
            "would be read development-only and forward-filled across the "
            "sealed span. Build the sealed path when a final test needs it.")
    if with_positioning:
        # Same rule as funding above, for the same reason: the positioning
        # store starts 2021-12 for most symbols and 2020-09 for BTCUSDT, while
        # the panels start earlier. A bar with no reading is not a bar with
        # zero open interest, and a column of zeros would read to a rule as
        # "every position was closed" -- the loudest possible signal, from
        # absence.
        from orc.facts import positioning

        pos = positioning.load(symbol, development_only=development_only)
        if pos.height == 0:
            raise ValueError(f"{symbol}: positioning is empty in the {state} span")

        first = pos["ts"].min()
        keep = df["ts"] >= first
        if int(df.height - keep.sum()):
            df = df.filter(keep)
            if df.height == 0:
                raise ValueError(
                    f"{symbol}: positioning starts at {first}, after every bar "
                    f"in the {state} span")
            _assert_bar_index_is_a_clock(df, symbol, clock)
            if with_funding and funding_path(symbol).exists():
                fr, settled = funding_rate_per_bar(df["ts"], fund)

        # Open interest is a LEVEL, so each bar takes the last reading inside
        # it -- the same convention as a close. Readings are every five
        # minutes; a bar with none carries the previous level forward rather
        # than a zero, and a leading gap cannot exist because the panel was
        # just truncated to the first reading.
        oi = (df.select("ts")
                .join_asof(pos.select("ts", "open_interest").sort("ts"),
                           on="ts", strategy="backward")["open_interest"]
                .to_numpy().astype(np.float64))
        if not np.all(np.isfinite(oi)):
            raise ValueError(
                f"{symbol}: open interest has gaps the panel cannot carry "
                "forward; the positioning store is incomplete for this span")

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
        funding_settled=settled,
        holdout_state=state,
        # high and low decide every liquidation, stop and take-profit, so a
        # panel that differs only in a wick is different data. Hashing close
        # and funding alone meant a corrected wick left the identity unchanged,
        # the ledger's UNIQUE key matched, and the new liquidation rate was
        # discarded as a duplicate of the old one.
        # The settlement mask is part of the identity: two funding tables
        # can give the same rate array and different settlement counts.
        # Open interest joins the identity for the same reason the wick did:
        # a rule that reads it produces different numbers from one that does
        # not, and two panels that differ only in this column must not collide
        # on the ledger's UNIQUE key.
        panel_hash=_hash_arrays(close, fr, settled.astype(np.float64),
                                df["high"].to_numpy().astype(np.float64),
                                df["low"].to_numpy().astype(np.float64),
                                oi if oi is not None else np.zeros(0)),
        open_interest=oi,
    )


def load_many(symbols: list[str], clock: str = "1h", **kw) -> dict[str, Panel]:
    out: dict[str, Panel] = {}
    for s in symbols:
        try:
            out[s] = load(s, clock, **kw)
        except (FileNotFoundError, ValueError):
            continue
    return out
