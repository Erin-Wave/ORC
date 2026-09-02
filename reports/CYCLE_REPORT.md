# ORC cycle report

- run `8b0c50c90c1e` finished 2026-09-02T04:13:59.678359+00:00
- trials in project: **336** (+0 this cycle)
- holdout sealed from **2024-03-01**, final tests used 0/3
- primary metric: `tm_q05` (5th-percentile terminal multiple across start dates)

Every number below is development data only. The ranking is not a result; the shape column and PBO are what decide whether it means anything.

## H0001 — unconditional_dca_spot_style

**Claim.** Baseline. Accumulating a major perpetual with equal deposits and no timing rule. Nobody is structurally paying us here; this exists to be the number every conditional rule must beat.

**Kill condition.** Closed if no (symbol, stride, horizon) cell reaches a 5th-percentile terminal multiple above 1.0 across start dates.

Trials in this family: 336. Pre-registration hash `16461da7e4b64a49`.

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
| ADAUSDT | 0.000 | SELECTION_INFORMATIVE | 12 | 252 |
| AVAXUSDT | 0.000 | SELECTION_INFORMATIVE | 12 | 252 |
| BNBUSDT | 0.008 | SELECTION_INFORMATIVE | 12 | 252 |

## What the next pass must do

1. Read the shape column first. A `SPIKE` is not a finding no matter how large its value; it means the grid found a corner, not a mechanism.
2. Do not propose a new grid over the same rule form. Parameters are already enumerated exhaustively. Propose a different RULE SHAPE, and state who is structurally paying for it.
3. Every proposal needs a kill condition written before results exist.
4. Say the independent-path count out loud when you argue from a number. Millions of start offsets over six years of history are still only a handful of independent experiments.
5. The holdout stays sealed. Nothing in this document justifies opening it.
