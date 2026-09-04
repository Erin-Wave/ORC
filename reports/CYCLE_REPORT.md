# ORC cycle report

- run `f83b0eaf389a` finished 2026-09-04T23:18:41.193619+00:00
- trials in project: **7122** (+112 this cycle)
- holdout sealed from **2024-03-01**, final tests used 0/3
- primary metric per track: `tm_q05` for accumulation (5th-percentile terminal multiple across start dates), `calmar` for signal positions (return over deepest drawdown)

Every number below is development data only. The ranking is not a result; the shape column and PBO are what decide whether it means anything.

## Headline

Best cell per family per symbol, ranked on the metric that survives a horizon change. `return p.a.` is the annualised money-weighted return at the 5th percentile of start dates on track A, and the CAGR of the single equity curve on track B. `max drawdown` is drawdown on invested capital on track A -- peak-to-trough of profit over contributed capital, so it can exceed 100% -- and conventional equity drawdown on track B. The two are not comparable and are labelled.

| family | symbol | return p.a. | max drawdown | basis | not a finding because |
|---|---|---:|---:|---|---|
| H0001 | ETHUSDT | +67.9% | 481.5% | invested | spike, 1.02 paths, PBO unmeasured, p=0.725 vs a random search |
| H0001 | SOLUSDT | +37.3% | 849.7% | invested | spike, 1.16 paths, PBO unmeasured, p=0.790 vs a random search |
| H0001 | BTCUSDT | +36.2% | 193.4% | invested | spike, 1.07 paths, PBO unmeasured, search test unmeasured |
| H0001 | BNBUSDT | +8.1% | 271.9% | invested | spike, 1.36 paths, PBO unmeasured, search test unmeasured |
| H0001 | XRPUSDT | -5.3% | 139.1% | invested | at or below 0, shape unmeasured, 1.4 paths, PBO unmeasured, search test unmeasured |
| H0001 | DOGEUSDT | -9.9% | 1344.9% | invested | at or below 0, shape unmeasured, 1.23 paths, PBO unmeasured, search test unmeasured |
| H0001 | LTCUSDT | -23.7% | 130.6% | invested | at or below 0, shape unmeasured, 1.39 paths, PBO unmeasured, search test unmeasured |
| H0001 | AVAXUSDT | -29.9% | 311.0% | invested | at or below 0, shape unmeasured, 1.16 paths, PBO unmeasured, search test unmeasured |
| H0001 | ADAUSDT | -32.0% | 418.8% | invested | at or below 0, shape unmeasured, 1.37 paths, PBO unmeasured, search test unmeasured |
| H0019 | AVAXUSDT | +38.8% | 24.6% | equity | spike, p=0.050 vs a random search |
| H0019 | ADAUSDT | +16.5% | 46.3% | equity | spike, search test unmeasured |
| H0019 | XRPUSDT | +13.5% | 38.6% | equity | spike, PBO unmeasured, search test unmeasured |
| H0019 | ETHUSDT | +9.1% | 21.8% | equity | spike, PBO 0.60, p=0.275 vs a random search |
| H0019 | SOLUSDT | +8.6% | 29.1% | equity | spike, PBO unmeasured, search test unmeasured |
| H0019 | DOGEUSDT | +3.3% | 32.5% | equity | spike, PBO unmeasured, search test unmeasured |
| H0019 | BNBUSDT | +3.3% | 12.7% | equity | spike, PBO unmeasured, search test unmeasured |
| H0019 | LTCUSDT | +1.9% | 8.2% | equity | spike, PBO unmeasured, search test unmeasured |
| H0019 | BTCUSDT | -2.8% | 26.9% | equity | at or below 0, shape unmeasured, PBO unmeasured, search test unmeasured |

No cell clears every check. Nothing in this table is a result.

## Closed families -- answered, do not re-propose

These are not gaps in the map. Each was closed against its own pre-registered kill condition and its grid is no longer enumerated. The reason is the finding.

| family | closed because | post-mortem |
|---|---|---|
| H0002 `funding_carry_short` | The kill condition required a single cell with positive Calmar on at least five of the nine symbols and a liquidation on none. Six of the nine - SOLUSDT -0.0399, AVAXUSDT -0.0612, BNBUSDT -0.1249, ADAUSDT -0.1677, ETHUSDT -0.1691, DOGEUSDT -0.2928 - have no positive cell anywhere in the 108-cell grid. Counting the 108 cells across the nine symbols, the best any SINGLE cell manages is TWO symbols (... | `reports/POSTMORTEM_H0002.md` |
| H0006 `negative_funding_carry_long` | H0006's kill condition carried four independent clauses and the third is met outright. PBO was computable on three of the nine symbols and reads at or above 0.5 on two of them - BTCUSDT 0.821 and SOLUSDT 0.516, both verdicted SELECTION_IS_NOISE, against BNBUSDT 0.278. Two of three is a majority of the symbols for which it was computed, which is the clause as written: 'Closed also if the reported P... | `reports/POSTMORTEM_H0006.md` |
| H0007 `dislocation_gated_dca` | [claude] clause: Closed also - even if that bar is cleared - if the IRR improvement over the same control with include_funding false is at least as large as the improvement with it true on five or more symbols, since the gain then survives only by not paying the funding tax and the shape has no home on a perpetual. -- 제1절의 기준선은 넘었다 — include_funding true에서 게이트 셀이 gate none 대조군을 이긴 심볼이 9개 중 8개(SOLU... | `reports/POSTMORTEM_H0007.md` |
| H0017 `cci_forced_flow_duel` | [claude] clause: 3. SPIKE. Closed if the recorded shape of the best cell is SPIKE on 5 or more of the 9 symbols. timeframe_hours carries five ordinal levels precisely so this is answerable: H0006 spent 72 configurations on all-binary axes and was closed with the shape column reading '?' on every symbol. -- Clause 3 names the recorded shape of each symbol's best cell, and the surface records it exp... | `reports/POSTMORTEM_H0017.md` |

## H0001 — unconditional_dca_spot_style (track A, metric `mwrr_q05`)

**Claim.** Baseline. Accumulating a major perpetual with equal deposits and no timing rule. Nobody is structurally paying us here; this exists to be the number every conditional rule must beat.

**Kill condition.** Closed if no (symbol, stride, horizon) cell reaches a 5th-percentile terminal multiple above 1.0 across start dates.

Trials in this family: 1344. Pre-registration hash `16461da7e4b64a49`.

| symbol | best | shape | neighbour/peak | start offsets | indep. paths | best cell |
|---|---:|---|---:|---:|---:|---|
| ETHUSDT | +0.6789 | SPIKE | -1.012 | 616 | 1.02 | `{'include_funding': False, 'n_contributions': 52, 'stride_days': 30.0}` |
| SOLUSDT | +0.3727 | SPIKE | -2.069 | 4,289 | 1.16 | `{'include_funding': False, 'n_contributions': 156, 'stride_days': 7.0}` |
| BTCUSDT | +0.3616 | SPIKE | -1.953 | 2,523 | 1.07 | `{'include_funding': False, 'n_contributions': 52, 'stride_days': 30.0}` |
| BNBUSDT | +0.0815 | SPIKE | -5.488 | 396 | 1.36 | `{'include_funding': True, 'n_contributions': 156, 'stride_days': 7.0}` |
| XRPUSDT | -0.0534 | ? | nan | 10,336 | 1.4 | `{'include_funding': False, 'n_contributions': 156, 'stride_days': 7.0}` |
| DOGEUSDT | -0.0988 | ? | nan | 5,871 | 1.23 | `{'include_funding': False, 'n_contributions': 156, 'stride_days': 7.0}` |
| LTCUSDT | -0.2374 | ? | nan | 10,264 | 1.39 | `{'include_funding': False, 'n_contributions': 156, 'stride_days': 7.0}` |
| AVAXUSDT | -0.2986 | ? | nan | 4,073 | 1.16 | `{'include_funding': False, 'n_contributions': 156, 'stride_days': 7.0}` |
| ADAUSDT | -0.3197 | ? | nan | 9,736 | 1.37 | `{'include_funding': False, 'n_contributions': 156, 'stride_days': 7.0}` |

`start offsets` is how many start dates the evaluator scored. `indep. paths` is a generous upper bound on how many of those are genuinely separate experiments, since overlapping windows over the same history are not independent draws. When the two differ by three orders of magnitude, the second is the honest sample size.

- PBO on **ETHUSDT** could not be computed: fewer than two configurations share a horizon
- PBO on **SOLUSDT** could not be computed: fewer than two configurations share a horizon
- PBO on **BTCUSDT** could not be computed: fewer than two configurations share a horizon

## H0019 — cci_mtf_regime_pullback (track B, metric `calmar`)

**Claim.** ORIGIN. reports/SCOUT.jsonl line 4 (codex, 2026-09-03T14:36:05Z, slug leveraged-binance-usd-m-perpetual-short-whose-collateral) -- the same line H0017 took and the line CLAUDE.md section 7b names as this family's payer. This is the THIRD reading of that ONE payer and it must not be counted as a third mechanism: section 6 says a tree re-arranging one idea is narrower than its hypothesis count suggests, and H0017's 90 rows plus this proposal's 72 are 162 rows on one idea. If the payer is not there they die together, and 90 of them already have.

WHO IS STRUCTURALLY PAYING, AND WHY THEY KEEP DOING IT. A Binance USD-M position past maintenance margin is closed by the venue's own risk engine with an immediate-or-cancel order and a clearance fee. It chooses neither its price nor its timing and it cannot wait: the order is sent because a margin ratio crossed a line, not because anyone judged the price. They keep doing it because leverage is the whole reason to hold a perpetual rather than spot -- the venue sells it, and its fee schedule and insurance fund are underwritten on the leveraged base rebuilding after every flush, which it has after every flush this archive contains. It would end if maintenance margin were something the holder could negotiate with, which is not a feature of this product. Nothing in this rule reads panel.funding_rate; the funding the evaluator charges or credits is a cost of holding, never an input to a decision.

WHY THIS PAYER IS NOT ONE ALREADY TESTED. Six of the first eight families read the funding series -- H0002 and H0006 on its level and sign, H0007 and H0009 on a dip gate defended by the same story, H0016 on its trailing mean, and H0016 was killed for exactly that. Every one of them identified the crowded leveraged holder by what he PAYS every eight hours. This family identifies him by what happens when he is CLOSED.

WHAT H0017's RESULT MAKES THE NEXT QUESTION, AND WHY IT IS THIS ONE. H0017 put continuation and relaxation on one grid so they could disagree, and they did: its closure record states that cci_breakout reaches calmar > 0 on 6 of 9 symbols at timeframe_hours = 2 with no liquidations, while cci_reversion reaches calmar > 0 on 0 of 9 symbols at EVERY timeframe. The family then closed on clause 3, SPIKE on 7 of 9 symbols along timeframe_hours -- the peak did not survive one step in either direction. So the map now records two things: the relaxation half of the scouted sentence does not pay unconditionally anywhere, and the continuation half pays only at a corner.

I read orc/eval/signal_rules.py::cci_mtf rather than inferring it. `up = filt >= filter_level` permits LONG and the entry is `entry[up & (base <= -enter_level)] = LONG`; `down = filt <= -filter_level` permits SHORT and the entry is `base >= +enter_level`. That is the RELAXATION trade -- buy the low fast reading -- taken only while the slow candle is displaced the same way. The docstring says so in the same words: "the entry is a pullback AGAINST the permitted side ... That is the trade the reversion rule takes, with the slower reading standing in for the question it cannot answer alone: is this an exhausted cascade or the beginning of one."

So this hypothesis asks one pre-registered question, and clause 1 is the answer: does a slow-candle permission rescue the reading that scored 0 of 9 without one? If it cannot reach 5 of 9, the relaxation half of the payer's observable is dead BOTH unconditionally and conditionally, and this reading of the family is answered rather than merely untried. That comparison is deliberately carried by clause 1's own bar on this family's own numbers and NOT by a cross-family clause: H0018 was killed in part because codex found its clause 2 undecidable when H0017's numbers might be unavailable, and no clause below reads another family's payload.

WHY THIS IS A DIFFERENT RULE FORM AND NOT A FINER GRID. cci_mtf is a different FUNCTION, not a parameterisation of _two_sided. _two_sided reads one array and its exit is `(~finite) | (abs(value) <= exit_level)`, an unsigned return to the band. cci_mtf reads TWO arrays at two resolutions, its entry is conjunctive (a side is permitted only while abs(filt) >= filter_level and is triggered only by the opposite extreme on the fast candle), and its exit has two independent stateless clauses -- `trend_gone = (~ok) | (abs(filt) < filter_level)` and `resolved = sign(filt) * base >= exit_level`, the second of which is a SIGNED threshold measured along the direction of the trade and therefore means something different from H0017's exit_level at the identical number 50.0. The rule has zero rows in the ledger. This is a probe under the 96-configuration ceiling and it spends 72 of them, 1.0 % of the 6,938 trials recorded as of run 715ea48a44be.

WHY THIS IS NOT A RE-SKIN OF CLOSED H0007, WHICH I RAISE AGAINST MYSELF. H0009 was killed as a re-skin of H0007 and H0013 was killed when `sma:<days>` turned out to deploy BELOW the average, making it H0007's weakness-buying shape under a new name. The entry here also buys a fast reading that has fallen, so the objection has to be answered rather than ignored. Three differences, each structural rather than cosmetic. (a) H0007 is Track A: an unconditional stream of deposits whose gate only decides WHEN capital is deployed, and which is long by construction. This is Track B: fixed capital, one position at a time, and the side is chosen by the sign of the slow reading -- `entry[down & (base >= enter_level)] = SHORT` is a trade H0007 cannot express at all. (b) H0007's gate is a level of price against its own trailing peak or average; the permission here is a displacement scaled by that window's own mean absolute deviation, which is the observable the scouted line names and is not a price level. (c) H0007 never exits; this rule exits on its own signal, on two clauses, and holds at most 5 days. If the adversary judges those three insufficient, the honest conclusion is that this shape is H0007 with extra steps and it should be killed on that ground -- but the SHORT arm is the part I cannot see how to reconcile with a long-only accumulator.

WHY filter_level IS THE AXIS AND WHY IT CARRIES FOUR NUMERIC LEVELS. The review that killed H0018 ran all 72 of its cells at zero ledger rows and reported that filter_level = 200 is not a second strength but a switch in the OFF position: 18 of 36 cells did not record at all (no_trades_fired) and the rest fired 1-3 trades per symbol, under that proposal's own T >= 20 floor. Its instruction was to re-propose the shape under a new id with filter_level at levels that are actually live and ordinal, "e.g. 60/80/100/120", and to keep the shape, because the L = 100 arm was alive and informative. I take those four numbers as written. 60, 80 and 100 are at or below a level that review recorded alive; 120 is the only one whose liveness I cannot assert, and it is 20 % above a live level rather than the 100 % that was dead. If it does not record, the frozen counting rule below makes it FAIL rather than pad, and three live ordinal levels still remain for the shape diagnostic.

WHAT THAT AXIS DOES AND DOES NOT ISOLATE, from the code rather than from the name. filter_level appears TWICE: in the entry permission and in `trend_gone`. Raising it therefore makes entries rarer AND exits earlier, so the axis is selectivity and hold-length together and cannot be read as selectivity alone. I state that now because a monotone reading along it will be tempting to describe as "stronger displacement pays better" when it is also "held for less time", and the recorded metrics carry no exit reason with which to separate them.

WHY filter_timeframe_hours HAS ONLY TWO LEVELS, AND WHY THAT IS NOT PADDING. Both 24 and 48 hours are inside the range the H0018 review exercised at L = 100 and neither is a dead arm. The two dropped levels are dropped on grounds available before any number: `_period_bars(20.0, 12.0)` is 40 candles but a 12-hour filter is only three of the 4-hour entry candles, so filt and base would be largely the same information and the shape's whole claim -- that the direction is visible at a resolution the entry is not taken on -- would not be under test; and `_period_bars(20.0, 72.0)` is 7 candles, a CCI whose mean absolute deviation is taken over seven observations. I computed both with that function rather than by hand. Two levels give the diagnostic no step either side, so NO clause below is written on this axis's shape, and it is present as a contrast rather than as an axis I claim to have measured. The fast leg is fixed at the 4-hour candle the owner named, with `_period_bars(5.0, 4.0)` = 30 candles.

WHAT THIS PROBE CANNOT SEE, SAID BEFORE ANY NUMBER EXISTS. The liquidation stream, the forced-order feed, open interest and the mark price are not in this archive. A displaced price is EVIDENCE of forced flow, not a MEASUREMENT of it, and ordinary aggressive trading displaces price too, so no result here may be reported as a measurement of forced liquidation -- only as a partial test of it. Four specific gaps. (1) The payer's sharpest fingerprint is asymmetry: a liquidated short must BUY. cci_mtf breaks _two_sided's symmetry only in the sense that the regime picks the side; no field of SignalTrialConfig restricts the rule to the buy side, so the asymmetry itself stays untested. (2) "Elevated volume" is the other half of the scouted observable and no rule reads volume. (3) enter_level is fixed at 100, so the +-200 extreme is untested; readings past 200 are a SUBSET of what this enters on, so a FAIL here is a FAIL at the band with the extreme diluted into it and never a FAIL at the extreme. (4) The permission and the trigger are read from the same price series, so a cascade and an ordinary trending pullback are indistinguishable to this rule by construction.

WHAT IS DELIBERATELY NOT IN THE KILL CONDITION, AND THE COST OF LEAVING IT OUT. H0017 wrote a cost-stress clause and a `gross_collected` clause and BOTH were recorded unevaluable at closure, because the surface payload carries neither re-priced cells nor the funding-leg split -- an unrun check is not a check that passed, and writing one again would buy the same nothing. So every clause below reads only quantities the H0017 surface demonstrably carried: per-cell `calmar`, and at each symbol's recorded best cell `shape`, `independent_paths_best` and `n_liquidations_best`. The price this pays is that this family CANNOT be closed here for the funding coupon having carried the curve. The structural mitigation is an argument and not a measurement: the rule takes long in up-regimes and short in down-regimes, so unlike H0002 and H0006 it does not sit on one side of the coupon, and a coupon-carried curve would have to be paid on both sides. Costs are the project defaults, 4.5 bps taker plus 1.0 bps slippage, 11 bps a round trip, and they are charged in the recorded numbers even though no clause stresses them.

Leverage is 1.0 and is not on the grid, KT-2 having closed leverage above 1x for averaging down and there being no reason to reopen it on a signal rule. stop_loss is 0.25 of margin, far outside what the entry reads, and is a tail bound rather than the rule's exit; max_hold_days is 5.0, equal to the fast window, so a position may not outlive the reading that justified it. On Track B the independent-path count IS the trade count, and clause 3 is written on it rather than on a bar count.

**Kill condition.** NOTATION AND FROZEN COUNTING RULES. Nine symbols s. Eight cells (L, f), L in {60, 80, 100, 120} and f in {24, 48} hours. C(s, L, f) is the recorded `calmar`. "The best cell" of a symbol means the cell the surface itself records as that symbol's best, which on Track B is the maximum recorded `calmar`; if two cells tie exactly, the lower L, and then the lower f. That selection rule is frozen here because codex killed H0018 for leaving "the best cell" undefined across symbols. At the best cell the surface records `shape`, `independent_paths_best` (which on Track B is n_trades) and `n_liquidations_best`, and clauses 2, 3, 4 and 5 read only those. A cell that does not record at all -- run_signal_trial raising UnsupportedConfig('no_trades_fired') -- counts as FAILING every clause it appears in and never as passing one. No clause reads `gross_collected`, a cost-stressed value, or any number belonging to another hypothesis, because each of those was recorded unevaluable at some earlier closure. Every threshold below is frozen now, before any of these 72 configurations has been run.

1. NO EDGE -- and the clause that carries the whole question. Closed if no single cell (L, f) reaches C > 0 on at least 5 of the 9 symbols. This is deliberately the identical bar, on the identical nine-symbol universe, that H0002, H0006 and H0017 were graded against, so the four are directly comparable and this family cannot be graded on an easier scale than the ones it follows. It is also the comparison this hypothesis exists to make, expressed without reading another family's payload: the unfiltered relaxation rule reached C > 0 on 0 of 9 symbols at every timeframe, so a filtered relaxation rule that cannot reach 5 of 9 has not rescued it, and the relaxation half of the scouted observable is then answered NO both with and without a regime permission.

2. RUIN. Closed if `n_liquidations_best` is above 0 on any of the 9 symbols. At leverage 1.0 behind a 0.25 stop a liquidation should be unreachable, and if one is recorded the Calmar is describing how close to ruin the shape ran. KT-2 closed that direction already and this family does not get to reopen it by accident.

3. TOO THIN TO BE AN EXPERIMENT. Closed if `independent_paths_best` is below 20 on 5 or more of the 9 symbols. On Track B the effective independent-path count IS the trade count, and a curve made of a handful of episodes is a handful of experiments however it looks. This floor is live rather than decorative: the H0018 review measured trade counts collapsing 96-100 % at filter_level 200 with 0 of 9 symbols within 10 %, which is why 200 is not on this grid. If it fires here it is a finding and not a measurement failure -- it says the permission this shape depends on is too rare to be an experiment even at levels already recorded alive, since every level on this grid is at or below one of those.

4. SPIKE. Closed if the recorded shape of the best cell is SPIKE on 5 or more of the 9 symbols. filter_level carries four ordinal live levels precisely so that this is answerable; H0006 spent 72 configurations on all-binary axes and was closed with the shape column reading '?' on every symbol. This clause is deliberately word-for-word H0017's, and it is the clause that closed H0017 on 7 of 9. If the conditional reading peaks at a corner of the level axis exactly as the unconditional one peaked at a corner of the timeframe axis, then what this family is reading is a corner of a grid and not a payer, and that is worth knowing whatever clause 1 says.

5. THE FILTER'S STRENGTH IS NOT WHAT PAYS. Closed if the best cell's filter_level is 60 -- the loosest permission on the grid -- on 5 or more of the 9 symbols. The mechanism claims a larger displacement of the slow candle is a more reliably forced move, so it predicts the edge does NOT live at the loosest setting. At L = 60 the permission is closest to always-on and the shape is closest to the unconditional reversion rule that H0017 recorded at 0 of 9; a majority preference for it says the filter trimmed some bad bars rather than identified a payer. Under a flat surface each of the four levels wins about 2.25 of the 9 symbols, so 5 is a real majority and not a coin flip. This clause can close the family even when clause 1 is met, and it is the only clause that can distinguish "the permission did the work" from "any pullback rule would have done this" on quantities this surface actually records.

WHAT SURVIVAL WOULD REQUIRE, on the record before the numbers and not softenable afterwards: one single cell (L, f) with C > 0 on at least 5 of the 9 symbols, no liquidation recorded at any symbol's best cell, at least 5 symbols whose best cell fired 20 trades or more, a shape that is not SPIKE on a majority, and a best cell above the loosest filter_level on a majority. Only then may a second registration under a new id enumerate the +-200 extreme, the exit_level hysteresis, the fast timeframe and the filter timeframes this probe dropped. A FAIL on any clause above is a publishable result and closes the third and last reading of this payer that the evaluator can express.

Trials in this family: 72. Pre-registration hash `0876046f6a6baa7d`.

| symbol | best | shape | neighbour/peak | start offsets | indep. paths | best cell |
|---|---:|---|---:|---:|---:|---|
| AVAXUSDT | +1.5785 | SPIKE | 0.506 | 1 | 75 | `{'filter_level': 80.0, 'filter_timeframe_hours': 48.0}` |
| ETHUSDT | +0.4196 | SPIKE | 0.576 | 1 | 66 | `{'filter_level': 100.0, 'filter_timeframe_hours': 48.0}` |
| ADAUSDT | +0.3560 | SPIKE | 0.180 | 1 | 100 | `{'filter_level': 80.0, 'filter_timeframe_hours': 48.0}` |
| XRPUSDT | +0.3492 | SPIKE | 0.533 | 1 | 127 | `{'filter_level': 60.0, 'filter_timeframe_hours': 48.0}` |
| SOLUSDT | +0.2941 | SPIKE | 0.214 | 1 | 51 | `{'filter_level': 100.0, 'filter_timeframe_hours': 48.0}` |
| BNBUSDT | +0.2622 | SPIKE | 0.655 | 1 | 33 | `{'filter_level': 120.0, 'filter_timeframe_hours': 48.0}` |
| LTCUSDT | +0.2288 | SPIKE | -0.353 | 1 | 19 | `{'filter_level': 120.0, 'filter_timeframe_hours': 24.0}` |
| DOGEUSDT | +0.1023 | SPIKE | -2.430 | 1 | 51 | `{'filter_level': 100.0, 'filter_timeframe_hours': 48.0}` |
| BTCUSDT | -0.1024 | ? | nan | 1 | 33 | `{'filter_level': 120.0, 'filter_timeframe_hours': 48.0}` |

`start offsets` is how many start dates the evaluator scored. `indep. paths` is a generous upper bound on how many of those are genuinely separate experiments, since overlapping windows over the same history are not independent draws. When the two differ by three orders of magnitude, the second is the honest sample size.

| PBO symbol | PBO | verdict | covers best cell | configs | splits |
|---|---:|---|---|---:|---:|
| AVAXUSDT | 0.234 | SELECTION_INFORMATIVE | yes | 8 | 252 |
| ETHUSDT | 0.599 | SELECTION_IS_NOISE | yes | 8 | 252 |
| ADAUSDT | 0.429 | SELECTION_WEAK | yes | 8 | 252 |

## What the next pass must do

1. Read the shape column first. A `SPIKE` is not a finding no matter how large its value; it means the grid found a corner, not a mechanism.
2. Do not propose a new grid over the same rule form. Parameters are already enumerated exhaustively. Propose a different RULE SHAPE, and state who is structurally paying for it.
3. Every proposal needs a kill condition written before results exist.
4. Say the independent-path count out loud when you argue from a number. Millions of start offsets over six years of history are still only a handful of independent experiments.
5. The holdout stays sealed. Nothing in this document justifies opening it.
