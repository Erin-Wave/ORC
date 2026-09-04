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
# When this project is finished
# --------------------------------------------------------------------------
# The owner's stop condition, set on 2026-09-04: research ends when a rule that
# has survived verification several times over -- the list is in orc/target.py,
# not a feeling -- reaches a CAGR of 100 % at a maximum drawdown of 25 % or
# less.  Both halves or neither: a CAGR without its drawdown is exactly the
# number this project exists not to be fooled by.
#
# Frozen with the measurement that proves it was frozen early.  On the day it
# was written the ledger held 6,848 trials, 5,292 of them Track B, and NOT ONE
# met it.  The best CAGR ever recorded was 0.9339 at a drawdown of 0.6667
# (H0006 SOLUSDT, in a family that is already closed); the best Calmar was
# 1.4007; and among the 65 rows that did hold drawdown at or under 25 %, the
# best CAGR was 0.2764.  The pair implies a Calmar of at least 4.0, which is
# 2.9x the largest this project has ever produced.
#
# It is a STOP condition and not a threshold any result is judged against.
# Nothing here changes how a cell is measured, what disqualifies it, or what
# gets published: a family that fails still publishes its failure, and a map of
# where rules break is still the deliverable.  What this decides is only when
# the loop has no further question worth asking.
TARGET_CAGR = 1.00
TARGET_MAX_DRAWDOWN = 0.25

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

# A mechanism nobody has tested gets a PROBE, not an enumeration.
#
# The ledger says why. 73.4 % of N -- 4,860 of 6,624 rows -- went to H0002,
# which registered 972 cells on the first and only test its mechanism ever got
# and is now closed. The two narrow families that came after it, H0006 at 72
# cells and H0007 at 54, cost 11.4 % of N between them and answered their
# questions just as well: H0006's own pre-registration says a failing mirror
# closes the funding question on both sides, and 72 cells are enough to say so.
#
# So width is not what buys an answer, and spending it before the mechanism has
# survived anything is how one guess ends up owning the multiple-testing
# denominator for the life of the project. A family with no rows in the ledger
# is capped here. Once it has been probed and not closed, a second registration
# under a NEW id may go as wide as the ceiling above -- which is depth earned by
# a result rather than assumed before one.
#
# Chosen AFTER seeing results, deliberately, and it is not a threshold any
# result is judged against: it constrains what may be asked, never what counts
# as an answer, so no finding can be biased by it. It is set where it separates
# what H0002 should have been from what H0006 and H0007 already were.
MAX_PROBE_CONFIGURATIONS = 96

# How many hypotheses may be REGISTERED in any rolling 24 hours.
#
# The loop now runs continuously rather than firing once a day, and that change
# is only safe because of this line.  Proposing costs nothing that cannot be
# undone: a killed proposal leaves a file in configs/killed/ and zero rows in
# the ledger, and both adversaries killed both proposals on 2026-09-03.  So a
# machine that proposes around the clock is spending compute, which is free
# here, on the step whose whole job is to widen the search.
#
# REGISTRATION is the irreversible half.  It hashes a claim and a grid, and
# every cell it enumerates enters the append-only ledger and raises the
# multiple-testing bar for every result this project will ever produce.  With
# the queue-empty rule alone, the registration rate would be bounded only by
# how fast the worker can clear a queue -- roughly one cycle every 35 minutes,
# so about thirty a day, which would put more rows into N in one week than the
# project has accumulated in its life.
#
# Four, which is four times the rate the once-a-day schedule actually achieved
# and bounded at 4 x 96 = 384 cells a day against a current N of 6,736.  Chosen
# so that a day of continuous running cannot move N by more than a few per
# cent, and deliberately not derived from any result: like the probe ceiling it
# constrains what may be ASKED and never what counts as an answer, so no
# finding can be biased by it.  Frozen 2026-09-03, before the continuous loop
# ran once.
MAX_REGISTRATIONS_PER_DAY = 4

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
