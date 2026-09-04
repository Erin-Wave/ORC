# H0019 — `cci_mtf_regime_pullback` — CLOSED on clause 4 (SPIKE, 8 of 9)

| | |
|---|---|
| Track | B (signal, fixed capital, one position at a time) |
| Metric | `calmar` |
| Grid | 4 × 2 × 9 symbols = 72 cells, all 72 recorded, none `no_trades_fired` |
| Cost in `N` | 72 rows, 1.03 % of the 7,010 trials recorded at registration; 162 rows (2.3 %) counting H0017 on the same payer |
| Prereg hash | `0876046f6a6b…` — registered 2026-09-04T17:52Z, closed against the kill condition as written |
| Holdout | untouched; every number below is inside the development window ending at the 2024-03-01 seal |
| Clauses | 1 PASS, 2 PASS, 3 PASS, 4 **FAIL**, 5 PASS |

---

## What was claimed

The payer is the one CLAUDE.md § 7b names and `reports/SCOUT.jsonl` line 4 supplied: a Binance USD-M position past maintenance margin is closed by the venue's own risk engine with an immediate-or-cancel order and a clearance fee, choosing neither its price nor its timing. H0019 was the third reading of that single payer and said so — not a third mechanism, a third shape over one idea. Where H0017 put continuation and relaxation on one grid and the relaxation half scored `calmar > 0` on 0 of 9 symbols at every timeframe, H0019 asked one question: does a *slow-candle permission* rescue the reading that failed unconditionally? `cci_mtf` permits a side only while the 24 h or 48 h CCI is displaced past `filter_level`, and then enters *against* that displacement on the 4-hour candle — buy the low fast reading inside an up-regime, sell the high fast reading inside a down-regime. The mechanism's own directional prediction was explicit: a larger slow displacement is a more reliably forced move, so the edge should **not** live at the loosest permission. The registration also named, before any number, that `filter_level` appears twice in the rule — in the entry permission and in `trend_gone` — so the axis is selectivity *and* hold-length together and cannot be read as selectivity alone.

## What happened

Every one of the 72 cells recorded. Per-symbol best cell (the surface's own maximum `calmar`), with the disqualifiers attached:

| symbol | best (L, f) | calmar | CAGR | MDD | Sharpe | shape (plateau ratio) | paths = trades | liq | funding_frac | PBO |
|---|---|---|---|---|---|---|---|---|---|---|
| AVAX | 80 / 48 | **1.5785** | 0.3877 | 0.2456 | 0.993 | SPIKE (0.506) | 75 | 0 | +0.0043 | 0.234 `SELECTION_INFORMATIVE` |
| ETH | 100 / 48 | 0.4196 | 0.0914 | 0.2177 | 0.403 | SPIKE (0.576) | 66 | 0 | −0.0047 | **0.599 `SELECTION_IS_NOISE`** |
| ADA | 80 / 48 | 0.3560 | 0.1649 | 0.4631 | 0.418 | SPIKE (0.180) | 100 | 0 | +0.0142 | 0.429 `SELECTION_WEAK` |
| XRP | 60 / 48 | 0.3492 | 0.1348 | 0.3861 | 0.351 | SPIKE (0.533, 1 nbr) | 127 | 0 | +0.0116 | — |
| SOL | 100 / 48 | 0.2941 | 0.0857 | 0.2912 | 0.307 | SPIKE (0.214) | 51 | 0 | −0.0028 | — |
| BNB | 120 / 48 | 0.2622 | 0.0332 | 0.1267 | 0.256 | SPIKE (0.655, 1 nbr) | 33 | 0 | +0.0019 | — |
| LTC | 120 / 24 | 0.2288 | 0.0187 | 0.0817 | 0.352 | SPIKE (−0.353, 1 nbr) | 19 | 0 | −0.0015 | — |
| DOGE | 100 / 48 | 0.1023 | 0.0332 | 0.3250 | 0.150 | SPIKE (−2.430) | 51 | 0 | −0.0199 | — |
| BTC | 120 / 48 | **−0.1024** | −0.0275 | 0.2687 | −0.242 | unmeasurable (peak not positive) | 33 | 0 | −0.0027 | — |

Median best-cell Calmar 0.294, mean 0.388 — and both are maxima over eight cells each, so both are upward-biased by construction. `n_starts_best = 1` everywhere: nine symbols is nine equity curves over one 2019-2024 history, and the 19–127 "independent paths" are trades *inside* those nine curves, overlapping in regime.

Clause by clause, on the frozen counting rules:

- **Clause 1 (no edge) — PASSED, and it is the one the family existed to answer.** Cell (L = 120, f = 48) reaches `calmar > 0` on **7 of 9** symbols (all but BTC and DOGE); (100, 48) on 6 of 9; (60, 24), (60, 48) and (80, 48) each on 5 of 9. The bar was 5 of 9 on the same nine-symbol universe H0002, H0006 and H0017 were graded against. The regime permission moved the relaxation reading from H0017's 0 of 9 to 7 of 9. That is a real pre-registered pass and it is stated first.
- **Clause 2 (ruin) — PASSED.** `n_liquidations_best = 0` on all nine.
- **Clause 3 (too thin) — PASSED.** Only LTC (19 trades) is below the floor of 20; the clause needed 5 of 9.
- **Clause 4 (SPIKE) — FAILED, and it closes the family.** Eight of nine best cells are recorded `SPIKE`; the ninth (BTC) is `unmeasurable` because its peak is not positive. **Zero of nine symbols show a plateau anywhere on the grid.** The clause is word-for-word H0017's, which fired on 7 of 9.
- **Clause 5 (the filter's strength is not what pays) — PASSED, on a technicality examined below.** Only XRP's best cell sits at L = 60; the clause needed 5 of 9.

The robustness gate ran one row for this family — AVAX at (80, 48), the peak — and returned `passed: false`, `failed: []`, `unmeasured: ["execution"]`:

- cost ×2: 1.5785 → 1.4255, retention 90.3 % — **passed**
- walk forward, 4 blocks / 2 train: in-sample 2.2670 → out-of-sample 1.7986, retention 0.793 — **passed**
- regime split (720-bar window): rising 0.4967, falling 0.3221, both positive — **passed**
- execution realism: **never ran** — "no minute panel here; certification has to happen locally"

And the search test, on the two symbols it covered:

| symbol | observed best | null best-of-8 mean | null q95 | p | verdict |
|---|---|---|---|---|---|
| AVAX | 1.5785 | 0.3767 | 1.5265 | 0.050 | `INDISTINGUISHABLE_FROM_SEARCH` |
| ETH | 0.4196 | 0.2578 | 0.9551 | 0.275 | `INDISTINGUISHABLE_FROM_SEARCH` |

CLAUDE.md records the project's best Calmar over 6,848 trials as 1.4007. **AVAX's 1.5785 is the highest Calmar this project has recorded, and it is the same cell its own block-shuffled null cannot be distinguished from at p = 0.05.**

## Why it broke

**One symbol is the entire result.** Summing all 72 recorded cells: mean Calmar +0.052, and exactly 36 of 72 cells positive — a coin flip. AVAX is positive in 8 of its 8 cells and contributes 5.547 of the grid's 3.748 total. Remove it and the remaining 64 cells sum to **−1.799, mean −0.028**, with 28 of 64 positive. Every clause-1 count above includes AVAX; at (120, 48), the 7-of-9 cell, the nine values have a median of only 0.086 and two symbols (ADA 0.0074, XRP 0.0298) within 0.03 of zero. Clause 1 passed on a distribution centred at zero with one outlier, and that outlier fails its own search test.

**The axis the mechanism predicted would order the result does not order it.** Mean Calmar over the 18 cells at each `filter_level`: L60 **+0.070**, L80 +0.044, L100 +0.069, L120 **+0.025**. Non-monotone, spread 0.045, and the *loosest* permission has the highest mean — the direction the claim explicitly predicted against. Excluding AVAX, all four level means are negative (L60 −0.012, L80 −0.079, L100 −0.007, L120 −0.014) and the ordering is still not monotone. The mechanism said stronger displacement is more reliably forced flow. Across 72 recorded cells, displacement strength carries no gradient at all.

**Clause 5 passed for a reason that is not the mechanism.** The winning level scatters (60 ×1, 80 ×2, 100 ×3, 120 ×3), which is what kept clause 5 from firing — but the scatter tracks sample size, not payer strength. Mean trade count at each winning level: L60 → 127, L80 → 87.5, L100 → 56, L120 → 28.3. Strictly monotone decreasing. The three symbols whose best cell chose the strongest filter (BNB 33, BTC 33, LTC 19) are the three thinnest curves on the board, where a Calmar is least stable. The registration named this confound in advance — `filter_level` sits in both the entry permission and `trend_gone`, so raising it makes entries rarer *and* exits earlier — and the recorded metrics carry no exit reason with which to separate them. So clause 5's pass distinguishes nothing: "the permission identified a payer" and "fewer, shorter trades landed luckily" produce the same table.

**The one regularity in the data is on the axis the prereg forbade itself to read.** The 48-hour filter beats the 24-hour one everywhere it is compared: 23 of 36 cells positive at f = 48 versus 13 of 36 at f = 24; mean +0.132 versus −0.027; 8 of 9 best cells at f = 48 (LTC alone at 24). That is the largest effect on the surface. It is also the axis carrying only two levels, which the registration declared present "as a contrast rather than as an axis I claim to have measured", writing no clause on it precisely so it could not be claimed after the fact. The discipline worked exactly as designed and the cost is that the family's only ordered finding is uninterpretable within it. Two levels cannot distinguish a real horizon effect from one lucky column.

**What the gate saw that the headline hid — and what the gate itself could not see.** Three of four checks passed on the AVAX peak: it survives doubled costs, it retains 79 % out of sample, it is positive in both rising and falling regimes. So the failure mode here is *not* a cell that disintegrates in time. It is a cell that never contained information about the *selection*: the robustness gate re-examines the winner, while the search test examines the act of winning, and only the second one failed. The margin matters. The observed 1.5785 clears the null's 95th percentile by 0.052 (3.4 %). The gate's own 2× cost stress moved the same number by 0.153 — three times that margin — to 1.4255, **below** the null's q95 of 1.5265. That is not a like-for-like test (the 199 null replicates were generated at `cost_multiplier` 1.0), so it is an indicative bound rather than a measurement; but a peak whose entire excess over its null is one third of its own cost sensitivity is not a peak the gate's `passed: true` on cost was ever describing. Separately, the walk-forward's 0.793 retention is measured on roughly the ~37 trades falling in AVAX's two out-of-sample blocks (75 trades over 4 blocks), which is an approximation from the recorded counts, not a recorded figure. And the fourth check never ran: with no minute panel, the 11 bps round trip is the only cost model these 75–127-trade curves have ever seen. `passed: false` with `failed: []` is the correct verdict — a check that did not run is not a check that passed.

**PBO says the same thing in the one place it was computed.** ETH, the second-best symbol, returns PBO 0.599 — above 0.5, which per § 6 means the selection carries no information at all — with 85.7 % of splits degrading out of sample. ADA is 0.429 `SELECTION_WEAK` at 71.4 % degraded. Only AVAX comes back `SELECTION_INFORMATIVE` (0.234), and AVAX is the symbol whose peak the search test cannot separate from noise. The three PBO runs all name (80, 48) as `best_config_overall`, including on ETH whose reported best is (100, 48) — the selection is not even stable across the two procedures that examined it.

**And the cross-section does not match the payer story.** BTC is negative in 8 of 8 cells (best −0.102, worst −0.285); DOGE in 7 of 8. If forced liquidation flow is what this rule harvests, the venue's deepest liquidation book is the one place it never appears. That is an argument, not a measurement — the liquidation stream, the forced-order feed, open interest and mark price are all outside this archive, and "BTC carries the largest perpetual open interest" is knowledge from outside it too. But it is the shape of evidence a real forced-flow edge would not have.

One correction to the record the registration made about its own surface: H0019 declined to write a coupon clause on the grounds that the surface carries no funding-leg split. The surface as recorded **does** carry `funding_frac_best`, and at every best cell it lies between −0.0199 (DOGE) and +0.0142 (ADA). The coupon did not carry these curves. That is an observation about what this reporting surface can support, not a check that was run — it was not pre-registered and it is not graded as one.

## What this closes

- **The relaxation reading of the liquidation-cascade observable is answered, both unconditionally and conditionally.** H0017 measured it at 0 of 9 with no permission; H0019 measured it at 7 of 9 with one, and the peaks are SPIKE on 8 of 9 with the predicted axis flat. The answer is not "reversion never shows a positive Calmar" — it does, weakly, at a median of 0.086 on the best cell. The answer is that no positive Calmar in this family is attributable to the permission the mechanism proposed, because the permission's own strength axis shows no gradient across 72 cells.
- **CLAUDE.md § 7b's family is now exhausted at the shapes the evaluator can express.** `cci_reversion`, `cci_breakout` and `cci_mtf` are one payer read three ways; all three have been tested, and 162 ledger rows have been spent on it. Nothing here says CCI is uninformative; it says this project's three ways of asking produced two SPIKE closures and one corner.
- **Anything that would rescue this by refining `filter_level` is dead twice over** — as a finer grid over an existing rule form (§ 6), and now empirically: 18-cell means of 0.070 / 0.044 / 0.069 / 0.025 with the loosest level highest, and all four negative once AVAX is removed. L = 200 was already dead from the H0018 review (18 of 36 cells `no_trades_fired`); L = 120 is now dead as a *location* — lowest mean of the four, and its three winning symbols are the three thinnest.
- **The 1.5785 is not a foundation for depth.** It is the project's highest recorded Calmar and it is `INDISTINGUISHABLE_FROM_SEARCH` at p = 0.05, on the symbol with the shortest history on the board (30,112 bars against ETH's 37,335). Any proposal whose justification is that number is answered here.
- **The SPIKE clause has now closed two families in a row on two different axes** — H0017 along `timeframe_hours` (7 of 9), H0019 along `filter_level` (8 of 9). One payer, two independent grid directions, the same verdict: peaks that do not survive a single step. That generalisation is the entry's most transferable line.
- **Nothing here moves the stop condition, and nothing here comes near it.** Target is CAGR 1.00 at MDD ≤ 0.25, i.e. Calmar ≥ 4.0. The median symbol's best-of-8 is Calmar 0.294 (7.4 % of the bar) at CAGR 0.086 (8.6 %). The best cell on the board reaches 39 % of the target CAGR and would need 2.58× more at the same drawdown.

## What remains open

- **The continuation half at its corner.** H0017 recorded `cci_breakout` at `calmar > 0` on 6 of 9 symbols at `timeframe_hours = 2` with no liquidations, and closed it on shape, not on level. Nothing in H0019 re-tests it. It is the same payer, so it is not open as a fresh mechanism — it is open as an unreplicated corner, and unreplicated corners are what clause 4 exists to distrust.
- **The slow-candle horizon, which is the one live axis this failure does not touch.** f = 48 beats f = 24 by 23-of-36 versus 13-of-36 positives and +0.132 versus −0.027 in mean Calmar, across every symbol but LTC. It might survive because it is the largest effect on the surface and the only one that is consistent across nine symbols rather than concentrated in one. It might equally be a single lucky column: with two levels there is no step either side, no shape diagnostic (the recorded diagnostics read `filter_level` exclusively — that is why BNB, LTC and XRP show `n_neighbours = 1`), and the registration declared in advance it would not claim this axis. Deciding it needs three or more ordinal live levels, which requires re-deriving `filter_lookback_days` alongside them: `_period_bars(20.0, 72.0)` is 7 candles, which is why 72 h was dropped here.
- **The asymmetry, still never tested.** The payer's sharpest fingerprint is that a liquidated short must **buy**. `SignalTrialConfig` has no field restricting the rule to one side, so `cci_mtf` breaks symmetry only insofar as the regime picks the side. The one-sided version of this observable has not been measured by any family.
- **Volume, still never read.** The scouted sentence is "asymmetric continuation and elevated volume". No rule in this project reads volume. Half the observable has never been looked at.
- **The ±200 extreme.** `enter_level` was fixed at 100 throughout, and readings past 200 are a strict subset of what this entered on. This is a FAIL at the band with the extreme diluted into it, and it is never a FAIL at the extreme.
- **Execution realism on this family, unmeasured.** The gate's fourth check has not run on any H0019 cell. At 19–127 trades per curve and an 11 bps modelled round trip, "adverse first" and "one fill" remain entirely untested here, and the AVAX peak's whole excess over its null (0.052 of Calmar) is smaller than the drift a doubled cost already produced.
- **Not affected:** KT-2 (leverage above 1× stays closed; leverage was 1.0 and never on the grid), KT-3, the sealed holdout, and every Track A funding family. This closure is about one Track B shape and the axis it claimed.

Proposing what comes next is the reasoning layer's job, and it happens against `reports/CYCLE_REPORT.md`, not against this post-mortem.