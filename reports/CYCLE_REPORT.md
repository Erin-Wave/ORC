# ORC cycle report

- run `0887d2b06967` finished 2026-09-02T10:25:24.732206+00:00
- trials in project: **2756** (+0 this cycle)
- holdout sealed from **2024-03-01**, final tests used 0/3
- primary metric per track: `tm_q05` for accumulation (5th-percentile terminal multiple across start dates), `calmar` for signal positions (return over deepest drawdown)

Every number below is development data only. The ranking is not a result; the shape column and PBO are what decide whether it means anything.

## H0001 — unconditional_dca_spot_style (track A, metric `tm_q05`)

**Claim.** Baseline. Accumulating a major perpetual with equal deposits and no timing rule. Nobody is structurally paying us here; this exists to be the number every conditional rule must beat.

**Kill condition.** Closed if no (symbol, stride, horizon) cell reaches a 5th-percentile terminal multiple above 1.0 across start dates.

Trials in this family: 560. Pre-registration hash `16461da7e4b64a49`.

| symbol | best | shape | neighbour/peak | start offsets | indep. paths | best cell |
|---|---:|---|---:|---:|---:|---|
| ETHUSDT | +3.6056 | SPIKE | 0.166 | 616 | 1.02 | `{'include_funding': False, 'n_contributions': 52, 'stride_days': 30.0}` |
| BTCUSDT | +2.0510 | SPIKE | 0.285 | 2,523 | 1.07 | `{'include_funding': False, 'n_contributions': 52, 'stride_days': 30.0}` |
| SOLUSDT | +1.6619 | SPIKE | 0.295 | 4,289 | 1.16 | `{'include_funding': False, 'n_contributions': 156, 'stride_days': 7.0}` |
| BNBUSDT | +1.1247 | SLOPE | 0.704 | 9,496 | 1.36 | `{'include_funding': True, 'n_contributions': 156, 'stride_days': 7.0}` |
| XRPUSDT | +0.9228 | SPIKE | 0.696 | 10,336 | 1.4 | `{'include_funding': False, 'n_contributions': 156, 'stride_days': 7.0}` |
| DOGEUSDT | +0.8602 | SLOPE | 0.766 | 5,871 | 1.23 | `{'include_funding': False, 'n_contributions': 156, 'stride_days': 7.0}` |
| ADAUSDT | +0.7677 | SLOPE | 0.755 | 34,552 | 29.23 | `{'include_funding': False, 'n_contributions': 52, 'stride_days': 1.0}` |
| LTCUSDT | +0.7403 | SLOPE | 0.797 | 35,080 | 29.66 | `{'include_funding': False, 'n_contributions': 52, 'stride_days': 1.0}` |
| AVAXUSDT | +0.6433 | SLOPE | 0.745 | 28,889 | 24.6 | `{'include_funding': False, 'n_contributions': 52, 'stride_days': 1.0}` |

`start offsets` is how many start dates the evaluator scored. `indep. paths` is a generous upper bound on how many of those are genuinely separate experiments, since overlapping windows over the same history are not independent draws. When the two differ by three orders of magnitude, the second is the honest sample size.

| PBO symbol | PBO | verdict | configs | splits |
|---|---:|---|---:|---:|
| ETHUSDT | 0.000 | SELECTION_INFORMATIVE | 2 | 252 |
| BTCUSDT | 0.000 | SELECTION_INFORMATIVE | 2 | 252 |
| SOLUSDT | 0.516 | SELECTION_IS_NOISE | 2 | 252 |

## H0002 — funding_carry_short (track B, metric `calmar`)

**Claim.** Leveraged long demand on a perpetual pays the funding rate every eight hours for as long as it stays crowded, and keeps paying because the leverage is the whole point of being there: someone who merely wanted the asset would buy spot. KT-1 measured that tax from the paying side at a median 36 percent of contributed capital over a three-year weekly DCA, with 87 percent of BTC settlements positive, and closed long perpetual accumulation over it. This stands on the receiving side of the same trade and asks the only question that side has: can the tax be collected without the directional move that produces it taking the position first? The rule shorts while the trailing mean settlement rate is rich and flattens when it decays, so it is short precisely when long crowding is most expensive - and therefore precisely when a squeeze is most likely. The grid exists to find whether any combination of stop, exposure and holding limit separates the two.

**Kill condition.** Closed if no cell reaches a positive Calmar on at least five of the nine symbols while liquidating on none of them. Collecting funding on the way to a liquidation is not a strategy, and a rule that survives on two symbols out of nine has been selected, not discovered.

Trials in this family: 1944. Pre-registration hash `0d6e7ca037976c0c`.

| symbol | best | shape | neighbour/peak | start offsets | indep. paths | best cell |
|---|---:|---|---:|---:|---:|---|
| BTCUSDT | +0.2433 | SPIKE | -0.115 | 1 | 47 | `{'enter_rate': 0.0002, 'leverage': 1.0, 'lookback_days': 21.0, 'max_hold_days': 7.0, 'stop_loss': None}` |
| LTCUSDT | +0.0464 | SPIKE | -1.869 | 1 | 19 | `{'enter_rate': 0.0002, 'leverage': 0.25, 'lookback_days': 21.0, 'max_hold_days': 30.0, 'stop_loss': 0.25}` |
| XRPUSDT | +0.0385 | SPIKE | -4.778 | 1 | 21 | `{'enter_rate': 0.0002, 'leverage': 0.25, 'lookback_days': 60.0, 'max_hold_days': 30.0, 'stop_loss': 0.1}` |
| SOLUSDT | -0.0399 | ? | nan | 1 | 2 | `{'enter_rate': 0.0002, 'leverage': 0.25, 'lookback_days': 60.0, 'max_hold_days': None, 'stop_loss': None}` |
| AVAXUSDT | -0.0612 | ? | nan | 1 | 5 | `{'enter_rate': 0.0002, 'leverage': 0.25, 'lookback_days': 60.0, 'max_hold_days': None, 'stop_loss': 0.1}` |
| BNBUSDT | -0.1205 | ? | nan | 1 | 23 | `{'enter_rate': 0.0001, 'leverage': 0.25, 'lookback_days': 7.0, 'max_hold_days': None, 'stop_loss': None}` |
| ADAUSDT | -0.1677 | ? | nan | 1 | 23 | `{'enter_rate': 0.0002, 'leverage': 0.25, 'lookback_days': 21.0, 'max_hold_days': 30.0, 'stop_loss': 0.1}` |
| ETHUSDT | -0.1691 | ? | nan | 1 | 56 | `{'enter_rate': 0.0002, 'leverage': 0.25, 'lookback_days': 60.0, 'max_hold_days': 7.0, 'stop_loss': 0.25}` |
| DOGEUSDT | -0.2928 | ? | nan | 1 | 21 | `{'enter_rate': 0.0002, 'leverage': 0.25, 'lookback_days': 60.0, 'max_hold_days': 30.0, 'stop_loss': 0.1}` |

`start offsets` is how many start dates the evaluator scored. `indep. paths` is a generous upper bound on how many of those are genuinely separate experiments, since overlapping windows over the same history are not independent draws. When the two differ by three orders of magnitude, the second is the honest sample size.

| PBO symbol | PBO | verdict | configs | splits |
|---|---:|---|---:|---:|
| BTCUSDT | 0.317 | SELECTION_WEAK | 108 | 252 |
| LTCUSDT | 0.357 | SELECTION_WEAK | 108 | 252 |
| XRPUSDT | 0.647 | SELECTION_IS_NOISE | 108 | 252 |

## H0006 — negative_funding_carry_long (track B, metric `calmar`)

**Claim.** H0002 closed the short side of the funding trade for a structural reason, not a numerical one: shorting a rich settlement rate puts the coupon and the directional exposure on opposite sides of the book, because the rate is rich exactly when leveraged long demand is strongest, which is exactly when price is rising. Six of nine symbols had no positive cell anywhere in 972 trials. This is the leg that was never tested, and it is the leg where the two point the same way. Negative funding means the shorts are paying the longs. It appears when leveraged bearish positioning is crowded - inside drawdowns and just after capitulation - and a crowded short base is the same condition that produces upward squeezes, so the coupon is collected while the directional move, when it comes, is in the position's favour rather than against it. Who pays: the leveraged bear, and the desk holding spot that needs protection now. They keep paying because the demand to be short in a drawdown is a demand for immediacy - a hedge deferred until the rate normalises is not a hedge, and a bear who waits for cheap funding has missed the move they are positioning for - so the rate stays negative until the crowd unwinds. This does not re-open KT-1. KT-1 closed unconditional long perpetual accumulation because it pays the tax at a median 36 percent of contributed capital; this rule holds the perpetual only while that tax is a rebate and flattens once the trailing rate crosses back above the 0.01 percent baseline at which the tax resumes. The real deliverable is the asymmetry. The evaluator's own note on this rule is that if the mirror pays as well as the original then what is being harvested is not the funding tax but something else; H0002 established that the original does not pay, so a mirror that also fails would say that the funding level carries no tradable information on either side, and a mirror that pays would locate the effect in the rarity and depth of the negative case rather than in carry as such. Either outcome closes a question rather than opening one.

**Kill condition.** Closed if no single cell reaches a positive Calmar on at least five of the nine symbols with funding included while liquidating on none of them - the same bar H0002 failed, so the two sides are directly comparable. Closed also, whatever the Calmar, if every cell that clears that bar has shape SPIKE: a positive sitting in a negative neighbourhood is a grid corner, and that is precisely what closed H0002. Closed also if the reported PBO is at or above 0.5 on a majority of the symbols for which it is computed, since selection then carries no information at all. Closed also if the effective independent-path count at the best cell is below 5 on a majority of the nine symbols - negative funding is rarer and shallower than the positive case, and a Calmar resting on fewer than five genuinely separate episodes describes those episodes, not a mechanism, and must not be reported as a result.

Trials in this family: 144. Pre-registration hash `d6b50b9b2c14f44f`.

| symbol | best | shape | neighbour/peak | start offsets | indep. paths | best cell |
|---|---:|---|---:|---:|---:|---|
| SOLUSDT | +1.4007 | ? | nan | 1 | 12 | `{'enter_rate': -0.0001, 'lookback_days': 21, 'stop_loss': 0.15}` |
| BNBUSDT | +1.3364 | ? | nan | 1 | 19 | `{'enter_rate': -0.0001, 'lookback_days': 7, 'stop_loss': None}` |
| BTCUSDT | +1.2803 | ? | nan | 1 | 2 | `{'enter_rate': -0.0001, 'lookback_days': 21, 'stop_loss': 0.15}` |
| DOGEUSDT | +1.1799 | ? | nan | 1 | 4 | `{'enter_rate': -0.0001, 'lookback_days': 21, 'stop_loss': 0.15}` |
| ETHUSDT | +0.3621 | ? | nan | 1 | 8 | `{'enter_rate': 0.0, 'lookback_days': 7, 'stop_loss': 0.15}` |
| ADAUSDT | +0.3533 | ? | nan | 1 | 12 | `{'enter_rate': 0.0, 'lookback_days': 21, 'stop_loss': 0.15}` |
| AVAXUSDT | +0.2758 | ? | nan | 1 | 5 | `{'enter_rate': -0.0001, 'lookback_days': 21, 'stop_loss': None}` |
| XRPUSDT | +0.2248 | ? | nan | 1 | 10 | `{'enter_rate': -0.0001, 'lookback_days': 7, 'stop_loss': 0.15}` |
| LTCUSDT | +0.1684 | ? | nan | 1 | 6 | `{'enter_rate': -0.0001, 'lookback_days': 7, 'stop_loss': 0.15}` |

`start offsets` is how many start dates the evaluator scored. `indep. paths` is a generous upper bound on how many of those are genuinely separate experiments, since overlapping windows over the same history are not independent draws. When the two differ by three orders of magnitude, the second is the honest sample size.

| PBO symbol | PBO | verdict | configs | splits |
|---|---:|---|---:|---:|
| SOLUSDT | 0.516 | SELECTION_IS_NOISE | 8 | 252 |
| BNBUSDT | 0.290 | SELECTION_WEAK | 8 | 252 |
| BTCUSDT | 0.821 | SELECTION_IS_NOISE | 8 | 252 |

## H0007 — dislocation_gated_dca (track A, metric `tm_q05`)

**Claim.** H0001 is unconditional by construction and its own claim says nobody is structurally paying it; its 448 trials vary how often and how many times money arrives, never whether a given bar is a bar worth buying. This proposes the axis H0001 has never held: a gate. Who pays: the liquidated leveraged long. On a perpetual venue a position that breaches maintenance margin is closed by the exchange at whatever price the book offers, in size, at a moment the seller did not choose and cannot decline - and because the liquidation of one position moves price into the maintenance level of the next, the selling arrives in cascades rather than smoothly. They keep doing it because leverage is the entire reason to be on this venue instead of buying spot, so the leveraged long base rebuilds after every flush; the venue's own fee schedule and insurance fund are built on the assumption that it will. A depositor with no urgency is the natural counterparty to a seller with no choice about timing, and the gate is the only way a scheduled depositor expresses that: contribute on bars that follow a drawdown of the gated depth, hold the cash otherwise. Two gate depths at two timescales are enumerated rather than a ladder, because they ask different questions - a 10 percent drawdown inside 7 days is a cascade, a 20 percent drawdown inside 30 days is a regime, and if only one pays then the answer names which. This does not and cannot repeal KT-1. Deferring a deposit changes the price at which it lands, not the fact that the perpetual charges the holder funding for as long as it is held, and the tax is therefore carried on the grid as include_funding so that it is measured rather than assumed away. If the gate beats its control only with funding switched off, the honest reading is that the dislocation exists but a perpetual cannot host the trade that harvests it, which is a finding about the venue and not about the gate. gate none is enumerated as an internal control rather than compared against H0001 across hypotheses, because the gate defers contributions and therefore moves the horizon: tm_q05 is a multiple of contributed capital and grows with holding time, so the comparison that decides this hypothesis is the annualised IRR, with tm_q05 reported beside it.

**Kill condition.** Closed if, with include_funding true, no gated cell's annualised IRR exceeds the gate none cell at the same symbol, stride and contribution count on at least five of the nine symbols. Closed also - even if that bar is cleared - if the IRR improvement over the same control with include_funding false is at least as large as the improvement with it true on five or more symbols, since the gain then survives only by not paying the funding tax and the shape has no home on a perpetual. Closed also if every cell that clears the first clause has shape SPIKE, or if the reported PBO is at or above 0.5 on a majority of the symbols for which it is computed. Closed as unmeasurable, rather than false, if the gate does not bind: if on five or more symbols both the IRR and the tm_q05 of every gated cell differ from the gate none control by less than one percent in relative terms, then the gate never fired often enough to change anything and the family has not been tested.

Trials in this family: 108. Pre-registration hash `5c39d5b986fce8ca`.

| symbol | best | shape | neighbour/peak | start offsets | indep. paths | best cell |
|---|---:|---|---:|---:|---:|---|
| BNBUSDT | +0.8095 | ? | nan | 1,124 | 4.15 | `{'gate': 'dip:0.20:30', 'include_funding': True}` |
| BTCUSDT | +0.6199 | ? | nan | 1,279 | 4.58 | `{'gate': 'dip:0.20:30', 'include_funding': False}` |
| ETHUSDT | +0.6164 | ? | nan | 1,199 | 4.36 | `{'gate': 'dip:0.20:30', 'include_funding': False}` |
| XRPUSDT | +0.5359 | ? | nan | 1,159 | 4.24 | `{'gate': 'dip:0.20:30', 'include_funding': False}` |
| LTCUSDT | +0.5111 | ? | nan | 1,156 | 4.24 | `{'gate': 'dip:0.20:30', 'include_funding': False}` |
| DOGEUSDT | +0.4871 | ? | nan | 973 | 3.72 | `{'gate': 'dip:0.20:30', 'include_funding': False}` |
| ADAUSDT | +0.4775 | ? | nan | 1,134 | 4.17 | `{'gate': 'dip:0.20:30', 'include_funding': False}` |
| AVAXUSDT | +0.4506 | ? | nan | 898 | 3.51 | `{'gate': 'dip:0.10:7', 'include_funding': False}` |
| SOLUSDT | +0.3989 | ? | nan | 21,761 | 3.54 | `{'gate': 'none', 'include_funding': True}` |

`start offsets` is how many start dates the evaluator scored. `indep. paths` is a generous upper bound on how many of those are genuinely separate experiments, since overlapping windows over the same history are not independent draws. When the two differ by three orders of magnitude, the second is the honest sample size.

| PBO symbol | PBO | verdict | configs | splits |
|---|---:|---|---:|---:|
| BNBUSDT | 0.167 | SELECTION_INFORMATIVE | 2 | 252 |
| BTCUSDT | 0.000 | SELECTION_INFORMATIVE | 2 | 252 |
| ETHUSDT | 0.000 | SELECTION_INFORMATIVE | 2 | 252 |

## What the next pass must do

1. Read the shape column first. A `SPIKE` is not a finding no matter how large its value; it means the grid found a corner, not a mechanism.
2. Do not propose a new grid over the same rule form. Parameters are already enumerated exhaustively. Propose a different RULE SHAPE, and state who is structurally paying for it.
3. Every proposal needs a kill condition written before results exist.
4. Say the independent-path count out loud when you argue from a number. Millions of start offsets over six years of history are still only a handful of independent experiments.
5. The holdout stays sealed. Nothing in this document justifies opening it.
