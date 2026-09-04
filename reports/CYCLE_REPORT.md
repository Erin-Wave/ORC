# ORC cycle report

- run `715ea48a44be` finished 2026-09-04T12:28:16.402460+00:00
- trials in project: **6938** (+90 this cycle)
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
| H0017 | DOGEUSDT | +209.8% | 69.8% | equity | spike, p=0.125 vs a random search |
| H0017 | SOLUSDT | +70.9% | 60.6% | equity | spike, p=0.130 vs a random search |
| H0017 | AVAXUSDT | +58.8% | 72.9% | equity | spike, search test unmeasured |
| H0017 | BNBUSDT | +24.1% | 73.0% | equity | spike, PBO unmeasured, search test unmeasured |
| H0017 | BTCUSDT | +17.4% | 65.6% | equity | spike, PBO unmeasured, search test unmeasured |
| H0017 | XRPUSDT | +16.9% | 77.6% | equity | spike, PBO unmeasured, search test unmeasured |
| H0017 | ADAUSDT | +5.4% | 68.3% | equity | spike, PBO unmeasured, search test unmeasured |
| H0017 | ETHUSDT | -2.7% | 82.2% | equity | at or below 0, shape unmeasured, PBO unmeasured, search test unmeasured |
| H0017 | LTCUSDT | -30.2% | 88.6% | equity | at or below 0, shape unmeasured, PBO unmeasured, search test unmeasured |

No cell clears every check. Nothing in this table is a result.

## Closed families -- answered, do not re-propose

These are not gaps in the map. Each was closed against its own pre-registered kill condition and its grid is no longer enumerated. The reason is the finding.

| family | closed because | post-mortem |
|---|---|---|
| H0002 `funding_carry_short` | The kill condition required a single cell with positive Calmar on at least five of the nine symbols and a liquidation on none. Six of the nine - SOLUSDT -0.0399, AVAXUSDT -0.0612, BNBUSDT -0.1249, ADAUSDT -0.1677, ETHUSDT -0.1691, DOGEUSDT -0.2928 - have no positive cell anywhere in the 108-cell grid. Counting the 108 cells across the nine symbols, the best any SINGLE cell manages is TWO symbols (... | `reports/POSTMORTEM_H0002.md` |
| H0006 `negative_funding_carry_long` | H0006's kill condition carried four independent clauses and the third is met outright. PBO was computable on three of the nine symbols and reads at or above 0.5 on two of them - BTCUSDT 0.821 and SOLUSDT 0.516, both verdicted SELECTION_IS_NOISE, against BNBUSDT 0.278. Two of three is a majority of the symbols for which it was computed, which is the clause as written: 'Closed also if the reported P... | `reports/POSTMORTEM_H0006.md` |
| H0007 `dislocation_gated_dca` | [claude] clause: Closed also - even if that bar is cleared - if the IRR improvement over the same control with include_funding false is at least as large as the improvement with it true on five or more symbols, since the gain then survives only by not paying the funding tax and the shape has no home on a perpetual. -- 제1절의 기준선은 넘었다 — include_funding true에서 게이트 셀이 gate none 대조군을 이긴 심볼이 9개 중 8개(SOLU... | `reports/POSTMORTEM_H0007.md` |

## H0001 — unconditional_dca_spot_style (track A, metric `mwrr_q05`)

**Claim.** Baseline. Accumulating a major perpetual with equal deposits and no timing rule. Nobody is structurally paying us here; this exists to be the number every conditional rule must beat.

**Kill condition.** Closed if no (symbol, stride, horizon) cell reaches a 5th-percentile terminal multiple above 1.0 across start dates.

Trials in this family: 1232. Pre-registration hash `16461da7e4b64a49`.

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

## H0017 — cci_forced_flow_duel (track B, metric `calmar`)

**Claim.** ORIGIN. reports/SCOUT.jsonl line 4 (codex, 2026-09-03T14:36:05Z, slug leveraged-binance-usd-m-perpetual-short-whose-collateral), which is the line CLAUDE.md section 7b names as this family's payer. It is taken as written and NOT sign-flipped into a funding rule: H0016 died last night for doing exactly that, and no decision in this hypothesis consults panel.funding_rate at all.

WHO IS STRUCTURALLY PAYING, AND WHY THEY KEEP DOING IT. A Binance USD-M position past maintenance margin is closed by the venue's own risk engine with an immediate-or-cancel order and a clearance fee. It chooses neither its price nor its timing and it cannot wait: the order is sent because a margin ratio crossed a line, not because anyone judged the price to be a good one, and the size is whatever the position happened to be. They keep doing it because leverage is the entire reason to be on a perpetual rather than in spot -- the venue sells it, and its fee schedule and insurance fund are underwritten on the assumption that the leveraged base rebuilds after every flush, which it has after every flush this archive contains. It would end if maintenance margin were enforced by something the holder could negotiate with, which is not a feature of this product.

WHY THIS PAYER IS NOT ONE ALREADY TESTED. Six of the first eight families in this project rested on the funding series: H0002 and H0006 on its level and sign, H0007 and H0009 on a dip gate defended by the same story, H0016 on its trailing mean. Every one of them identified the crowded leveraged holder by what he PAYS every eight hours. This family identifies him by what happens when he is CLOSED, and the observable is displacement of price from its own trailing mean scaled by its own dispersion. The evaluator still charges or credits funding on the position because holding a perpetual costs that -- but it is a cost of the trade here, never an input to it, and clause 5 below exists so a curve carried by the coupon cannot be reported as a CCI result.

ONE PAYER READ THREE WAYS, AND I AM NOT COUNTING IT AS THREE MECHANISMS. Section 6 says a tree that re-arranges one idea is narrower than its hypothesis count suggests, and section 7b says this family is one payer read three ways. This hypothesis takes two of the readings -- continuation (cci_breakout) and relaxation (cci_reversion) -- and its companion H0018 takes the third (cci_mtf). Together they cost 90 + 72 = 162 ledger rows, 2.4 % of the 6,848 already recorded, on ONE mechanism; if the payer is not there, all 162 rows are dead together and that is the honest accounting of what is being bought.

WHY THE PAIR IS THE TEST AND NEITHER SHAPE IS ONE ALONE. The scouted observable is a single sentence with two halves: 'asymmetric continuation and elevated volume, followed by relaxation once the compulsory buy flow is exhausted'. Continuation is cci_breakout, relaxation is cci_reversion, and one payer cannot pay both at the same horizon. So the informative object is not either rule's number but their DISAGREEMENT along the horizon axis, which is why both are on one grid rather than in two hypotheses. I read orc/eval/signal_rules.py rather than assuming it: both rules are the same function _two_sided with a single `fade` flag, so warm-up, entry threshold, exit threshold, hysteresis and the no-flip-without-passing-the-middle rule are identical between them and a disagreement is about direction and nothing else.

WHY timeframe_hours IS THE AXIS, AND WHY IT CARRIES FIVE NUMERIC LEVELS. 'They cannot both be right at one horizon' makes the horizon the axis that decides whether the mechanism is there at all, so it gets 1, 2, 4, 8 and 12 hours -- the 4-hour candle the owner named with a step either side of it in both directions, which is what the shape diagnostic needs to say SPIKE or not. lookback_days is fixed at 5.0 and is a DURATION, so all five cells read the same five-day window at different resolutions: _period_bars gives 120 / 60 / 30 / 15 / 10 candles, which I computed rather than assumed. The axis therefore varies how fast the rule may react to a displacement, not the span the displacement is measured over -- which is what 'at what horizon' has to mean here.

FOUR DESIGN CHOICES, CHECKED IN THE CODE. (a) exit_level is 50.0 and not 0.0, because _two_sided exits on abs(value) <= exit_level and at 0.0 that set is measure-zero on a continuous series: both rules would then exit only on NaN, the stop, the max hold or liquidation, and the duel would be a test of max_hold_days rather than of CCI. 50.0 is halfway back to the centre and identical for both rules, so the pair stays symmetric. (b) max_hold_days is 5.0, equal to the CCI window: a position may not outlive the window that justified it, and the cap bounds a left tail the ledger already knows about, H0002 having recorded that a signal position with no exit rule reaches -1.0. (c) leverage is 1.0 and is not on the grid, KT-2 having closed leverage above 1x; stop_loss is 0.25 of margin, far outside what the entry reads, since a +-100 reading is a displacement of 1.5 times the window's mean absolute deviation. It is a tail bound, not the rule's exit. How often it actually binds cannot be known without running the grid, and the recorded metrics carry no exit reason at all, so no clause below is written on how a position ended. (d) Costs are the project defaults, 4.5 bps taker plus 1.0 bps slippage, 11 bps a round trip. This shape trades far more often than any family so far and the fast end of the timeframe axis is where that is paid; clause 4 is written on it.

WHAT THIS PROBE CANNOT SEE, SAID BEFORE ANY NUMBER EXISTS. The liquidation stream, the forced-order feed, open interest and the mark price are not in this archive. A displaced price is evidence of forced flow, not a measurement of it, and ordinary aggressive trading displaces price too -- so no result from this family may be reported as a measurement of forced liquidation, only as a partial test of it. Three specific gaps, each of which is the mechanism's own fingerprint: the scouted continuation is ASYMMETRIC because a liquidated short must BUY, and _two_sided is symmetric by construction with no field of SignalTrialConfig restricting a rule to one side, so the sharpest fingerprint the payer has is untestable here; 'elevated volume' is the other half of the observable and no rule reads volume; and enter_level is fixed at 100, so +-200 is untested. On that last one the honest statement is narrow rather than convenient: readings past 200 are a SUBSET of what this probe enters on, so a cascade at the extreme does contribute here, diluted by ordinary band-crossings. A FAIL is therefore a FAIL at the band with the extreme diluted into it, and never a FAIL at the extreme.

The stop condition in CLAUDE.md is not a bar this family is judged against, no clause below mentions it, and nothing here is argued on the grounds that this shape might reach it.

**Kill condition.** NOTATION. Nine symbols; r in {cci_breakout, cci_reversion}; t in {1, 2, 4, 8, 12} hours. C(s,r,t) is the recorded `calmar`, Lq the recorded `liquidation_rate`, T the recorded `n_trades`, G the recorded `gross_collected`. Two counting rules, frozen with the rest. A cell that does not record at all -- run_signal_trial raises UnsupportedConfig('no_trades_fired') -- counts as FAILING every clause it appears in and never as passing it. A (symbol, cell) with T < 20 is not counted as a positive symbol anywhere below: on Track B effective_independent_paths IS n_trades, and a curve made of a handful of episodes is a handful of experiments however it looks. If EVERY cell in the grid is disqualified by that floor on five or more symbols, the family is reported UNMEASURABLE rather than closed, because a level that never fires has not been tested. Every threshold below is frozen now, before any of these 90 configurations has been run.

1. NO EDGE. Closed if no single cell (r,t) reaches C > 0 on at least 5 of the 9 symbols while recording Lq = 0 on all nine. This is deliberately the identical bar, on the identical nine-symbol universe, that H0002 and H0006 were both graded against and both failed, so the three are directly comparable and this family cannot be graded on an easier scale than the ones it follows.

2. NOT FORCED FLOW -- the duel, and the only clause neither shape could produce alone. Closed if, at every timeframe t at which either rule meets clause 1's bar, the OTHER rule ALSO reaches C > 0 on at least 5 of the 9 symbols at that same t. One payer cannot pay both the continuation and the relaxation at one horizon; if both are paid, the indicator is reading dispersion rather than forced flow, and a mechanism indistinguishable from ordinary volatility has not been found. This clause can close the family even when clause 1's bar is met.

3. SPIKE. Closed if the recorded shape of the best cell is SPIKE on 5 or more of the 9 symbols. timeframe_hours carries five ordinal levels precisely so this is answerable: H0006 spent 72 configurations on all-binary axes and was closed with the shape column reading '?' on every symbol.

4. COST. Closed if no cell meeting clause 1 still reaches C > 0 on at least 5 of the 9 symbols under scripts/robustness.py's cost stress at COST_STRESS_MULTIPLIER = 2.0, i.e. 22 bps a round trip instead of 11. That check re-prices recorded cells and adds zero ledger rows.

5. THE COUPON, NOT THE INDICATOR. Closed if, among the symbols on which a clause-1 cell is positive, more than half record G <= 0. The price leg and the funding leg sum to total P&L by construction (orc/eval/signal.py), so that pattern says the price leg -- the only thing CCI can claim to have read -- lost, and the coupon carried the curve. That is H0002's and H0006's payer wearing a CCI hat and both are closed.

WHAT SURVIVAL WOULD REQUIRE, so that it is on the record before the numbers and cannot be softened afterwards: one single (r,t) meeting clause 1, its opposite rule NOT meeting it at that same t, a shape that is not SPIKE on a majority, that cell still positive on 5 of 9 at twice the assumed cost, and a positive price leg on most of the symbols it won on. Only then may a second registration under a new id enumerate +-200, the exit_level hysteresis and the sides. A FAIL on any clause above is a publishable result and closes this reading of the payer.

Trials in this family: 90. Pre-registration hash `3b99d3b1478002aa`.

| symbol | best | shape | neighbour/peak | start offsets | indep. paths | best cell |
|---|---:|---|---:|---:|---:|---|
| DOGEUSDT | +3.0063 | SPIKE | 0.514 | 1 | 444 | `{'rule': 'cci_breakout', 'timeframe_hours': 2.0}` |
| SOLUSDT | +1.1696 | SPIKE | 0.096 | 1 | 357 | `{'rule': 'cci_breakout', 'timeframe_hours': 4.0}` |
| AVAXUSDT | +0.8075 | SPIKE | 0.694 | 1 | 313 | `{'rule': 'cci_breakout', 'timeframe_hours': 8.0}` |
| BNBUSDT | +0.3306 | SPIKE | 0.367 | 1 | 436 | `{'rule': 'cci_breakout', 'timeframe_hours': 4.0}` |
| BTCUSDT | +0.2650 | SPIKE | 0.515 | 1 | 621 | `{'rule': 'cci_breakout', 'timeframe_hours': 1.0}` |
| XRPUSDT | +0.2180 | SPIKE | 0.044 | 1 | 501 | `{'rule': 'cci_breakout', 'timeframe_hours': 2.0}` |
| ADAUSDT | +0.0793 | SPIKE | -0.160 | 1 | 428 | `{'rule': 'cci_breakout', 'timeframe_hours': 4.0}` |
| ETHUSDT | -0.0333 | ? | nan | 1 | 571 | `{'rule': 'cci_breakout', 'timeframe_hours': 1.0}` |
| LTCUSDT | -0.3412 | ? | nan | 1 | 444 | `{'rule': 'cci_reversion', 'timeframe_hours': 4.0}` |

`start offsets` is how many start dates the evaluator scored. `indep. paths` is a generous upper bound on how many of those are genuinely separate experiments, since overlapping windows over the same history are not independent draws. When the two differ by three orders of magnitude, the second is the honest sample size.

| PBO symbol | PBO | verdict | covers best cell | configs | splits |
|---|---:|---|---|---:|---:|
| DOGEUSDT | 0.103 | SELECTION_INFORMATIVE | yes | 10 | 252 |
| SOLUSDT | 0.091 | SELECTION_INFORMATIVE | yes | 10 | 252 |
| AVAXUSDT | 0.028 | SELECTION_INFORMATIVE | yes | 10 | 252 |

## What the next pass must do

1. Read the shape column first. A `SPIKE` is not a finding no matter how large its value; it means the grid found a corner, not a mechanism.
2. Do not propose a new grid over the same rule form. Parameters are already enumerated exhaustively. Propose a different RULE SHAPE, and state who is structurally paying for it.
3. Every proposal needs a kill condition written before results exist.
4. Say the independent-path count out loud when you argue from a number. Millions of start offsets over six years of history are still only a handful of independent experiments.
5. The holdout stays sealed. Nothing in this document justifies opening it.
