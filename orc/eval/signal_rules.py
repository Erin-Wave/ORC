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
"""
from __future__ import annotations

import numpy as np

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


def _trailing_settlement_mean(funding_rate: np.ndarray, window: int) -> np.ndarray:
    """Mean rate per settlement over the trailing window.

    `panel.funding_rate` is per bar and zero everywhere except the bars a
    settlement lands on, so dividing the trailing sum by the window length
    would answer a different question -- cost per hour, roughly an eighth of
    the rate people quote -- and every pre-registered threshold would mean
    something other than it says.  Divide by the settlements actually in the
    window instead, so 0.0001 is 0.01% per settlement whatever the clock.
    """
    rate = np.asarray(funding_rate, dtype=np.float64)
    total = _trailing_sum(rate, window)
    count = _trailing_sum((rate != 0.0).astype(np.float64), window)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = np.where(count > 0, total / count, np.nan)
    out[~np.isfinite(total)] = np.nan
    return out


def carry_funding(
    funding_rate: np.ndarray,
    lookback_bars: int,
    enter_rate: float,
    exit_rate: float,
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

    mean_rate = _trailing_settlement_mean(funding_rate, lookback_bars)
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
) -> tuple[np.ndarray, np.ndarray]:
    """The mirror: long while funding has been persistently negative.

    Included because the asymmetry between the two sides is itself a result.
    Negative funding means shorts are paying longs, which on these symbols is
    rarer and shallower than the positive case -- if the mirror pays as well as
    the original, the effect is not the funding tax but something else.
    """
    if enter_rate > exit_rate:
        raise ValueError("for the long side enter_rate must be at or below exit_rate")

    mean_rate = _trailing_settlement_mean(funding_rate, lookback_bars)
    entry = np.where(mean_rate <= enter_rate, LONG, FLAT).astype(np.int8)
    entry[~np.isfinite(mean_rate)] = FLAT
    exit_ = (mean_rate > exit_rate) & np.isfinite(mean_rate)
    return entry, exit_


RULES = {
    "carry_funding": carry_funding,
    "carry_funding_long": carry_funding_long,
}


def build_signals(rule: str, panel, lookback_bars: int,
                  enter_rate: float, exit_rate: float) -> tuple[np.ndarray, np.ndarray]:
    """Dispatch to a named rule using the panel's own funding series."""
    try:
        fn = RULES[rule]
    except KeyError:
        raise ValueError(f"unknown signal rule {rule!r}; "
                         f"known rules are {sorted(RULES)}") from None
    return fn(panel.funding_rate, lookback_bars, enter_rate, exit_rate)
