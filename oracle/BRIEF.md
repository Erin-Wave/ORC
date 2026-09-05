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

`reason` is exactly one of: `liquidation`, `stop`, `take_profit`, `max_hold`,
`signal`. A position still open on the last bar is closed at that bar's close
and ALSO reported as `signal` -- there is no separate `end` label. The
implementation under test has no such label and inventing one makes the two
disagree about a word rather than about a number.

## Semantics, in order

1. NO LOOKAHEAD, AND THE LAST BAR HAS NO i+1. A signal read at bar i is acted
   on at bar i+1. Nothing is ever filled at a price that was used to decide the
   fill. A position opened because entry[i] != 0 fills at close[i+1].

   So entry[n-1] -- the signal on the FINAL bar -- opens nothing. There is no
   bar to fill it at. A trade whose entry_bar equals its exit_bar is proof this
   rule was broken: it was filled and closed on the same bar, which means it
   was filled at a price that decided the fill.

   The first version of this brief left it implicit and the reference produced
   exactly that trade -- (83, 83) on an 84-bar panel, identical to the
   implementation on all thirteen trades before it.

2. ONE POSITION AT A TIME, AND RULE 1 STILL APPLIES TO THE RE-ENTRY. While a
   position is open, `entry` is ignored -- including on the bar it closes.

   Concretely, because rules 1 and 2 overlap here and the first version of this
   brief did not say how. A position that CLOSES on bar X was still open during
   X, so entry[X] is ignored. The first signal that can be acted on is
   entry[X+1], and by rule 1 it fills at X+2.

       exit at bar 5  ->  next entry signal read at 6, FILLED AT 7
       not filled at 6

   The implementation under test skips the bar; the reference did not, and that
   one bar was the source of every remaining disagreement between them after
   the liquidation and cost rules were pinned down. It is the conservative
   reading: a fill on the closing bar would be acting on a signal that was
   visible while the position that blocked it was still open.

3. EXITS, and the tie-break when several fall in the same bar. Priority is
   liquidation < stop < take_profit < signal, LOWER FIRST. An hourly bar cannot
   say which was touched first, so the order is the one that costs the most.

4. ADVERSE FIRST. If a stop and a target both fall inside one bar, the stop is
   taken.

5. LIQUIDATION WINS, AND IT LEAVES ZERO. If maintenance margin is breached
   anywhere inside the bar -- against `low` for a long, `high` for a short --
   the position is gone regardless of where the bar closed AND the account is
   at zero. Not the residue above the bankruptcy price. Equity is 0.0 from that
   bar onward and no further position is opened, because there is nothing to
   open one with.

   This sentence was missing in the first version of this brief and it was the
   single source of every numeric disagreement between the two implementations.
   Decided in favour of zero: a Binance USD-M liquidation is an IOC order plus
   a clearance fee and takes the position margin, the residue assumes a fill at
   exactly the maintenance-margin price, and KT-2 reads a liquidation as ruin.

   Use
   `orc.eval.signal.liquidation_level(side, wallet, qty, entry_price, table)`;
   that helper is shared on purpose, it is not the thing under test.

6. THE EXIT SCAN STARTS AT a+1, NOT a. Bar a's own extremes happened BEFORE the
   fill at close[a], so they cannot trigger an exit on the fill bar.

7. FUNDING IS CHARGED BAR BY BAR, from a+1, on the mark notional. A long pays
   when the rate is positive and a short is paid. Never approximated.

   AND IT SETTLES AFTER THE LIQUIDATION CHECK, NOT BEFORE. Within one bar the
   order is: check liquidation against the account as it stood ENTERING the
   bar, then settle that bar's funding. Margin that arrives later in time must
   not rescue a position from a high or a low that had already printed.

   This bites hardest on a short receiving funding: crediting it first grows
   the wallet, lifts the liquidation level, and the position survives a bar it
   was already gone on. The first version of this brief did not say which came
   first, and on one case in three thousand -- a short at 5x through a +1.33%
   settlement -- the reference survived to bar 80 where the implementation was
   liquidated at 77. Same class as a defect already on record for the Track A
   simulator, where a scheduled deposit applied before the liquidation check
   made every deposit bar err towards survival.

8. COSTS, AND THE COST IS IN THE FILL PRICE, NOT A SEPARATE DEDUCTION.
   c = (fee_bps + slippage_bps)/1e4. A buy fills at P*(1+c) and a sell at
   P*(1-c); mark-to-market is always at P.

   Concretely, and this is the sentence the first version was missing: the
   QUANTITY comes from the fill price.

       qty = (capital * leverage) / (P * (1 + c))       for a long

   NOT `qty = capital*leverage/P` with `capital*leverage*c` subtracted from the
   wallet afterwards. The two differ at second order in c and the difference is
   real: 1000 capital at 5x with 1bp slippage gives 999.500050 the first way
   and 999.500000 the second. The first version of this brief said only "buys
   fill at P*(1+c)" and the reference read it the other way, which is how this
   paragraph came to exist.

9. A LIQUIDATED TRADE reports the funding it ACTUALLY ACCRUED up to the
   liquidation bar -- and that is not zero.

   Concretely, because the first version of this brief said only "not the
   funding of the full intended holding period" and the reference read that as
   "report nothing". A position opened at bar a and liquidated at bar L was
   charged or paid funding on every bar from a+1 to L, and `trade["funding"]`
   is that sum. Whatever the liquidation then destroys is a PRICE loss and
   belongs on the price leg, not on the coupon.

   The two must reconcile: `funding_collected` is the sum of every trade's
   `funding`, liquidated ones included. A short liquidated after collecting 45
   reports 45, not 0 -- reporting 0 makes the coupon and the price leg
   disagree about where the money went, and this project has a finding on
   record for exactly that (6641f54ee642).

   Note the shape of the disagreement this produced: equity agreed to 1.07e-15
   across the whole panel and only the REPORTED total differed. A number that
   is right in the account and wrong in the report is still wrong -- it is a
   recorded metric.

10. NO CLAMP AT ZERO. If funding drives the wallet through zero the position is
    liquidated by rule 5; the equity path must not be floored with max(x, 0).

11. max_hold_bars, if set, closes the position that many bars after the fill.

## When a gap is found, ask for an EDIT, not a rewrite

Each round of this brief was handed to the provider fresh and it wrote the
whole file again. Six rounds went 400 clean, then a REGRESSION -- the
intra-bar-ordering round broke a stop that five rounds had got right. A full
rewrite per fix means every fix carries a new implementation with new variance,
and the oracle then reports disagreements about the newest rewrite instead of
about the specification.

So after the first version exists, fix it by handing the provider ITS OWN
previous file and asking for the smallest edit. That keeps the vendor split
intact -- what must never be shown is `orc/eval/signal.py`, not the provider's
own output -- and it removes the variance.

The reference is still never edited by hand. A human patch would make it the
same author as the implementation and the whole device would be checking itself.

## What to hand back

One Python file. Standard library plus numpy. No imports from orc except
`liquidation_level`, `tier_table_for`, `SignalSpec`, `LONG`, `SHORT`, `FLAT`.
