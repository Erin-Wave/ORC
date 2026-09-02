"""ORC | Paths, constants and the research cutoff.

Everything that is a *choice* lives here so that a config hash pins a run.
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

# --------------------------------------------------------------------------
# Roots
# --------------------------------------------------------------------------
ORC_ROOT = Path(__file__).resolve().parent.parent
FACTS = Path(os.environ.get("ORC_FACTS", ORC_ROOT / "facts"))
REPORTS = ORC_ROOT / "reports"
CONFIGS = ORC_ROOT / "configs"
QUEUE = CONFIGS / "queue"
REGISTRY = CONFIGS / "registry"
LEDGER_DB = Path(os.environ.get("ORC_LEDGER", ORC_ROOT / "ledger" / "trials.sqlite"))

# Raw vendor archive on this machine. Read-only; ORC never writes here.
RAW_1M = Path(os.environ.get("ORC_RAW_1M", r"D:/Assets/BinanceFuturesData/1m"))

# --------------------------------------------------------------------------
# The sealed holdout.  Enforced by orc.holdout, not by good intentions.
# --------------------------------------------------------------------------
# Everything strictly before this date is DEVELOPMENT data.
# Everything on/after is SEALED and is physically absent from the worker panel.
HOLDOUT_START = date(2024, 3, 1)

# The archive stops here (last 1m file present locally).
DATA_END = date(2025, 7, 23)

# --------------------------------------------------------------------------
# Market microstructure defaults (Binance USDs-M perpetuals)
# --------------------------------------------------------------------------
TAKER_FEE_BPS = 4.5      # 0.045 % taker, no BNB discount, no VIP tier
MAKER_FEE_BPS = 1.8      # 0.018 % maker
SLIPPAGE_BPS = 1.0       # conservative default for retail-size clips
FUNDING_HOURS = (0, 8, 16)   # UTC settlement hours

# Cost-stress multipliers a candidate must survive (protocol, not a knob).
COST_STRESS_MULTIPLIERS = (1.0, 2.0, 3.0)

# --------------------------------------------------------------------------
# What one hypothesis is allowed to cost
# --------------------------------------------------------------------------
# Every configuration a registered hypothesis enumerates enters the append-only
# ledger, and that count is the denominator of the multiple-testing correction
# applied to every result this project will ever produce.  It cannot be reduced
# afterwards.  The only thing standing between a proposer and an arbitrarily
# large N was a sentence in a prompt asking it to be reasonable, which is not a
# constraint.  Frozen at roughly twice the largest grid registered before any
# family cleared (H0002 at 972), so it binds what is proposed next without
# retroactively rejecting anything the ledger already holds.
MAX_CONFIGURATIONS_PER_HYPOTHESIS = 2000

# --------------------------------------------------------------------------
# Panel build
# --------------------------------------------------------------------------
# Bars whose entire OHLC is flat AND volume == 0 are pre-listing padding in the
# vendor archive (verified on BTCUSDT 2019-09-08).  They are removed, never
# forward-filled.
DROP_ZERO_VOLUME_FLAT = True

# The simulation clock.  Path-dependent variants run on this; liquidation
# extremes are carried down from the 1m bars so nothing is hidden inside a bar.
SIM_CLOCK_MINUTES = 60

MIN_BARS_REQUIRED = 60 * 24 * 90     # a symbol needs >= 90 days to be usable


def ensure_dirs() -> None:
    for p in (FACTS, REPORTS, QUEUE, REGISTRY, LEDGER_DB.parent):
        p.mkdir(parents=True, exist_ok=True)
