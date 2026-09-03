# ORC cycle report

- run `8f62f3b9ad94` finished 2026-09-03T04:00:01.802043+00:00
- trials in project: **6736** (+112 this cycle)
- holdout sealed from **2024-03-01**, final tests used 0/3
- primary metric per track: `tm_q05` for accumulation (5th-percentile terminal multiple across start dates), `calmar` for signal positions (return over deepest drawdown)

Every number below is development data only. The ranking is not a result; the shape column and PBO are what decide whether it means anything.

## Headline

Best cell per family per symbol, ranked on the metric that survives a horizon change. `return p.a.` is the annualised money-weighted return at the 5th percentile of start dates on track A, and the CAGR of the single equity curve on track B. `max drawdown` is drawdown on invested capital on track A -- peak-to-trough of profit over contributed capital, so it can exceed 100% -- and conventional equity drawdown on track B. The two are not comparable and are labelled.

| family | symbol | return p.a. | max drawdown | basis | not a finding because |
|---|---|---:|---:|---|---|
| H0001 | ADAUSDT | n/a | 418.8% | invested | at or below 0, shape unmeasured, 1.37 paths, PBO unmeasured, search test unmeasured |
| H0001 | AVAXUSDT | n/a | 311.0% | invested | at or below 0, shape unmeasured, 1.16 paths, PBO unmeasured, search test unmeasured |
| H0001 | BNBUSDT | n/a | 271.9% | invested | spike, 1.36 paths, PBO unmeasured, search test unmeasured |
| H0001 | BTCUSDT | n/a | 193.4% | invested | spike, 1.07 paths, PBO unmeasured, search test unmeasured |
| H0001 | DOGEUSDT | n/a | 1344.9% | invested | at or below 0, shape unmeasured, 1.23 paths, PBO unmeasured, search test unmeasured |
| H0001 | ETHUSDT | n/a | 481.5% | invested | spike, 1.02 paths, PBO unmeasured, p=1.000 vs a random search |
| H0001 | LTCUSDT | n/a | 130.6% | invested | at or below 0, shape unmeasured, 1.39 paths, PBO unmeasured, search test unmeasured |
| H0001 | SOLUSDT | n/a | 849.7% | invested | spike, 1.16 paths, PBO unmeasured, p=1.000 vs a random search |
| H0001 | XRPUSDT | n/a | 139.1% | invested | at or below 0, shape unmeasured, 1.4 paths, PBO unmeasured, search test unmeasured |

No cell clears every check. Nothing in this table is a result.

## Closed families -- answered, do not re-propose

These are not gaps in the map. Each was closed against its own pre-registered kill condition and its grid is no longer enumerated. The reason is the finding.

| family | closed because | post-mortem |
|---|---|---|
| H0002 `funding_carry_short` | The kill condition required a single cell with positive Calmar on at least five of the nine symbols and a liquidation on none. Six of the nine - SOLUSDT -0.0399, AVAXUSDT -0.0612, BNBUSDT -0.1249, ADAUSDT -0.1677, ETHUSDT -0.1691, DOGEUSDT -0.2928 - have no positive cell anywhere in the 108-cell grid. Counting the 108 cells across the nine symbols, the best any SINGLE cell manages is TWO symbols (... | `reports/POSTMORTEM_H0002.md` |
| H0006 `negative_funding_carry_long` | H0006's kill condition carried four independent clauses and the third is met outright. PBO was computable on three of the nine symbols and reads at or above 0.5 on two of them - BTCUSDT 0.821 and SOLUSDT 0.516, both verdicted SELECTION_IS_NOISE, against BNBUSDT 0.278. Two of three is a majority of the symbols for which it was computed, which is the clause as written: 'Closed also if the reported P... | `reports/POSTMORTEM_H0006.md` |
| H0007 `dislocation_gated_dca` | [claude] clause: Closed also - even if that bar is cleared - if the IRR improvement over the same control with include_funding false is at least as large as the improvement with it true on five or more symbols, since the gain then survives only by not paying the funding tax and the shape has no home on a perpetual. -- 제1절의 기준선은 넘었다 — include_funding true에서 게이트 셀이 gate none 대조군을 이긴 심볼이 9개 중 8개(SOLU... | `reports/not written` |

## H0001 — unconditional_dca_spot_style (track A, metric `mwrr_q05`)

**Claim.** Baseline. Accumulating a major perpetual with equal deposits and no timing rule. Nobody is structurally paying us here; this exists to be the number every conditional rule must beat.

**Kill condition.** Closed if no (symbol, stride, horizon) cell reaches a 5th-percentile terminal multiple above 1.0 across start dates.

Trials in this family: 1120. Pre-registration hash `16461da7e4b64a49`.

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

## What the next pass must do

1. Read the shape column first. A `SPIKE` is not a finding no matter how large its value; it means the grid found a corner, not a mechanism.
2. Do not propose a new grid over the same rule form. Parameters are already enumerated exhaustively. Propose a different RULE SHAPE, and state who is structurally paying for it.
3. Every proposal needs a kill condition written before results exist.
4. Say the independent-path count out loud when you argue from a number. Millions of start offsets over six years of history are still only a handful of independent experiments.
5. The holdout stays sealed. Nothing in this document justifies opening it.
