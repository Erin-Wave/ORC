"""ORC | Signal generators for Track B.

A rule here answers one question: on the evidence available at bar i, should a
position be open, and on which side?  It returns the two arrays the evaluator
consumes and nothing else -- no fills, no accounting, no equity.  Keeping the
rule ignorant of its own results is what stops a signal from quietly reading
its own outcome.

Every generator is causal by construction.  A window ending at bar i uses bars
i-w+1 .. i and the evaluator then fills at i+1, so two separate mechanisms have
to fail before a future price can reach a decision.

  carry_funding   Short while funding has been persistently positive, flat when
                  it decays.  The payer is named and unambiguous: leveraged long
                  demand on a perpetual, which is charged the funding rate every
                  eight hours for as long as it stays crowded.  KT-1 measured
                  that tax from the paying side and closed long DCA over it;
                  this stands on the other side of the same trade.

                  It is not free money and the shape of the loss is known in
                  advance: a short pays for its funding with directional risk,
                  and funding is usually positive precisely when price is
                  rising.  Whether the tax outruns the squeeze is the question.

  cci_reversion   One payer read two ways.  A Binance USD-M position past
  cci_breakout    maintenance margin is closed by the exchange with an
                  immediate-or-cancel order and a clearance fee: it does not
                  choose its price and it cannot wait.  The scouted line for
                  that payer says the move should show "asymmetric continuation
                  and elevated volume, followed by relaxation once the
                  compulsory buy flow is exhausted", and those are two
                  different trades.  Both are written so the pair can disagree
                  -- if both pay, what is being read is not forced flow.

  cci_mtf         The same reading at two resolutions.  The slow candle says
                  which side may be taken, the fast one says when, and the
                  entry is a pullback inside the permitted direction.  It
                  differs from the pair above by having an answer to the
                  question they split on.

CCI is an INDICATOR, and the constitution asks for a payer.  What these three
register is the OBSERVABLE: displacement of price from its own recent mean,
scaled by its own recent dispersion, is the footprint forced liquidation would
leave in bars this archive actually holds.  The liquidation stream itself is
not in it, and ordinary aggressive trading displaces price too, so every result
from these rules is a partial test of that payer and has to be reported as one.
"""
from __future__ import annotations

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from orc.eval.signal import FLAT, LONG, SHORT


def _trailing_sum(x: np.ndarray, window: int) -> np.ndarray:
    """Sum of the last `window` values ending at each bar, NaN until full.

    Prefix sums, so the whole series costs one pass.  The first `window-1` bars
    are NaN rather than a partial sum: a rule that fires on two observations
    because that is all there was is a rule fitted to the start of the archive.
    """
    x = np.asarray(x, dtype=np.float64)
    if window < 1:
        raise ValueError("window must be at least one bar")
    out = np.full(x.size, np.nan)
    if x.size < window:
        return out
    c = np.concatenate(([0.0], np.cumsum(x)))
    out[window - 1:] = c[window:] - c[:-window]
    return out


def _trailing_settlement_mean(funding_rate: np.ndarray, window: int,
                              settled: np.ndarray) -> np.ndarray:
    """Mean rate per settlement over the trailing window.

    `panel.funding_rate` is per bar and zero everywhere except the bars a
    settlement lands on, so dividing the trailing sum by the window length
    would answer a different question -- cost per hour, roughly an eighth of
    the rate people quote -- and every pre-registered threshold would mean
    something other than it says.  Divide by the settlements actually in the
    window instead, so 0.0001 is 0.01% per settlement whatever the clock.

    Which settlements those are has to come from the panel's own mask, not
    from `rate != 0.0`.  A settlement that printed exactly 0.0 is a settlement:
    43.9 percent of BNBUSDT's development-window settlements did, and counting
    only the non-zero ones inflated the reported mean by a median 1.8x and up
    to 45x on that symbol -- so a pre-registered threshold of 0.0001 was being
    compared against a quantity that was not the one it named.  The same line
    failed the other way when a window's settlements were all 0.0: count fell
    to zero, the mean came back NaN, and the rule read that hole as FLAT, a
    decision not to trade.
    """
    rate = np.asarray(funding_rate, dtype=np.float64)
    total = _trailing_sum(rate, window)
    count = _trailing_sum(np.asarray(settled, dtype=np.float64), window)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = np.where(count > 0, total / count, np.nan)
    out[~np.isfinite(total)] = np.nan
    return out


def carry_funding(
    funding_rate: np.ndarray,
    lookback_bars: int,
    enter_rate: float,
    exit_rate: float,
    settled: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Short while the trailing mean funding rate is rich; flat when it is not.

    Two thresholds rather than one, and `enter_rate` must be the higher: a
    single threshold makes the rule flip sides on noise around it, and the
    round trip costs fees every time.  The gap is the rule's own hysteresis and
    is pre-registered like any other parameter.

    Rates are per settlement, not annualised.  Binance settles every eight
    hours, so 0.0001 here is roughly 11% a year paid by the long side.
    """
    if enter_rate < exit_rate:
        raise ValueError("enter_rate must be at or above exit_rate, else the "
                         "rule enters and exits on the same bar")

    if settled is None:
        raise ValueError(
            "carry rules need the panel's settlement mask: a rate of 0.0 is "
            "both 'no settlement' and 'a settlement that cost nothing', and "
            "the two cannot be told apart from the rate array alone")
    mean_rate = _trailing_settlement_mean(funding_rate, lookback_bars, settled)
    rich = mean_rate >= enter_rate
    thin = mean_rate < exit_rate

    entry = np.where(rich, SHORT, FLAT).astype(np.int8)
    # NaN compares false, so the warm-up window is already flat; make the
    # intent explicit rather than relying on that.
    entry[~np.isfinite(mean_rate)] = FLAT
    exit_ = thin & np.isfinite(mean_rate)
    return entry, exit_


def carry_funding_long(
    funding_rate: np.ndarray,
    lookback_bars: int,
    enter_rate: float,
    exit_rate: float,
    settled: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """The mirror: long while funding has been persistently negative.

    Included because the asymmetry between the two sides is itself a result.
    Negative funding means shorts are paying longs, which on these symbols is
    rarer and shallower than the positive case -- if the mirror pays as well as
    the original, the effect is not the funding tax but something else.
    """
    if enter_rate > exit_rate:
        raise ValueError("for the long side enter_rate must be at or below exit_rate")

    if settled is None:
        raise ValueError(
            "carry rules need the panel's settlement mask: a rate of 0.0 is "
            "both 'no settlement' and 'a settlement that cost nothing', and "
            "the two cannot be told apart from the rate array alone")
    mean_rate = _trailing_settlement_mean(funding_rate, lookback_bars, settled)
    entry = np.where(mean_rate <= enter_rate, LONG, FLAT).astype(np.int8)
    entry[~np.isfinite(mean_rate)] = FLAT
    exit_ = (mean_rate > exit_rate) & np.isfinite(mean_rate)
    return entry, exit_


# --------------------------------------------------------------------------
# CCI, and the timeframe it is read on
# --------------------------------------------------------------------------
# Lambert's 0.015 is part of the definition of the indicator, not a choice this
# project gets to make: it is what puts roughly 70-80 % of readings inside
# +-100 on a normal-ish series, which is why the levels quoted everywhere are
# 100 and 200.  It is fixed here so a pre-registered level of 100 means what
# the literature means by it, and it is never put on a grid.
_CCI_K = 0.015

# The sliding window is materialised in row blocks rather than whole.  A 20-day
# period on an hourly panel is 480 bars over ~48,000 of them, and the full
# (48000, 480) view is 184 MB per call -- once per configuration, times a grid,
# times nine symbols.  The mean absolute deviation has no prefix-sum identity
# the way the mean does, so the window has to be materialised; it does not have
# to be materialised all at once.
_WINDOW_ROWS = 4096

# Minutes per bar on each clock the panel builder produces.  A KeyError here is
# the right outcome for a clock nobody has built: the timeframe arithmetic
# below divides by this, and guessing would silently rescale every period.
_BAR_MINUTES = {"1m": 1, "1h": 60}


def _rolling_mean_and_mad(x: np.ndarray, period: int) -> tuple[np.ndarray, np.ndarray]:
    """Window mean and mean ABSOLUTE deviation about that mean, ending at each i.

    Both are NaN until the window is full, for the reason `_trailing_sum` gives:
    a statistic computed on however many observations happened to exist is a
    statistic fitted to the start of the archive.

    The deviation is taken about the window's own mean, not about the series
    mean and not as a standard deviation.  CCI is defined that way, and the
    substitution is not small: a standard deviation runs roughly 1.25x the mean
    absolute deviation on normal data, so every level a hypothesis
    pre-registers would mean about 80 % of what it says.
    """
    x = np.asarray(x, dtype=np.float64)
    n = x.size
    mean = np.full(n, np.nan)
    mad = np.full(n, np.nan)
    if period < 2:
        raise ValueError("a CCI period of one bar has no dispersion to divide by")
    if n < period:
        return mean, mad

    win = sliding_window_view(x, period)
    for s in range(0, win.shape[0], _WINDOW_ROWS):
        w = win[s:s + _WINDOW_ROWS]
        m = w.mean(axis=1)
        d = np.abs(w - m[:, None]).mean(axis=1)
        lo = s + period - 1
        mean[lo:lo + m.size] = m
        mad[lo:lo + d.size] = d
    return mean, mad


def resample_ohlc(ts: np.ndarray, high: np.ndarray, low: np.ndarray,
                  close: np.ndarray, timeframe_hours: float, clock: str):
    """Aggregate the base clock into fixed UTC blocks of `timeframe_hours`.

    Blocks are cut on the epoch, never on the panel's own first bar.  A 4-hour
    block is 00:00-04:00 UTC and is the same block for every symbol and every
    base clock, which is what makes "the 4h candle" a fact about the market
    rather than about where this archive happens to start -- two symbols listed
    a day apart would otherwise be reading different candles under one
    pre-registered parameter.

    Returns the block high, low, close and end timestamp, and `available`: for
    every BASE bar, the index of the last block that had CLOSED by the end of
    that bar, or -1 where none had.  That index is the entire no-lookahead
    argument for a higher timeframe.  A 4-hour candle is not readable at 01:00
    merely because the 01:00 bar sits inside it; it becomes readable at the
    close of the bar that completes it, which on a 1h clock is 03:00 and on a
    1m clock is 03:59.  Comparing a bar's END against the block's end is what
    says so without ever consulting a later bar: a block whose final bars are
    missing from the archive simply never becomes available, which costs
    signals and cannot invent one.
    """
    ms = np.asarray(ts).astype("datetime64[ms]").astype(np.int64)
    if ms.size == 0:
        raise ValueError("cannot resample an empty panel")
    try:
        step_ms = _BAR_MINUTES[clock] * 60_000
    except KeyError:
        raise ValueError(f"unknown clock {clock!r}; known clocks are "
                         f"{sorted(_BAR_MINUTES)}") from None
    tf_ms = int(round(float(timeframe_hours) * 3_600_000))
    if tf_ms < step_ms or tf_ms % step_ms:
        raise ValueError(
            f"timeframe {timeframe_hours}h is not a whole multiple of the "
            f"{clock} bar; a block that does not align to the base clock has "
            "no defined open or close")

    bid = ms // tf_ms
    starts = np.flatnonzero(np.concatenate(([True], np.diff(bid) != 0)))
    ends = np.concatenate((starts[1:], [ms.size]))          # exclusive
    b_high = np.maximum.reduceat(np.asarray(high, dtype=np.float64), starts)
    b_low = np.minimum.reduceat(np.asarray(low, dtype=np.float64), starts)
    b_close = np.asarray(close, dtype=np.float64)[ends - 1]
    b_end_ms = (bid[starts] + 1) * tf_ms

    # Count of blocks whose end is at or before this bar's end, minus one.
    available = np.searchsorted(b_end_ms, ms + step_ms, side="right") - 1
    return b_high, b_low, b_close, b_end_ms, available.astype(np.int64)


def cci(ts: np.ndarray, high: np.ndarray, low: np.ndarray, close: np.ndarray,
        period_bars: int, timeframe_hours: float = 1.0,
        clock: str = "1h") -> np.ndarray:
    """CCI on `timeframe_hours` candles, carried onto every base bar.

        TP  = (H + L + C) / 3
        CCI = (TP - SMA(TP, n)) / (0.015 * MAD(TP, n))

    The value at base bar i is the reading of the last higher-timeframe candle
    that had closed by the end of bar i, and the evaluator fills at i+1, so two
    separate mechanisms stand between a future price and a decision -- the same
    construction the carry rules use.

    NaN, not zero, wherever the reading does not exist: before the first full
    window, before the first completed block, and where the window's mean
    absolute deviation is exactly zero.  That last one is a flat stretch of an
    illiquid symbol, where the division is +-inf and a rule would read the
    largest extreme in its history off a series that did not move.  Zero would
    have read as a perfectly neutral market instead, which is a decision rather
    than the absence of one.
    """
    period_bars = int(period_bars)
    b_high, b_low, b_close, _, available = resample_ohlc(
        ts, high, low, close, timeframe_hours, clock)
    if period_bars < 2:
        raise ValueError(
            f"CCI period rounds to {period_bars} candle(s) on a "
            f"{timeframe_hours}h timeframe; a period below two has no "
            "dispersion to divide by")
    if period_bars > b_close.size:
        raise ValueError(
            f"CCI period of {period_bars} candles exceeds the "
            f"{b_close.size} candles this history holds at {timeframe_hours}h")

    tp = (b_high + b_low + b_close) / 3.0
    mean, mad = _rolling_mean_and_mad(tp, period_bars)
    with np.errstate(invalid="ignore", divide="ignore"):
        block_cci = np.where(mad > 0.0, (tp - mean) / (_CCI_K * mad), np.nan)

    out = np.full(np.asarray(close).size, np.nan)
    seen = available >= 0
    out[seen] = block_cci[available[seen]]
    return out


def _two_sided(value: np.ndarray, enter_level: float, exit_level: float,
               fade: bool) -> tuple[np.ndarray, np.ndarray]:
    """Shared body of the two single-timeframe CCI rules.

    `fade` picks which side of the extreme the position is taken on, and it is
    the only difference between them: the reversion rule buys the low reading
    and the breakout rule buys the high one.  They are written as one function
    because the pair is only informative if nothing else differs -- if the two
    disagree, the disagreement is about the direction of the flow being read,
    not about a threshold, a warm-up or an exit that drifted apart.

    A position is closed when the reading comes back inside `exit_level`, and
    the band is symmetric, so the rule cannot flip from long to short in one
    bar: it has to pass through the middle first.  That is a property of the
    shape, pre-registered here rather than discovered later -- a breakout long
    riding a reversal down to the opposite extreme is held until the reading
    crosses the band on its way there, or until the stop, the maximum hold or
    the liquidation ends it.
    """
    if not enter_level > exit_level >= 0.0:
        raise ValueError(
            f"need enter_level ({enter_level}) > exit_level ({exit_level}) >= 0; "
            "otherwise the entry and exit conditions overlap and the rule "
            "closes the position it has just opened")
    value = np.asarray(value, dtype=np.float64)
    finite = np.isfinite(value)
    hot = finite & (value >= enter_level)
    cold = finite & (value <= -enter_level)

    entry = np.full(value.size, FLAT, dtype=np.int8)
    entry[hot] = SHORT if fade else LONG
    entry[cold] = LONG if fade else SHORT

    # A reading that does not exist is not a decision to hold.  The carry rules
    # treat NaN as "stay flat" because their NaN is a warm-up window; this NaN
    # can also be a symbol that has stopped moving, and holding a position on
    # an indicator that cannot be computed is the one thing the rule must not
    # do silently.
    exit_ = (~finite) | (np.abs(value) <= exit_level)
    return entry, exit_


def cci_reversion(value: np.ndarray, enter_level: float,
                  exit_level: float) -> tuple[np.ndarray, np.ndarray]:
    """Buy the oversold reading, sell the overbought one, close in the middle.

    The payer is the forced participant.  A Binance USD-M position that
    breaches maintenance margin is closed by the exchange with an
    immediate-or-cancel order and a clearance fee, and a stop cluster does the
    same thing voluntarily; neither is choosing a price and both must transact
    now.  What is collected on the other side is compensation for immediacy,
    and the scout notebook's own line for this payer ends the sentence: the
    move relaxes "once the compulsory buy flow is exhausted".  This rule is a
    bet on the relaxation.

    It is a PARTIAL test of that payer and says so.  The liquidation stream
    itself is not in this archive, so a displaced price is read as evidence of
    forced flow rather than measured as it, and ordinary aggressive trading
    displaces price too.
    """
    return _two_sided(value, enter_level, exit_level, fade=True)


def cci_breakout(value: np.ndarray, enter_level: float,
                 exit_level: float) -> tuple[np.ndarray, np.ndarray]:
    """The other half of the same sentence: ride the flow while it is still forced.

    Same payer, opposite reading of them.  A liquidated short must BUY, at
    market, into a market that is already rising, and that flow is
    one-directional by construction and arrives after the move has begun.  If
    the cascade is what displaces price, continuation is paid before relaxation
    is.

    The pair is the point.  Reversion and breakout cannot both be right about
    the same payer at the same horizon, so the two together are a test that
    either shape alone cannot be: if both pay, what is being read is not forced
    flow.
    """
    return _two_sided(value, enter_level, exit_level, fade=False)


def cci_mtf(base: np.ndarray, filt: np.ndarray, enter_level: float,
            exit_level: float, filter_level: float) -> tuple[np.ndarray, np.ndarray]:
    """Slow timeframe says which side is allowed; fast timeframe says when.

    The cascade the two rules above disagree about has a direction, and that
    direction is not visible at the resolution the entry is taken on.  So the
    higher timeframe is used for one thing only -- which side may be taken --
    and the lower one for the trigger, entering on a pullback AGAINST the
    permitted side.  That is the trade the reversion rule takes, with the
    slower reading standing in for the question it cannot answer alone: is this
    an exhausted cascade or the beginning of one.

    `filter_level` must be positive.  At zero every bar permits a side, the
    filter stops filtering, and the exit clause below degenerates into the
    reversion rule's exit -- so the whole shape would quietly collapse into the
    one it exists to be distinguished from.
    """
    if filter_level <= 0.0:
        raise ValueError(
            "filter_level must be positive; at zero the higher timeframe "
            "permits both sides on every bar and this is no longer a filtered "
            "rule")
    if enter_level <= 0.0:
        raise ValueError("enter_level must be positive")
    if exit_level < 0.0:
        raise ValueError("exit_level must not be negative")

    base = np.asarray(base, dtype=np.float64)
    filt = np.asarray(filt, dtype=np.float64)
    ok = np.isfinite(base) & np.isfinite(filt)
    up = ok & (filt >= filter_level)
    down = ok & (filt <= -filter_level)

    entry = np.full(base.size, FLAT, dtype=np.int8)
    entry[up & (base <= -enter_level)] = LONG
    entry[down & (base >= enter_level)] = SHORT

    # Two ways out, and both are stateless on purpose.  The side taken is the
    # sign of the filter at the entry bar, so `sign(filter) * base` is the
    # reading measured along the direction of the trade, and the clause says
    # the pullback has resolved in the permitted direction.  The other way out
    # is the regime itself ending, and because the filter has to pass through
    # the band to change sign, a flip is always caught by that clause before
    # the signed one can be read against the wrong side.
    trend_gone = (~ok) | (np.abs(filt) < filter_level)
    resolved = ok & (np.sign(filt) * base >= exit_level)
    return entry, trend_gone | resolved


# --------------------------------------------------------------------------
# Dispatch
# --------------------------------------------------------------------------
def _period_bars(lookback_days: float, timeframe_hours: float) -> int:
    """The CCI period, in candles of the timeframe it is read on.

    Every parameter in this project is a duration, so that one number means the
    same thing on every clock -- `panel.bars(days)` is the same idea.  A period
    expressed in candles would mean 20 hours on one timeframe and 80 on
    another under a single registered value, and the 4h-against-1h comparison
    this family exists to make would be comparing two windows as well as two
    resolutions.
    """
    return int(round(float(lookback_days) * 24.0 / float(timeframe_hours)))


def _build_carry(fn):
    def build(cfg, panel, price=None):
        # `price` is ignored, and that is the shape of the null test rather
        # than an oversight: a carry rule reads the funding series, which the
        # bootstrap does not resample, so its signals are the same on every
        # synthetic path.  A price rule's are not, which is the whole reason
        # the override exists.
        return fn(panel.funding_rate, panel.bars(cfg.lookback_days),
                  cfg.enter_rate, cfg.exit_rate, panel.funding_settled)
    return build


def _cci_of(panel, timeframe_hours: float, lookback_days: float,
            price: tuple | None = None) -> np.ndarray:
    high, low, close = price if price is not None else (panel.high, panel.low,
                                                        panel.close)
    return cci(panel.ts, high, low, close,
               _period_bars(lookback_days, timeframe_hours),
               timeframe_hours, panel.clock)


def _build_cci(fn):
    def build(cfg, panel, price=None):
        value = _cci_of(panel, cfg.timeframe_hours, cfg.lookback_days, price)
        return fn(value, cfg.enter_level, cfg.exit_level)
    return build


def _build_cci_mtf(cfg, panel, price=None):
    if cfg.filter_timeframe_hours is None:
        raise ValueError("cci_mtf needs filter_timeframe_hours; without a "
                         "second timeframe it is not a multi-timeframe rule")
    if cfg.filter_timeframe_hours <= cfg.timeframe_hours:
        raise ValueError(
            f"filter_timeframe_hours ({cfg.filter_timeframe_hours}) must be "
            f"above timeframe_hours ({cfg.timeframe_hours}); the filter is the "
            "SLOWER of the two and the shape means nothing reversed")
    base = _cci_of(panel, cfg.timeframe_hours, cfg.lookback_days, price)
    filt = _cci_of(panel, cfg.filter_timeframe_hours,
                   cfg.filter_lookback_days
                   if cfg.filter_lookback_days is not None else cfg.lookback_days,
                   price)
    return cci_mtf(base, filt, cfg.enter_level, cfg.exit_level, cfg.filter_level)


# name -> builder(cfg, panel) -> (entry, exit_).  The builders take the whole
# configuration rather than a hand-picked handful of its fields, and that is
# not tidiness: `build_signals` had five call sites, each passing
# (rule, panel, lookback, enter_rate, exit_rate) by hand, so a rule reading a
# NEW field would have been given the default by four of them while the fifth
# honoured the grid.  The failure mode is a robustness check or an
# execution-realism run reporting a number for a configuration it never
# evaluated.
RULES = {
    "carry_funding": _build_carry(carry_funding),
    "carry_funding_long": _build_carry(carry_funding_long),
    "cci_reversion": _build_cci(cci_reversion),
    "cci_breakout": _build_cci(cci_breakout),
    "cci_mtf": _build_cci_mtf,
}

# Which rules read the funding series rather than price.  The runner refuses a
# symbol with no funding history for these outright; a price rule still PAYS
# funding bar by bar inside the evaluator, so it wants the history too, but for
# a different reason and with a different message.
FUNDING_RULES = ("carry_funding", "carry_funding_long")


def build_signals(cfg, panel, close: np.ndarray | None = None,
                  high: np.ndarray | None = None,
                  low: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Dispatch to a named rule, reading everything it needs off the config.

    `close` overrides the panel's own prices, and the search test is what needs
    it: its null re-runs the SAME rule on a bootstrapped history, and a price
    rule handed the real panel would have produced the real signals on a
    synthetic path -- a null for a strategy nobody ran.  Track A carries the
    identical override on `build_gate` for the identical reason, and the note
    at `runner.tm_q05_on_path` is the worked example of what it costs when the
    null quietly evaluates a different shape.  `high` and `low` default to
    `close`: a bootstrap has no wick.
    """
    try:
        fn = RULES[cfg.rule]
    except KeyError:
        raise ValueError(f"unknown signal rule {cfg.rule!r}; "
                         f"known rules are {sorted(RULES)}") from None
    price = None
    if close is not None:
        close = np.asarray(close, dtype=np.float64)
        price = (close if high is None else np.asarray(high, dtype=np.float64),
                 close if low is None else np.asarray(low, dtype=np.float64),
                 close)
    return fn(cfg, panel, price)
