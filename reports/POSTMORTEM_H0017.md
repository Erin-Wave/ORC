# H0017 — `cci_forced_flow_duel` — CLOSED

| | |
|---|---|
| Track | B (signal-driven, fixed capital) |
| Registered grid | 2 rules × 5 timeframes × 9 symbols = **90 cells, all 90 filled** |
| Ledger cost | 90 rows; project N at close **6,938** |
| Primary metric | `calmar` |
| Verdict | **FAIL — closed on kill-condition clause 3 (SPIKE), 7 of 9 symbols** |
| Clauses 1 and 2 | **not met** — the family survived both of its own novel tests |
| Clause 4 | **unmeasured at the required resolution** — see below |
| Clause 5 | **not met** — the coupon did not carry the curve |
| Holdout | untouched. Nothing in this entry went near 2024-03-01. |

---

## What was claimed

The payer was the Binance USD-M risk engine's counterparty of necessity: a position past maintenance margin is closed by the venue with an immediate-or-cancel order and a clearance fee, choosing neither its price nor its timing nor its size, and the leveraged base rebuilds after every flush because leverage is the whole reason to be on a perpetual rather than in spot. This is the payer of CLAUDE.md §7b and of `reports/SCOUT.jsonl` line 4, and — unlike the six of the first eight families that rested on the funding series — it identifies the crowded holder by what happens when he is **closed**, not by what he pays every eight hours. The observable was CCI: displacement of price from its own 5-day trailing mean scaled by its own dispersion, read at ±100 on candles aggregated to 1, 2, 4, 8 and 12 hours, 1× leverage, 5-day max hold, exit at |CCI| ≤ 50, 0.25-of-margin stop, 11 bps a round trip. The registration was explicit that this is a **partial test**: the liquidation stream, the forced-order feed, open interest and the mark price are not in this archive, and a displaced price is evidence of forced flow, not a measurement of it. Its designed discriminator was the **duel**: the scouted sentence has two halves — "asymmetric continuation and elevated volume, followed by relaxation once the compulsory buy flow is exhausted" — continuation is `cci_breakout`, relaxation is `cci_reversion`, one payer cannot pay both at one horizon, and the informative object was to be their disagreement along the horizon axis rather than either rule's number.

## What happened

The whole grid, `calmar`, both rules, all nine symbols. No cell raised `UnsupportedConfig`; the pre-registered `n_trades ≥ 20` floor never bound (smallest best-cell trade count was 313), so the family is **closed, not UNMEASURABLE**.

| symbol | bo 1h | bo 2h | bo 4h | bo 8h | bo 12h | rev 1h | rev 2h | rev 4h | rev 8h | rev 12h |
|---|---|---|---|---|---|---|---|---|---|---|
| ADAUSDT | −0.051 | −0.071 | **0.079** | 0.046 | −0.210 | −0.721 | −0.633 | −0.657 | −0.518 | −0.466 |
| AVAXUSDT | 0.585 | 0.644 | 0.405 | **0.808** | 0.715 | −0.890 | −0.888 | −0.854 | −0.853 | −0.855 |
| BNBUSDT | −0.277 | 0.102 | **0.331** | 0.141 | −0.295 | −0.608 | −0.674 | −0.666 | −0.579 | −0.391 |
| BTCUSDT | **0.265** | 0.136 | −0.127 | 0.017 | −0.078 | −0.572 | −0.549 | −0.440 | −0.453 | −0.421 |
| DOGEUSDT | 2.159 | **3.006** | 0.929 | 1.885 | 0.315 | −0.853 | −0.868 | −0.796 | −0.776 | −0.799 |
| ETHUSDT | **−0.033** | −0.067 | −0.071 | −0.277 | −0.283 | −0.660 | −0.609 | −0.613 | −0.541 | −0.555 |
| LTCUSDT | −0.454 | −0.471 | −0.433 | −0.389 | −0.408 | −0.357 | −0.341 | **−0.341** | −0.353 | −0.367 |
| SOLUSDT | 0.269 | 0.336 | **1.170** | −0.113 | −0.389 | −0.776 | −0.759 | −0.836 | −0.752 | −0.588 |
| XRPUSDT | 0.077 | **0.218** | −0.058 | 0.070 | −0.217 | −0.757 | −0.753 | −0.595 | −0.643 | −0.469 |

**24 of 90 cells are positive and every one of them is `cci_breakout`.** All 45 `cci_reversion` cells are negative; the best of them is LTC at 4h, −0.341. Mean calmar across the 45 continuation cells is **+0.221**, across the 45 relaxation cells **−0.632**.

Clause 1's bar (C > 0 on ≥5 of 9, Lq = 0 on all nine) is met by `cci_breakout` at **four of five timeframes**: t=1 (5/9), t=2 (6/9), t=4 (5/9), t=8 (6/9); t=12 reaches only 2/9. Clause 1 therefore **does not close the family**. Its liquidation half is uninformative by construction — at leverage 1.0 with a 0.25-of-margin stop nothing can liquidate, and `n_liquidating_configs: 0` across all 30 cells of the three PBO-measured symbols confirms it. Clause 2 **also does not close it**: at every t where breakout meets the bar, reversion is positive on 0 of 9. The duel resolved cleanly in favour of continuation.

Now the disqualifiers, attached to every headline.

| symbol | best cell | calmar | CAGR | MDD | Sharpe | shape | plateau ratio | `n_trades` | `funding_frac` | PBO |
|---|---|---|---|---|---|---|---|---|---|---|
| DOGEUSDT | bo 2h | **3.006** | 2.098 | 0.698 | 0.979 | **SPIKE** | 0.514 | 444 | −9.433 | 0.103 |
| SOLUSDT | bo 4h | **1.170** | 0.709 | 0.606 | 0.523 | **SPIKE** | 0.096 | 357 | −0.566 | 0.091 |
| AVAXUSDT | bo 8h | 0.808 | 0.588 | 0.729 | 0.449 | **SPIKE** | 0.694 | 313 | −0.903 | 0.028 |
| BNBUSDT | bo 4h | 0.331 | 0.241 | 0.730 | 0.313 | **SPIKE** | 0.367 | 436 | −0.476 | not run |
| BTCUSDT | bo 1h | 0.265 | 0.174 | 0.656 | 0.310 | **SPIKE** (1 neighbour, axis edge) | 0.515 | 621 | −0.519 | not run |
| XRPUSDT | bo 2h | 0.218 | 0.169 | 0.776 | 0.182 | **SPIKE** | 0.044 | 501 | −1.075 | not run |
| ADAUSDT | bo 4h | 0.079 | 0.054 | 0.683 | 0.065 | **SPIKE** | −0.160 | 428 | −0.588 | not run |
| ETHUSDT | bo 1h | −0.033 | −0.027 | 0.822 | −0.038 | unmeasurable (peak ≤ 0) | — | 571 | −0.293 | not run |
| LTCUSDT | rev 4h | −0.341 | −0.302 | 0.886 | −0.425 | unmeasurable (peak ≤ 0) | — | 444 | +0.189 | not run |

**Clause 3 fires: SPIKE on 7 of 9, against a threshold of 5.** The two non-SPIKE symbols are the two whose peak is not positive at all.

Two path-count corrections belong next to those numbers. The surface's `independent_paths_best` (313–621) is the **trade count**, and the pre-registration asserted that on Track B `effective_independent_paths` *is* `n_trades`. CLAUDE.md §4 does not say that: the count comes from symbols and non-overlapping time blocks. Under §4 this family is **9 symbols × 4 walk-forward blocks = 36 experiments**, and any single symbol's curve is **4**, not 444. The `T ≥ 20` floor was a reasonable floor; it was not a path count.

Search test, on the two strongest symbols only — DOGE observed 3.006 against its own block-bootstrap null (199 draws, 24-bar blocks, same 10-config search): null mean **1.401**, null q95 **4.302**, **p = 0.125**, `INDISTINGUISHABLE_FROM_SEARCH`. SOL observed 1.170 against null mean 0.450, q95 **2.074**, **p = 0.130**, same verdict. Both headline numbers sit **below the 95th percentile of what the identical search produces on shuffled price**.

Robustness gate, run on the family's largest cell (DOGE, `cci_breakout`, 2h):

- **cost** ×2.0 (22 bps round trip): 3.006 → 2.294, **passed**, 76.3 % retained.
- **walk_forward**, 4 blocks / 2 train: in-sample **79.341** → out-of-sample **1.856**, retention **0.0234**. **FAILED.**
- **regime**, 720-bar (30-day) windows: rising **+15.505**, falling **−0.220**. **FAILED.**
- **execution**: `no minute panel here; certification has to happen locally`. **Unmeasured.**

The same gate run on the same day passed H0001's walk-forward at retention 0.574. The 2.3 % is not the check being harsh.

## Why it broke

**The duel answered, and its answer was the wrong shape to be a payer.** The pre-registration named the fatal pattern as *both* halves paying at one horizon. What actually happened is that one half never pays at *any* horizon: 45 of 45 relaxation cells negative, on every symbol, at every resolution from 1 to 12 hours. A cascade that exhausts should relax, and if the exhaustion happens on any timescale this grid can resolve, the relaxation should be findable somewhere in the 1–12h band. It is nowhere. That leaves a surviving half — continuation — with no companion effect to distinguish it from ordinary trend, which is precisely what the remaining diagnostics then say it is.

**The horizon axis was chosen to be the deciding axis, and it decided against the mechanism.** "They cannot both be right at one horizon" is what put five ordinal levels on `timeframe_hours`. The horizon that pays is a different one on almost every symbol: 4h on ADA/BNB/SOL, 2h on DOGE/XRP, 1h on BTC, 8h on AVAX — and the PBO pass on AVAX ranks 12h best overall while the full-history best is 8h, disagreeing on the same axis. Each individual peak stands alone against its own neighbours: plateau ratios 0.044 (XRP), 0.096 (SOL), 0.367 (BNB), 0.514 (DOGE), 0.515 (BTC), 0.694 (AVAX), and −0.160 on ADA, where the peak of 0.079 sits on a neighbourhood averaging −0.013. A forced-flow cascade has a characteristic duration; a mechanism with a characteristic duration puts the peak in the same neighbourhood on correlated majors and leaves a plateau around it. This left seven isolated spikes at four different locations. BTC's is worse than the others in a way the shape column cannot flag: its peak is at the fast edge of the axis with a single neighbour, so its SPIKE verdict rests on one comparison and the grid cannot see whether the true peak is outside it.

**The gate saw the thing the headline could not contain: the return is a regime, not an event.** DOGE at 3.006 calmar is the family's whole case. Split its 30-day windows and it is **+15.505 rising, −0.220 falling**. `_two_sided` is symmetric by construction — the registration said so and named the absence of a one-sided field on `SignalTrialConfig` as the reason the payer's sharpest fingerprint was untestable here. The regime split closes that gap from the other side: a symmetric rule whose entire return lives in rising windows is not responding symmetrically to displacement, it is collecting a long-bias premium and reporting the two-sided wrapper. Remove DOGE and the mean of the other 40 continuation cells is **+0.041** — the family is one symbol, and that symbol carries the largest bull leg in the development window. A forced-flow response should pay on the side the liquidated party must trade in *either* market direction; this pays in whichever direction the sample spent its time going.

**Walk-forward names the same defect in the time axis.** An in-sample calmar of **79.34** is not a strategy; it is a two-block window that happened not to contain the adverse leg, and the metric's denominator collapsed. Out of sample the same cell returns 1.856 — still positive, and that is the honest part — but 2.34 % retention means the number the headline reports is a number about which blocks were selected, not about the rule.

**The search test says the level itself is inside the noise, and says it under conditions that favour the rule.** A block bootstrap with 24-bar blocks destroys structure longer than a day, which should *damage* the null for a rule that holds up to five days and profits from multi-day continuation — the null should be biased low, making the observed easier to distinguish. It still isn't: p = 0.125 on DOGE, 0.130 on SOL. (That reading of the block length is mechanics, not a measurement; the p-values are the measurement.) The two symbols tested are the two strongest; the other seven have smaller best cells and were not tested, so the inference that they would fare no better is an inference, not a result.

**PBO looks good and does not help, and it is worth saying why.** All three measured symbols return `SELECTION_INFORMATIVE` (0.028, 0.091, 0.103) — well under the 0.5 that means no information. PBO measures whether the *ranking* among configs holds up out of sample, and here it does, because there is one enormous and utterly stable rank fact: breakout beats reversion by 0.5 to 1.5 calmar on every symbol at every horizon. What PBO detected is the rule axis, not the timeframe axis, and "trend beats fade in this archive" is not the claim under test. Beside it, `degraded_fraction` is 0.623–0.746: the selected winner is worse out of sample than in sample two to three times in four.

**Clause 5 exonerates the family, and that is a real result.** The surface does not carry `gross_collected`; it carries `funding_frac`, which is negative on eight of nine best cells (−0.293 to −9.433) and positive only on LTC (+0.189), whose best cell loses anyway. Whatever the exact denominator, the sign is unambiguous: funding was a **net cost** here, heavily so on DOGE, and the price leg produced whatever positive number exists. This is the first family in the project whose positive cells are not the funding coupon wearing a different hat. Its failure is therefore informative rather than a repeat of H0002 and H0006 — it failed for a new reason.

**And clause 4 never actually ran.** The clause demanded the 5-of-9 count re-priced at 22 bps. What ran was cost stress on one cell of one symbol. That cell held (76.3 % retained), and this is the family that trades 313–621 times per curve — more than any family so far. **Cost is unmeasured, not passed**, on the family that most needed it measured. It is recorded here as unmeasured because a check that did not run is not a check that passed.

## What this closes

- **This reading of the payer is closed**: CCI displacement at the ±100 band, symmetric, 1–12h candles over a fixed 5-day measurement window, ≤5-day hold, exit at |CCI| ≤ 50, 1× leverage, on nine majors on the development window. Clause 3 fired at 7 of 9 against a threshold frozen before any of the 90 cells ran.
- **`cci_reversion` is closed harder than any clause required.** 45 of 45 cells negative, every symbol, every horizon. The "relaxation once the compulsory buy flow is exhausted" half of the scouted observable does not exist as a standalone rule anywhere in the 1–12h band at this entry level. This is the strongest single statement the family produced and it cost nothing extra to obtain.
- **The duel is spent as a discriminator.** It was registered to produce one bit — continuation or relaxation — and it produced it unambiguously. Re-asking the same disagreement at a different exit level, a finer timeframe spacing, a different `lookback_days` or a different `max_hold_days` is not a new mechanism; §6 calls that noise mining and the ledger has already paid for the answer.
- **Dead for the same reason, therefore also closed**: any Track B rule whose entry is a *symmetric* threshold on displacement-from-trailing-mean-scaled-by-trailing-dispersion, read at 1–12h, held ≤5 days, on these nine majors. RSI at 30/70, Bollinger %B at ±2σ, a z-score of close over a 5-day window — these compute the same object under different arithmetic and would inherit the same +15.5 / −0.22 regime split, because the split is a property of a symmetric displacement rule in a rising sample, not of CCI's particular normalisation. The specific finding is not "CCI is a bad indicator." It is that a symmetric displacement rule's return in this archive is a long-bias premium collected through a two-sided wrapper.
- **H0018 (`cci_mtf`) is not closed by this**, but its accounting changes. It is the third reading of the same payer, on the same symmetric `_two_sided`, on the same nine symbols; the registration's own honest arithmetic was 90 + 72 = 162 rows on one mechanism, dead together if the payer is not there. A filter timeframe changes *when* the rule may trade, not *what* it reads, so it cannot escape the regime exposure by construction. Whatever it reports must be graded against the rising/falling split explicitly, or it will re-collect the same premium and be read as a finding.

## What remains open

- **The one-sided rule.** The registration named this before any number existed: a liquidated short must **buy**, so the payer's fingerprint is asymmetric, and no field of `SignalTrialConfig` restricts a rule to one side. The regime result is now evidence *bearing* on it rather than against it — a symmetric rule earning +15.5 rising and −0.220 falling is consistent with the long leg paying and the short leg giving it back. A one-sided rule is a different rule shape, not a finer grid, so §6 permits it. But the reason it might survive is the same reason it might be this failure a second time: "long only, in a rising sample" is exactly how a long-bias premium looks once you restrict the rule to the long side. Any such attempt has to be graded on the regime split *first*, not on the headline.
- **The extreme band.** `enter_level` was fixed at 100 and ±200 is untested. The registration's statement holds verbatim and is the honest one: readings past 200 are a **subset** of what this probe entered on, so a cascade at the extreme did contribute here, diluted by ordinary band-crossings. This is a FAIL at the band with the extreme diluted into it, **never a FAIL at the extreme**. A rule firing 313–621 times over the development window is not selecting rare events, and a cascade is a rare event. At ±200 the trade count falls and the `T ≥ 20` floor stops being decorative — which is itself the reason the extreme is worth a look and the reason it may come back UNMEASURABLE.
- **Volume.** "Elevated volume" is the other half of the scouted sentence and no rule in this family reads it. It is the half that could separate forced flow from ordinary aggressive trading, which is the exact ambiguity that makes any CCI result a partial test. Entirely untested here.
- **Execution and cost, unanswered.** `execution: no minute panel here` and clause 4's nine-symbol re-price never ran. This family trades more than any predecessor, and the fast end of its axis — where four of five clause-1-passing timeframes sit — is where 11 bps a round trip is paid. If a later reading of this payer clears its own kill condition, this is the check that runs before anything else, because it is the one the current evidence cannot speak to at all.
- **The forced-flow payer itself is not closed.** §7b already says CCI is the observable this archive can reach, not the mechanism. What is closed is one observable's reading of the payer, at one band, symmetric, on nine majors. The liquidation stream, the forced-order feed, open interest and the mark price are still absent, and nothing measured here says the payer is not there — only that a symmetric ±100 displacement rule cannot find him without also collecting a trend premium that dominates whatever he pays.

*Not open: a finer grid over `timeframe_hours`, `exit_level`, `lookback_days` or `max_hold_days` on this shape.*