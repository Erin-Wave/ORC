# ORC cycle report

- run `a67db5d32656` finished 2026-09-02T05:42:00.602038+00:00
- trials in project: **1308** (+972 this cycle)
- holdout sealed from **2024-03-01**, final tests used 0/3
- primary metric per track: `tm_q05` for accumulation (5th-percentile terminal multiple across start dates), `calmar` for signal positions (return over deepest drawdown)

Every number below is development data only. The ranking is not a result; the shape column and PBO are what decide whether it means anything.

## H0002 — funding_carry_short (track B, metric `calmar`)

**Claim.** Leveraged long demand on a perpetual pays the funding rate every eight hours for as long as it stays crowded, and keeps paying because the leverage is the whole point of being there: someone who merely wanted the asset would buy spot. KT-1 measured that tax from the paying side at a median 36 percent of contributed capital over a three-year weekly DCA, with 87 percent of BTC settlements positive, and closed long perpetual accumulation over it. This stands on the receiving side of the same trade and asks the only question that side has: can the tax be collected without the directional move that produces it taking the position first? The rule shorts while the trailing mean settlement rate is rich and flattens when it decays, so it is short precisely when long crowding is most expensive - and therefore precisely when a squeeze is most likely. The grid exists to find whether any combination of stop, exposure and holding limit separates the two.

**Kill condition.** Closed if no cell reaches a positive Calmar on at least five of the nine symbols while liquidating on none of them. Collecting funding on the way to a liquidation is not a strategy, and a rule that survives on two symbols out of nine has been selected, not discovered.

Trials in this family: 972. Pre-registration hash `0d6e7ca037976c0c`.

| symbol | best | shape | neighbour/peak | start offsets | indep. paths | best cell |
|---|---:|---|---:|---:|---:|---|
| BTCUSDT | +0.2433 | SPIKE | -0.115 | 1 | 47 | `{'enter_rate': 0.0002, 'leverage': 1.0, 'lookback_days': 21.0, 'max_hold_days': 7.0, 'stop_loss': None}` |
| LTCUSDT | +0.0464 | SPIKE | -1.867 | 1 | 19 | `{'enter_rate': 0.0002, 'leverage': 0.25, 'lookback_days': 21.0, 'max_hold_days': 30.0, 'stop_loss': 0.25}` |
| XRPUSDT | +0.0386 | SPIKE | -4.772 | 1 | 21 | `{'enter_rate': 0.0002, 'leverage': 0.25, 'lookback_days': 60.0, 'max_hold_days': 30.0, 'stop_loss': 0.1}` |
| SOLUSDT | -0.0399 | PLATEAU | 25.061 | 1 | 2 | `{'enter_rate': 0.0002, 'leverage': 0.25, 'lookback_days': 60.0, 'max_hold_days': None, 'stop_loss': None}` |
| AVAXUSDT | -0.0612 | PLATEAU | 3.973 | 1 | 5 | `{'enter_rate': 0.0002, 'leverage': 0.25, 'lookback_days': 60.0, 'max_hold_days': None, 'stop_loss': 0.1}` |
| BNBUSDT | -0.1204 | PLATEAU | 8.304 | 1 | 23 | `{'enter_rate': 0.0001, 'leverage': 0.25, 'lookback_days': 7.0, 'max_hold_days': None, 'stop_loss': None}` |
| ADAUSDT | -0.1676 | PLATEAU | 1.298 | 1 | 23 | `{'enter_rate': 0.0002, 'leverage': 0.25, 'lookback_days': 21.0, 'max_hold_days': 30.0, 'stop_loss': 0.1}` |
| ETHUSDT | -0.1691 | PLATEAU | 1.186 | 1 | 56 | `{'enter_rate': 0.0002, 'leverage': 0.25, 'lookback_days': 60.0, 'max_hold_days': 7.0, 'stop_loss': 0.25}` |
| DOGEUSDT | -0.2929 | PLATEAU | 1.028 | 1 | 21 | `{'enter_rate': 0.0002, 'leverage': 0.25, 'lookback_days': 60.0, 'max_hold_days': 30.0, 'stop_loss': 0.1}` |

`start offsets` is how many start dates the evaluator scored. `indep. paths` is a generous upper bound on how many of those are genuinely separate experiments, since overlapping windows over the same history are not independent draws. When the two differ by three orders of magnitude, the second is the honest sample size.

## What the next pass must do

1. Read the shape column first. A `SPIKE` is not a finding no matter how large its value; it means the grid found a corner, not a mechanism.
2. Do not propose a new grid over the same rule form. Parameters are already enumerated exhaustively. Propose a different RULE SHAPE, and state who is structurally paying for it.
3. Every proposal needs a kill condition written before results exist.
4. Say the independent-path count out loud when you argue from a number. Millions of start offsets over six years of history are still only a handful of independent experiments.
5. The holdout stays sealed. Nothing in this document justifies opening it.
