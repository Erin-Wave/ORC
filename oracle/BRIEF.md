# Brief for the Track B differential oracle

Write a SECOND, independent implementation of `orc.eval.signal.run_signals`.

It is never merged into the research path. Its only job is to disagree with the
first one, so it must be derived from the SEMANTICS below and not from reading
`orc/eval/signal.py`. If you copy the original's structure you have built
nothing: two implementations that share a mistake catch nothing, and that is
the whole reason a different vendor writes this one.

Write it slowly and obviously. Loop bar by bar. Do not vectorise, do not use
searchsorted, do not optimise. The fast one is already fast; this one is
supposed to be readable enough that its correctness is visible.

## Signature

    ref_run_signals(close, high, low, entry, exit_, spec,
                    funding_rate=None, symbol="", table=None) -> dict

`entry` is an int8 array over bars with values in {LONG=1, SHORT=-1, FLAT=0}.
`exit_` is a bool array over bars.

Return a dict with at least: `equity` (float64 array, one per bar, starting at
spec.capital), `n_trades`, `trades` (list of dicts with entry_bar, exit_bar,
reason, exit_price, funding), `n_liquidations`, `funding_collected`.

## Semantics, in order

1. NO LOOKAHEAD. A signal read at bar i is acted on at bar i+1. Nothing is ever
   filled at a price that was used to decide the fill. A position opened
   because entry[i] != 0 fills at close[i+1].

2. ONE POSITION AT A TIME. While a position is open, `entry` is ignored. A new
   position may only open on a bar after the previous one closed.

3. EXITS, and the tie-break when several fall in the same bar. Priority is
   liquidation < stop < take_profit < signal, LOWER FIRST. An hourly bar cannot
   say which was touched first, so the order is the one that costs the most.

4. ADVERSE FIRST. If a stop and a target both fall inside one bar, the stop is
   taken.

5. LIQUIDATION WINS. If maintenance margin is breached anywhere inside the bar
   -- against `low` for a long, `high` for a short -- the position is gone
   regardless of where the bar closed. Use
   `orc.eval.signal.liquidation_level(side, wallet, qty, entry_price, table)`;
   that helper is shared on purpose, it is not the thing under test.

6. THE EXIT SCAN STARTS AT a+1, NOT a. Bar a's own extremes happened BEFORE the
   fill at close[a], so they cannot trigger an exit on the fill bar.

7. FUNDING IS CHARGED BAR BY BAR, from a+1, on the mark notional. A long pays
   when the rate is positive and a short is paid. Never approximated.

8. COSTS. Buys fill at P*(1+c), sells at P*(1-c), where c is
   (fee_bps + slippage_bps)/1e4. Mark-to-market is always at P.

9. A LIQUIDATED TRADE reports the funding it actually accrued up to the
   liquidation bar, not the funding of the full intended holding period.

10. NO CLAMP AT ZERO. If funding drives the wallet through zero the position is
    liquidated by rule 5; the equity path must not be floored with max(x, 0).

11. max_hold_bars, if set, closes the position that many bars after the fill.

## What to hand back

One Python file. Standard library plus numpy. No imports from orc except
`liquidation_level`, `tier_table_for`, `SignalSpec`, `LONG`, `SHORT`, `FLAT`.
