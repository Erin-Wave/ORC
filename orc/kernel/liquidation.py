"""ORC | Binance USDs-M liquidation.

The single highest correctness risk in leveraged DCA research: an averaging-down
position looks wonderful right up to the bar where it is liquidated.  If this
module is wrong, every leveraged result in the project is fiction.

Model (isolated margin, one-way long, matching Binance USDs-M):

    margin_balance      = isolated_wallet + Q * (mark - entry_price)
    notional            = Q * mark
    maintenance_margin  = notional * MMR(notional) - cum_maint_amount(notional)
    LIQUIDATED          when margin_balance <= maintenance_margin

Liquidation is evaluated against the *worst mark price inside the bar* (the low,
for a long), never the close.  Anything else hides intrabar wipeouts.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Tier:
    notional_cap: float      # upper bound of the bracket, in USDT
    mmr: float               # maintenance margin rate
    cum_maint: float         # cumulative maintenance amount
    max_leverage: float


@dataclass(frozen=True)
class TierTable:
    name: str
    tiers: tuple[Tier, ...]

    def lookup(self, notional: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Vectorised bracket lookup -> (mmr, cum_maint) arrays."""
        caps = np.array([t.notional_cap for t in self.tiers])
        mmrs = np.array([t.mmr for t in self.tiers])
        cums = np.array([t.cum_maint for t in self.tiers])
        idx = np.searchsorted(caps, np.abs(notional), side="left")
        idx = np.clip(idx, 0, len(caps) - 1)
        return mmrs[idx], cums[idx]

    @property
    def max_leverage(self) -> float:
        return self.tiers[0].max_leverage


# Published BTCUSDT brackets.  Retail DCA at a few thousand USDT never leaves
# the first bracket, but the table is implemented in full so that capacity
# studies cannot silently use the wrong rate.
BTC_LIKE = TierTable("BTC_LIKE", (
    Tier(50_000,       0.0040,        0.0, 125),
    Tier(600_000,      0.0050,       50.0, 100),
    Tier(3_000_000,    0.0100,     3_050.0, 50),
    Tier(12_000_000,   0.0250,    48_050.0, 20),
    Tier(70_000_000,   0.0500,   348_050.0, 10),
    Tier(100_000_000,  0.1000, 3_848_050.0,  5),
    Tier(230_000_000,  0.1250, 6_348_050.0,  4),
    Tier(480_000_000,  0.1500,11_098_050.0,  3),
    Tier(600_000_000,  0.2500,59_098_050.0,  2),
    Tier(800_000_000,  0.5000,209_098_050.0, 1),
))

# Conservative profile for large alts (ETH/BNB/SOL class).
MAJOR_ALT = TierTable("MAJOR_ALT", (
    Tier(10_000,       0.0065,        0.0, 75),
    Tier(100_000,      0.0100,       35.0, 50),
    Tier(500_000,      0.0200,    1_035.0, 25),
    Tier(2_000_000,    0.0500,   16_035.0, 10),
    Tier(10_000_000,   0.1000,  116_035.0,  5),
    Tier(30_000_000,   0.1250,  366_035.0,  4),
))

# Everything else.  Deliberately the harshest of the three: an unknown symbol
# must never be modelled as easier to hold than it really is.
LONG_TAIL = TierTable("LONG_TAIL", (
    Tier(5_000,        0.0100,        0.0, 25),
    Tier(50_000,       0.0250,       75.0, 20),
    Tier(250_000,      0.0500,    1_325.0, 10),
    Tier(1_000_000,    0.1000,   13_825.0,  5),
    Tier(5_000_000,    0.1250,   38_825.0,  4),
))

_MAJORS = {"ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT",
           "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "LTCUSDT", "BCHUSDT"}


def tier_table_for(symbol: str) -> TierTable:
    """Pick a bracket table.  Unknown symbols get the harshest table."""
    if symbol in {"BTCUSDT", "BTCUSDC", "BTCBUSD"}:
        return BTC_LIKE
    if symbol in _MAJORS:
        return MAJOR_ALT
    return LONG_TAIL


def maintenance_margin(notional: np.ndarray, table: TierTable) -> np.ndarray:
    mmr, cum = table.lookup(notional)
    return np.abs(notional) * mmr - cum


def is_liquidated(
    wallet: np.ndarray,
    qty: np.ndarray,
    entry_price: np.ndarray,
    worst_mark: np.ndarray,
    table: TierTable,
) -> np.ndarray:
    """Elementwise liquidation test for a LONG position at the bar's worst mark.

    All arguments broadcast, so an entire ensemble of start dates is tested in
    one call.
    """
    notional = qty * worst_mark
    margin_balance = wallet + qty * (worst_mark - entry_price)
    return margin_balance <= maintenance_margin(notional, table)


def liquidation_price_long(
    wallet: float | np.ndarray,
    qty: float | np.ndarray,
    entry_price: float | np.ndarray,
    table: TierTable,
) -> np.ndarray:
    """Closed-form long liquidation price, for reporting and cross-checks.

        WB + Q*(P - EP) = Q*P*MMR - cumB
    =>  P = (Q*EP - WB - cumB) / (Q*(1 - MMR))

    The bracket is resolved iteratively because MMR depends on the notional at
    the liquidation price, which depends on MMR.
    """
    qty = np.asarray(qty, dtype=np.float64)
    wallet = np.asarray(wallet, dtype=np.float64)
    entry_price = np.asarray(entry_price, dtype=np.float64)

    price = np.asarray(entry_price, dtype=np.float64).copy()
    for _ in range(8):                       # converges in 2-3 for real inputs
        mmr, cum = table.lookup(qty * price)
        denom = qty * (1.0 - mmr)
        nxt = np.where(denom > 0, (qty * entry_price - wallet - cum) / denom, 0.0)
        nxt = np.maximum(nxt, 0.0)
        if np.allclose(nxt, price, rtol=1e-12, atol=1e-12):
            price = nxt
            break
        price = nxt
    return price
