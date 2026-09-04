# ORC hand-off: propose one hypothesis

You are proposing research on Binance USD-M perpetuals for a project whose deliverable is a MAP OF WHERE RULES BREAK, not an optimal setting. A result of FAIL is publishable and closing a family is a success. Read the rules, then the state of play, then answer with one JSON object and nothing else.

## Rules that will get your proposal rejected mechanically

1. **Name who is structurally paying, and why they keep paying even though it is known.** "This pattern backtests well" is rejected without being run. A payer with no choice about timing (a liquidated leveraged long, a hedger who needs immediacy) is a mechanism; a payer who is simply wrong is not.
2. **Propose a different rule SHAPE, never a finer grid over a shape already tested.** The parameter space is enumerated exhaustively, so a narrower grid is noise mining by definition.
3. **Write the kill condition BEFORE any number exists**, as something computable from the metrics below. It must be able to close your own family.
4. **Every configuration you enumerate enters an append-only ledger** whose row count N is the denominator of the multiple-testing correction. N is currently **6848** and can never be reduced. The grid ceiling is **2000** configurations and a grid over it is refused whole, not trimmed.
5. **At least one grid axis must have three or more NUMERIC levels**, or the shape diagnostic cannot run, and an unmeasured shape is an automatic disqualifier -- every cell would cost N and none could ever be a finding.
6. Data begins 2020 and **everything from 2024-03-01 onward is sealed** and physically absent. Do not propose anything that needs it.

## The owner's standing instruction

**When this project ends.** A rule that reaches a CAGR of **100%** at a maximum drawdown of **25%** or less, and survives verification several times over, ends the research. It is a STOP condition, not a bar any single result is judged against: a family that fails still publishes its failure. Do not weaken a kill condition to get closer to it and do not argue for a proposal on the grounds that it might reach it. What it does change: a shape with no plausible path to a Calmar of 4 is not what the remaining N should be spent on.

**What is being researched next.** Track B, CCI on the 4-hour candle and across timeframes, as a long/short position signal -- `cci_reversion`, `cci_breakout`, `cci_mtf`. One payer read three ways, and say so rather than counting three mechanisms: a position past maintenance margin is closed by the exchange with an immediate-or-cancel order and a clearance fee, choosing neither its price nor its timing. Continuation while that flow runs and relaxation once it is exhausted are the two halves the family splits on, and they cannot both be right at one horizon. The liquidation stream itself is not in this archive, so every claim here is a PARTIAL test and must say which part it cannot see.

## Established results -- do not re-litigate these

- **KT-1**: a long perpetual DCA pays a median funding bill of **36 % of contributed capital** over three years, 87 % of BTC settlements positive. Long-side perp accumulation is CLOSED. Worse than stated: routed through the simulator, the funded 1x long liquidates on 0.69 of ADAUSDT start dates and 0.82 of SOLUSDT's.
- **KT-2**: liquidation reaches **100 % at 2x and above** for averaging down. Leverage above 1x is CLOSED for that shape.
- **KT-3**: 986 symbols ever traded, 481 archived, 266 delisted; the usable delisted sample is still too small. **No alt-basket hypothesis** until that is resolved.
- **H0002 `funding_carry_short`** is CLOSED. The kill condition required a single cell with positive Calmar on at least five of the nine symbols and a liquidation on none. Six of the nine - SOLUSDT -0.0399, AVAXUSDT -0.0612, BNBUSDT -0.1249, ADAUSDT -0.1677, ETHUSDT -0.1691, DOGEUSDT -0.2928 - have no positive cell anywhere in the 108-cell grid. Counting the 108 cells across the nine symbols, the best any SINGLE cell manages is TWO symbols (e.g. lookback 21d / enter 0.0002 / leverage 0.25 / max_hold 30d: BTCUSDT +0.0763 and LTCUSDT +0.0907). Five is not merely unreached, it is arithmetically unreachable. The condition is met and the fami
- **H0006 `negative_funding_carry_long`** is CLOSED. H0006's kill condition carried four independent clauses and the third is met outright. PBO was computable on three of the nine symbols and reads at or above 0.5 on two of them - BTCUSDT 0.821 and SOLUSDT 0.516, both verdicted SELECTION_IS_NOISE, against BNBUSDT 0.278. Two of three is a majority of the symbols for which it was computed, which is the clause as written: 'Closed also if the reported PBO is at or above 0.5 on a majority of the symbols for which it is computed, since selection then carries no information at all.' Both measurements are recorded as covering the best cell, so the noise
- **H0007 `dislocation_gated_dca`** is CLOSED. [claude] clause: Closed also - even if that bar is cleared - if the IRR improvement over the same control with include_funding false is at least as large as the improvement with it true on five or more symbols, since the gain then survives only by not paying the funding tax and the shape has no home on a perpetual. -- 제1절의 기준선은 넘었다 — include_funding true에서 게이트 셀이 gate none 대조군을 이긴 심볼이 9개 중 8개(SOLUSDT만 -0.9015125554825547 < -0.9001710625210104)이므로 다섯 개 문턱을 통과했다. 그러나 제2절이 '설령 그 기준선을 넘더라도'라고 명시한 대로 곧바로 적용되고, 여기서 정확히 다섯 심볼이 걸린다. ADAUSDT는 펀딩을 낼 때 개선폭이 +0.0099064464788521인데 내지 않을 때는 +0.0113448873933

## The fields the evaluator can actually express

A grid or `fixed` block naming anything not on these lists cannot be run and will be killed before registration. This is the single most common way a good idea is wasted here.

**Track A** (`track: "A"`, accumulation: deposits arrive on a schedule, judged on `tm_q05` and annualised MWRR because there is no fixed capital to compute a CAGR against):

```
  contribution
  stride_days
  n_contributions
  hold_days
  leverage
  gate
  take_profit
  stop_loss
  include_funding
  clock
  fee_bps
  slippage_bps
  cost_multiplier
```
`gate` is a string: `"none"`, `"dip:<drop>:<lookback_days>"` (e.g. `"dip:0.20:30"`), or `"sma:<days>"`. `take_profit` and `stop_loss` are fractions of the position's own margin.

**Track B** (`track: "B"`, one position at a time from fixed capital, entered long or short on a signal and closed on a signal, stop or liquidation; judged on Calmar, CAGR, max equity drawdown and Sharpe):

```
  rule
  lookback_days
  enter_rate
  exit_rate
  timeframe_hours
  enter_level
  exit_level
  filter_timeframe_hours
  filter_lookback_days
  filter_level
  capital
  leverage
  stop_loss
  take_profit
  max_hold_days
  clock
  fee_bps
  slippage_bps
  cost_multiplier
```
`rule` must be one of: ['carry_funding', 'carry_funding_long', 'cci_breakout', 'cci_mtf', 'cci_reversion']. A rule that does not exist in the code cannot be proposed -- if your idea needs a new signal generator, say so in the claim and it will be written first, rather than registering a grid that cannot run.

The carry rules read the funding series and use `enter_rate` / `exit_rate`, per SETTLEMENT and not annualised. The `cci_` rules read PRICE and use `enter_level` / `exit_level` in the units the literature quotes (+-100 the band, +-200 the extreme), with `enter_level` above `exit_level`. `lookback_days` is the CCI period as a DURATION, so one value means the same window on every timeframe, and `timeframe_hours` is the candle it is read on, aggregated from the execution clock -- 4.0 with clock `"1h"` is the 4-hour candle traded on the hourly bar. `cci_mtf` also needs `filter_timeframe_hours` (strictly slower than `timeframe_hours`) and a positive `filter_level`.

## What counts as a finding

A cell must clear ALL of: shape not SPIKE (a peak whose neighbours are worse and of the opposite sign is a grid corner, not a mechanism); enough effective independent paths (millions of overlapping start offsets over six years are still a handful of experiments); PBO below 0.5 (at 0.5 the selection carries no information at all); a p-value against a null built by re-running the SAME grid on bootstrapped histories; and a robustness gate of doubled costs, walk-forward, regime split and minute-bar execution. Nothing has cleared all of them yet.

## Answer with exactly this, and nothing else

```json
{
  "hypothesis_id": "H0017",
  "track": "B",
  "family": "short_lowercase_with_underscores",
  "claim": "Who is structurally paying, why they keep paying even though it is known, and what would have to be true for this to be a mechanism rather than a pattern. Several sentences.",
  "kill_condition": "The computable result that would close this family, written now, before any number exists.",
  "universe": [
    "BTCUSDT",
    "ETHUSDT"
  ],
  "grid": {
    "an_axis_from_the_lists_above": [
      1,
      2,
      3
    ]
  },
  "fixed": {
    "another_field_from_the_lists_above": 1.0
  }
}
```

Ids already spent, do not reuse: H0001 (registered), H0002 (closed), H0003 (killed), H0004 (killed), H0005 (killed), H0006 (closed), H0007 (closed), H0008 (killed), H0009 (killed), H0010 (killed), H0011 (killed), H0012 (killed), H0013 (killed), H0014 (killed), H0015 (killed), H0016 (killed). Use `H0017`.

---

## The state of play

Everything below is development data. The ranking is not a result; read the shape column and the independent-path count first.

# ORC cycle report

- run `70dae2406666` finished 2026-09-04T01:42:45.338689+00:00
- trials in project: **6848** (+0 this cycle)
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

## What the next pass must do

1. Read the shape column first. A `SPIKE` is not a finding no matter how large its value; it means the grid found a corner, not a mechanism.
2. Do not propose a new grid over the same rule form. Parameters are already enumerated exhaustively. Propose a different RULE SHAPE, and state who is structurally paying for it.
3. Every proposal needs a kill condition written before results exist.
4. Say the independent-path count out loud when you argue from a number. Millions of start offsets over six years of history are still only a handful of independent experiments.
5. The holdout stays sealed. Nothing in this document justifies opening it.
