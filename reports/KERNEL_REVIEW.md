# Kernel review

Written 2026-09-02T13:16:30.401651+00:00. Confidence high. 50 finding(s) over 54 file(s) read.

## HIGH — orc/eval/signal.py:162

**The liquidation level is computed once from the entry wallet and never revisited, so funding debited during the trade never moves it and a position whose margin has been eaten by funding is never margin-checked again.**

- Trigger: capital=10_000, leverage=10, SHORT filled at 100.0 on a flat series, funding_rate=-0.0010 on every 8th bar for 300 bars. The trade pays 3,700 of funding, leaving a 6,300 wallet, but `liq` stays frozen at 109.502 where liquidation_level(SHORT, 6300, 1000, 100, BTC_LIKE) = 105.821. A bar with high=107 is liquidated on the exchange and is not liquidated here; the run continues and books whatever the price does next.
- Why it is silent: `adverse >= liq` simply never fires, so no branch is taken and no exception is raised. The trade closes on its ordinary signal exit with an arithmetically consistent gross/funding/pnl, and n_liquidations and liquidation_rate come back 0 — the exact figures KT-2 reads to decide whether a leverage setting is survivable.


## HIGH — orc/eval/signal.py:219

**`cash = max(cash + pnl, 0.0)` (with the matching `np.maximum(..., 0.0)` on the path at line 217) absorbs a loss larger than the wallet into a zero instead of a wipeout, so a trade that is destroyed by funding rather than by price is recorded as an ordinary signal exit and, if the funding regime flips back, the position carries negative equity through the middle of the trade and recovers.**

- Trigger: Two cases, both on a flat close=high=low=100.0 series so no price move can trigger anything. (a) capital=10_000, leverage=10, SHORT, funding_rate=-0.0060 on every 8th bar of 300: trade reason 'signal', n_liquidations 0, trade pnl -22,200 against a 10,000 wallet, equity_after 0.0, funding_frac_of_capital -2.22 — a bill 222% of capital the account never had. (b) same but funding_rate=-0.0060 on bars 8..200 step 8 then +0.0080 after: true mark equity reaches -4,400 and stays below zero for 104 bars, n_liquidations 0, the trade is scored a win, final_equity 15,600, total_return +56%.
- Why it is silent: The clamp is what a wipeout is supposed to look like, so nothing distinguishes 'lost exactly the wallet' from 'lost twice the wallet'. cagr, total_return, win_rate and liquidation_rate all come out finite and plausible; only max_drawdown (exactly 1.0) and a nan sharpe hint at it, and a curve that recovers to +56% reads as a strategy that survived a bad patch. sum(t['pnl']) = -22,200 while the curve moved -10,000, so the trade log does not reconcile with the equity curve and neither one errors.


## HIGH — orc/eval/signal.py:237

**`funding_collected` sums the `funding` field of every trade including liquidated ones, but line 212 sets `pnl = -cash` on liquidation and discards that funding, so the reported funding income was never credited to any wallet.**

- Trigger: capital=10_000, leverage=10, SHORT filled at 100.0; funding_rate=+0.0020 on bars 8..150 step 8; close/high jump to 112.0 at bar 150 (past the 109.502 liquidation level). Result: reason 'liquidation', final_equity 0.0, funding recorded 3,600, funding_collected 3,600, and the runner's funding_frac_of_capital = 0.36 — 'collected 36% of capital in funding' on an account that ended at zero, numerically the mirror image of KT-1's 36% funding tax and exactly the number Track B's first family exists to find.
- Why it is silent: The 3,600 is a correct sum of real per-bar accruals, so it passes any sanity check on its own magnitude. It is reported in a different key from the equity curve, and nothing in run_signals or run_signal_trial cross-foots funding_collected against final_equity, so the contradiction never meets itself.


## HIGH — orc/eval/simulate.py:133

**A single non-finite value anywhere in `funding_rate` propagates into `wallet` and therefore into the margin balance, and because `NaN <= maintenance_margin` is False, `is_liquidated` returns False forever after: every path whose window touches that bar is reported as a survivor and `liquidation_rate` — the only number KT-2 reads — comes back as a clean, finite, understated float while nothing anywhere raises.**

- Trigger: Any NaN/null in the `funding_rate` column of `facts/funding/<SYM>.parquet`. `funding_rate_per_bar` does `np.add.at(out, pos[ok], rate[ok])` with no finiteness filter, `panel.load` checks bar continuity but never finiteness, and `simulate` line 88 accepts the array as given. Reproduced: close=[100,100,55,55,55,55], low=[100,100,49,55,55,55], starts=[0,1,2,3], SimSpec(contribution=100, stride_bars=1, n_contributions=3, hold_bars=2, leverage=2, zero fees). With funding all zero: liquidation_rate 0.750, liquidated [F,T,T,T], tm [1,0,0,0]. With one element set to NaN one bar before the crash: liquidation_rate 0.000, liquidated [F,F,F,F]. (The 430 funding parquets currently in facts/ are clean, so this is latent, not live — but no guard stands between a vendor file and the number.)
- Why it is silent: The wipeout shows up as NaN only in the array-valued outputs (terminal_multiple, max_dd_total), which runner.py reduces with np.quantile and which surface_from_ledger then skips via nanargmax. `liquidation_rate` is `float(liquidated.mean())` over a bool array, so it is always a well-formed number in [0,1]; the NaN is laundered into 0.0, and kt2_martingale's `closed = liquidation_rate > MAX_ACCEPTABLE_LIQUIDATION_RATE` reads that as 'the leverage was survivable'. Prices cannot carry NaN (build_panel filters `close > 0`, which is False for NaN), so the funding array is the unguarded door.


## HIGH — orc/ledger/trials.py:78

**The code_hash roots cover orc/kernel, orc/eval, orc/orchestrator/runner.py and orc/facts/panel.py but not orc/orchestrator/spec.py, which is where the fee and slippage actually applied to a trial (effective_fee_bps, effective_slippage_bps), the evaluator routing (uses_analytic) and the grid expansion are defined.**

- Trigger: Verified by running it: edit TrialConfig.effective_fee_bps in orc/orchestrator/spec.py (e.g. `self.fee_bps * self.cost_multiplier` -> `* 2.0`) and code_hash() returns the identical digest 4c62e90e1f0ad6f7 before and after. Re-run any already-recorded hypothesis: every metric changes, but config_hash is unchanged (to_dict stores fee_bps, slippage_bps and cost_multiplier as raw fields, never their product), panel_hash is unchanged, evaluator is unchanged, so the UNIQUE key matches.
- Why it is silent: INSERT OR IGNORE discards the corrected row and run_hypothesis prints `evaluated 972, new 0`, which reads as correct deduplication rather than as a correction thrown away. This is verbatim the failure the docstring at lines 73-77 says it fixed for orc/orchestrator/runner.py; the same hole is still open one module over.


## HIGH — orc/orchestrator/surface.py:129

**The winning cell of a surface is chosen by `np.nanargmax` over raw `tm_q05`, a metric section 4 forbids comparing between cells that hold for different lengths of time, so the argmax is decided mostly by which cell holds longest (or, when long horizons lose, by which holds shortest) rather than by which rule is better.**

- Trigger: H0001 as registered (`n_contributions [52,104,156]` x `stride_days [1,7,30]`, horizons 51d..4650d in one grid). BTCUSDT: the cell (52, 30d, horizon 1530d) reports tm_q05 2.0510 and wins over (156, 7d, horizon 1085d) at 0.9200. ADAUSDT: the winner is (52, 1d, horizon 51d) at tm_q05 0.7677 while its `mwrr_q05_best` is -0.98/yr, beating the 1085d cell at 0.5958 whose annualised return is far better. The same `best_value` then sets `ranked`, i.e. which symbols get a PBO (ranked[:3]) and a search test (ranked[:2]), and is the number verdict.py applies BREAK_EVEN to; `_span`'s `effective_independent_paths = span/horizon + 1` also rewards the short-horizon winner (ADAUSDT 29.23 paths), so both gates line up behind the same horizon artefact.
- Why it is silent: tm_q05 is a real, correctly computed number for each cell; only the comparison between cells is undefined. The report shows a plausible ordering and even carries `horizon_days_best` beside it, so the ranking reads as a result rather than as a horizon sort. pbo_for_hypothesis (lines 213-232) explicitly implements the horizon guard for its own columns, which makes the two code paths disagree about whether cross-horizon comparison is allowed.


## HIGH — orc/orchestrator/surface.py:141

**`plateau_score` is handed the raw cross-horizon `tm_q05` grid, so the neighbour/peak ratio that decides SPIKE vs PLATEAU divides a long-horizon peak by shorter-horizon neighbours and measures holding time instead of parameter sensitivity.**

- Trigger: H0001/BTCUSDT on disk: peak 2.0510 at (52 contributions, 30d stride, horizon 1530d); the only non-NaN neighbour is 0.5843 at (52, 7d, horizon 357d) — a 4.3x shorter holding period — giving plateau_ratio 0.2849 and the label SPIKE from `n_neighbours: 1`. The bias runs both ways: on values 52->0.90, 104->0.50, 156->0.95 along `n_contributions` (where the horizon grows toward the peak) the ratio would be inflated and the cell labelled PLATEAU, which is the strongest structural check in the project clearing on a horizon difference.
- Why it is silent: The ratio is a finite number between 0 and 1 and the label is one of the three legitimate ones, so a wrongly-labelled surface is indistinguishable from a correctly-labelled one. verdict.py only asks whether `shape` is absent or in SPIKE_SHAPES; it never checks `n_neighbours` or `cells_filled` (12 of 18 on every H0001 symbol), so a label resting on one neighbour of a different horizon carries the same weight as a full neighbourhood.


## HIGH — orc/orchestrator/surface.py:403

**The Track A search-test null re-runs only the unconditional, unfunded, closed-form shape — `score()` builds an AnalyticSpec from contribution/stride/n_contributions/hold and calls `evaluate(close, spec)` with no funding — silently discarding `gate`, `leverage`, `take_profit`, `stop_loss` and `include_funding`, so the null carries neither the width nor the mechanism of the search that produced the observed number.**

- Trigger: H0007 (`dislocation_gated_dca`, grid = gate ['none','dip:0.10:7','dip:0.20:30'] x include_funding [True,False]) as registered: all 6 configurations per symbol collapse to one distinct AnalyticSpec (100.0, 168, 52, 0, 4.5, 1.0) — verified — so the null distribution is best-of-1 while the result reports `n_configs: 6`, and the gate the family exists to test is never applied to a synthetic path. The observed side is worse: BNBUSDT's `observed_best` 0.8095 came from the simulator with the dip gate and funding on, while the null is closed-form, ungated and unfunded. Best-of-1 is stochastically below best-of-6, so `p_value` is systematically too small and `survives_search` — the last disqualifier in verdict.py — can clear on it. (On H0007 the p-values were 0.33 and 0.77, so this did not flip that family's verdict; the bias is present and unflagged.)
- Why it is silent: `best_of_g` derives the null's search width entirely from what `score_grid` varies and takes `n_configs` as a label it only reports, so a collapsed grid produces a full 199-path null, a finite p-value, a `status: ok` and a `verdict` string that all look like a measurement of the registered grid.


## HIGH — orc/holdout.py:140

**`openings_used()` derives the spend count from `len()` of the log's lines instead of from the `"opening"` ordinal each record already carries, so a log that has lost or been edited to drop any line silently restores openings and re-issues an ordinal that is already spent.**

- Trigger: Verified by execution: patch TOKEN_FILE/LOG_FILE to a tmp dir, run `open_final_test({}, "")` three times (ordinals 1,2,3), then rewrite the log with lines 1 and 3 only. `openings_used()` returns 2 while the surviving records read `"opening": 1` and `"opening": 3`. Writing the token once more and calling `open_final_test` a fourth time succeeds and logs `{"opening": 3, "of": 3}` — two records now both claim to be opening 3, and four real openings have happened under a cap of three. The same happens without any hand editing if the file is restored from a backup taken between two openings, or if a crash truncates the last line (that line is then dropped by the `if line.strip()` filter in `_openings()`).
- Why it is silent: Nothing compares the line count to the ordinals the records themselves state, and `open_final_test` never checks that the ordinal it is about to write is unused. The extra opening returns a normal record dict with a plausible `"opening": 3, "of": 3`, and `scripts/status.py` prints `3/3 openings used` — exactly what a correctly spent project looks like.


## HIGH — orc/holdout.py:79

**The only gated door has no sealed-only read: the sole permitted call inside `final_test()` is `panel.load(development_only=False)`, which returns development *and* sealed bars concatenated, so a final-test metric is computed mostly on the data the candidate was selected on and is filed as the out-of-sample result.**

- Trigger: Verified on the local archive: `panel.load("BTCUSDT", "1h", development_only=False)` returns 60,748 bars spanning 2019-09-08 to 2026-08-14, of which 39,243 (64.6 %) are before the 2024-03-01 seal and only 21,505 are sealed. Inside `with holdout.final_test({"id": "H0002"}, "final")`, evaluating a DCA or signal rule on that panel yields a `tm_q05` / CAGR whose denominator is two-thirds in-sample history. There is no `sealed_only=True` path and no helper that returns the sealed span through the gate; `holdout_state="SEALED_INCLUDED"` is written to the ledger (orc/ledger/trials.py:41) but no consumer anywhere branches on it.
- Why it is silent: The number is a well-formed metric over a longer, mostly-in-sample window, so it comes out looking *better* than a true holdout figure and carries no marker that would let a reader tell. The one irreversible measurement the whole design exists to protect is spent on a quantity that is not an out-of-sample measurement at all.


## MEDIUM — orc/eval/signal.py:167

**When there is no exit signal the code substitutes `sig_exit = n - 2` and when `max_hold_bars` binds it shrinks `b` at line 170, but both paths keep `_PRIORITY['signal']` and `reason = 'signal'`, so a position force-closed at the end of the panel or capped by max-hold is logged as having exited on its own rule.**

- Trigger: 40 flat bars, entry[5] = -1, exit_ all False. With max_hold_bars=None the trade comes back {entry_bar 6, exit_bar 39, bars_held 33, reason 'signal'} — exit_bar is n-1, the last bar in the panel. With max_hold_bars=3 it comes back {entry_bar 6, exit_bar 9, bars_held 3, reason 'signal'}. A carry rule held through a persistent positive-funding regime to the seal therefore reports 100% signal exits while its exit rule was never exercised once.
- Why it is silent: It produces a complete, correctly-priced trade — the mark-to-market close at bar n-1 is a real price — so every number attached to it is right. Only the attribution is wrong, and Track B's defining claim in the constitution is a rule that 'exits on its own signal'; the trade log is the only place that claim could be checked and it always agrees.


## MEDIUM — orc/eval/analytic.py:133

**The funding window is `W[t_j] - W[ends+1]`, which charges the settlement sitting on the deposit bar itself even though the deposit fills at `close[t_j]` and a settlement is stamped at its bar's open — the same off-by-one that signal.py:210 deliberately excludes (`flow_cum[a+1]`, with a comment explaining why); `lump_sum_reference` line 184 repeats it on the full notional.**

- Trigger: N=3360 bars flat at 100.0, funding_flow from fr[0::8]=5e-4, AnalyticSpec(stride_bars=168, n_contributions=15, fees 0). Because 168 % 8 == 0 a start offset lands either every deposit or no deposit on a settlement bar: starts with s%8==0 report funding_paid 111.000, starts with s%8==1 report 110.250. 12.5% of the ensemble carries a spurious 0.75 USDT (5 bp of the 1,500 contributed) and tm_q05 moves 0.9260 -> 0.9265. lump_sum_reference on the same inputs shows 221.25 vs 220.50.
- Why it is silent: simulate.py step 4 charges funding after step 3's deployment, so it shares the convention exactly; test_analytic_matches_simulator_with_funding (stride 24, settlements every 8 — again a multiple) asserts the two agree to 1e-10 and therefore locks the off-by-one in rather than catching it. The resulting bias is one settlement per deposit, far too small to look like corruption, and it is correlated with the start offset so it shows up as ensemble structure rather than as a wrong total.


## MEDIUM — orc/eval/simulate.py:184

**Take-profit and stop-loss are tested against `pnl` built from the bar CLOSE, while liquidation on the same bar is tested against the bar LOW; a stop that was breached intrabar is never taken and the path is allowed to recover.**

- Trigger: close=[100,100,100,100,100], low=[100,60,100,100,100], starts=[0], SimSpec(contribution=100, stride_bars=1, n_contributions=1, hold_bars=4, leverage=1, zero fees, stop_loss=0.2). The account was 40% underwater at bar 1's low against a 20% stop; the run returns exit_reason=0 (EXIT_HORIZON), exit_bar=4, terminal_multiple=1.0000. orc/eval/signal.py:180 does this correctly for the same mechanism (`adverse = low[scan] if side == LONG else high[scan]`), so the two evaluators disagree on identical inputs.
- Why it is silent: The module docstring (lines 20-22) argues explicitly that the low is the true intrabar extreme and that anything else 'hides intrabar wipeouts', and applies that reasoning only to liquidation. The stop simply never fires, so there is no missing field or NaN — the cell reports a stop-loss variant that outperforms its own stop. No registered Track A hypothesis sets stop_loss today (H0007 fixes it to None; the live stop grids in H0002/H0006 are Track B and go through signal.py), so the wrong number is not in the ledger yet — the next Track A rule with a stop gets it.


## MEDIUM — orc/kernel/inference.py:247

**`plateau_score` drops NaN neighbours from the mean instead of treating them as unmeasured, so a mostly-unevaluated grid emits the label PLATEAU — the strongest shape verdict the scale has — from a single surviving comparison.**

- Trigger: g = np.full((5,5), np.nan); g[2,2]=1.00; g[2,3]=0.97; plateau_score(g, [True, True]) returns {'peak': 1.0, 'plateau_ratio': 0.97, 'n_neighbours': 1, 'shape': 'PLATEAU'} from 2 of 25 cells. surface_from_ledger builds exactly this array — `grid = np.full(shape, np.nan)` filled only from ledger rows — so any cell the runner rejected as UnsupportedConfig, or any interrupted run, leaves NaN holes around the peak.
- Why it is silent: verdict.disqualifiers is built on the principle that 'a check that did not run is not a check that passed' and fires 'shape unmeasured' only when `shape` is None. A one-neighbour PLATEAU is not None, so the disqualifier is silently cleared by the one check the module exists to perform. `n_neighbours` and `cells_filled` are reported but nothing conditions on them.


## MEDIUM — orc/kernel/inference.py:182

**`best_of_g_pvalue` filters the null distribution for finiteness (line 179) but never checks `observed_best`; a NaN or +inf observed value makes `nb >= observed_best` all-False and yields the smallest p-value the test can produce.**

- Trigger: best_of_g_pvalue(float('nan'), rng.normal(1.0, 0.2, 199), 64) returns p_value=0.00500, n_null=199, verdict 'SURVIVES_SEARCH'. float('inf') gives the same. search_test.best_of_g applies `np.isfinite(v)` to every synthetic score but passes `observed_best` straight through, and surface.write_report feeds it `surfaces[sym]['best_value']` with no finiteness test either.
- Why it is silent: p = (0 + 1)/(199 + 1) is arithmetically identical to the answer for a real best that beat every synthetic, so the report shows a strong, well-formed p-value and `survives_search: true`, and verdict.disqualifiers accepts it. The NaN survives only in `observed_best`, a field nobody gates on. Current callers cannot reach it (nanargmax skips NaN cells and metrics_fc.calmar already guards zero-drawdown to NaN), so this is a latent asymmetry between two halves of one function rather than a live wrong number.


## MEDIUM — orc/ledger/trials.py:87

**A root that does not exist contributes nothing to code_hash and raises nothing: `root.is_file()` is False for a missing path, and `Path('.../missing.py').rglob('*.py')` returns an empty list rather than an error.**

- Trigger: Verified: `Path('orc/orchestrator/does_not_exist.py').rglob('*.py')` -> `[]`. Rename or move orc/orchestrator/runner.py, or ship a cloud bundle without orc/eval/, and code_hash() still returns a well-formed 64-hex digest computed over a silently smaller file set.
- Why it is silent: The function's only output is a hash, so a hash over four files and a hash over three are indistinguishable. Nothing asserts the file count, so the guarantee that a kernel change starts a new trial can be silently withdrawn for a whole module by a rename, and a local and a remote checkout with different file sets would compute different hashes and never dedupe against each other.


## MEDIUM — orc/ledger/trials.py:131

**_migrate copies rows with INSERT OR IGNORE and then DROPs trials_legacy without ever comparing the two counts, and because executescript() commits before each script the rename, the copy and the drop are three separate transactions with no rollback between them.**

- Trigger: Verified by construction: create a legacy ledger with 5 rows whose UNIQUE key lacks code_hash, run only the first executescript (the DROP TRIGGER / ALTER TABLE ... RENAME TO trials_legacy step), then reopen with Ledger(path). Result: total_trials() returns 0, the 5 rows sit orphaned in trials_legacy, and because the fresh `trials` table's SQL now contains 'code_hash)' the guard at line 121 returns early so _migrate never runs again.
- Why it is silent: The ledger opens cleanly, the append-only triggers are recreated, and every query works. N — the denominator of every multiple-testing correction in the project — reads 0 rather than raising, so the next correction is trivially passed. The docstring's promise that this 'neither drops nor edits a single row' is checked by nothing.


## MEDIUM — orc/kernel/metrics_cf.py:87

**mwrr_equal_interval converts non-finite terminal values into finite, in-bracket rates: NaN falls through every guard to the bracket floor and inf saturates at the bracket ceiling.**

- Trigger: Verified: `mwrr_equal_interval(100.0, 156, 7/365, np.array([inf, nan, 1e13, 15600.0]), horizon_years=156*7/365)` returns `[1000.0, -0.9999, 1000.0, ~0.0]`. For NaN: np.sign(nan) is nan so `outside` is False, `go_right` is False every iteration so b collapses onto a=lo, and `V <= EPS` is False for NaN. For inf: npv(lo) and npv(hi) are both +inf, so the saturation branch returns hi exactly.
- Why it is silent: A path whose terminal value is undefined is written to the ledger as an IRR of -99.99 %, indistinguishable from a genuine near-wipeout, and an overflowed path as +100,000 % annualised, indistinguishable from the legitimate saturation at 1e13. The conversion happens before start_date_profile, which does filter non-finite values, ever sees the array — so the two functions in this same file disagree about NaN and the one that fabricates a number wins.


## MEDIUM — orc/kernel/metrics_cf.py:170

**start_date_profile silently discards non-finite paths and then reports the reduced survivor count as `n`, so every quantile it returns — including tm_q05, the PRIMARY_METRIC — is conditional on survival.**

- Trigger: Verified: `start_date_profile(np.array([nan]*500 + [2.0]*500))` returns `{'q05': 2.0, ..., 'n': 500, 'worst': 2.0}`. Nothing compares this `n` against the trial's own path count: runner.py records n_starts from the evaluator in a separate ledger column, so a row reading `n_starts: 1000, tm_n: 500` is written with no complaint from either side.
- Why it is silent: The returned dict is shaped exactly like a healthy one and the quantiles are perfectly plausible — they are just quantiles of the surviving half. The bias runs upward, in the left tail, which is the one place section 4 says the decision lives.


## MEDIUM — orc/kernel/metrics_fc.py:73

**sharpe is the only one of the four Track B ratios that survives a non-finite value in the equity curve, and it survives by deleting the returns it cannot read (`r = r[np.isfinite(r)]`) while still annualising by the full bars_per_year.**

- Trigger: Verified: an 8760-bar equity curve with a single `equity[4000] = np.nan` gives `summary(...)` -> `{'cagr': 0.3578, 'max_drawdown': nan, 'calmar': nan, 'sharpe': 1.6184, 'total_return': 0.3577, 'bars': 8760}`. The `np.any(equity <= 0.0)` guard at line 69 does not catch NaN (nan <= 0 is False), so control reaches the diff, and the two NaN returns are simply dropped.
- Why it is silent: The row records a strategy with a 1.62 Sharpe and a 36 % CAGR whose drawdown 'could not be computed' — the check that failed is reported as nan while the metric that quietly worked around the same corruption is reported as a result. calmar being nan also means json_extract returns SQL NULL for it, so the cell is filtered out of Ledger.best by `WHERE ... IS NOT NULL` and disappears from selection while its Sharpe stays in the surface report.


## MEDIUM — orc/facts/panel.py:124

**A missing funding parquet produces a Panel whose funding_rate is all zeros and funding_settled all False — identical to a symbol that genuinely pays no funding — and run_dca_trial never calls has_funding() before using it.**

- Trigger: Build a panel for a symbol and run a Track A hypothesis with include_funding: true before fetching its funding history (build_panel and `python -m orc.facts.fetch_vision <SYM>` are separate commands, so this is the state of every newly built symbol until fetch is run for it). runner.py:163 takes `flow = p.funding_flow` = close * 0 with no guard; run_signal_trial is protected by has_funding() at line 99, run_dca_trial is not. All 253 panels currently in facts/panel_1h/ do have a funding file, so this is armed rather than currently firing.
- Why it is silent: The trial records normally with `include_funding: true` in its config_json, `funding_frac_q50: 0.0` in its metrics, and a tm_q05 with the structural funding tax removed — the exact 36 %-of-contributed-capital drag that KT-1 closed long-side perp DCA on. Zero funding paid is a legitimate reading, so nothing distinguishes 'this symbol collected nothing' from 'nobody fetched the data'.


## MEDIUM — orc/facts/panel.py:116

**The bar-index-as-clock check is one-sided: `missing = 1 - height/expected` can only ever detect too few bars, so duplicated timestamps make `missing` negative and pass, and nothing verifies that ts is sorted or aligned to the clock grid even though `expected` is computed from ts[-1] - ts[0].**

- Trigger: Verified: write `pl.concat([src, src]).sort('ts')` for BTCUSDT to facts/panel_1h/, then panel.load('DUPUSDT','1h'). The check passes (missing ~ -1.0), and p.bars(7) still returns 168 while 168 bars now spans 3.58 days. build_panel does dedupe on ts, so the trigger is any panel parquet reaching facts/ by another route — a hand-assembled file, a partially rewritten bundle, or a future writer.
- Why it is silent: load() is the designated enforcement point ('research code must not open parquet files directly'), and it returns a Panel that looks entirely normal. Every stride, horizon, lookback and hold in the project is expressed in bars via Panel.bars(), so every duration silently halves and every resulting metric is internally consistent at the wrong horizon.


## MEDIUM — orc/orchestrator/verdict.py:27

**`disqualifiers` is not the single decision point its docstring claims: the `search` argument defaults to None (which the body reads as "unmeasured"), and the `covers_reported_best` filter lives in `survivors()` rather than in `disqualifiers()`, so a second caller that builds the arguments itself gets a different verdict on the same report without any error.**

- Trigger: `scripts/status.py:87` calls `disqualifiers(s, metric, p)` with three arguments, so every cell on the status screen is disqualified with "search test unmeasured" and line 104 prints "0 cell(s) clear ..." no matter what `search_test` in the report says — while `notify.py`, going through `survivors()`, can announce the same cell as a finding. In the other direction, `status.py:74` builds its pbo map filtering only on `status == "ok"` and omits the coverage filter, so H0007/BNBUSDT (`status: ok`, `pbo: 0.167`, `covers_reported_best: false`) is shown a passing PBO for a cell the PBO never measured, which `survivors()` correctly drops.
- Why it is silent: A missing keyword argument is a legal call, and both failure directions produce a well-formed verdict line: one reads as a cell that failed a check, the other as a cell that passed one. Nothing compares the two screens, so the drift the module was written to prevent is invisible in both outputs.


## MEDIUM — orc/orchestrator/spec.py:231

**`params.update(self.fixed)` lets a key present in both `grid` and `fixed` silently override the grid axis, so the axis is enumerated in the count but never varied.**

- Trigger: A hypothesis with `grid: {"stride_days": [1.0, 7.0, 30.0], "n_contributions": [52,104,156]}` and `fixed: {"stride_days": 7.0}` — verified: `size()` returns 9, `expand()` returns 9 configs, but only 3 are distinct and every one has stride 7.0. Intake prints "9 configurations", the cycle prints "9 configurations", the ledger holds 3 rows, and the surface's stride axis has one of three levels filled. Nothing in `intake_queue` checks that grid and fixed are disjoint.
- Why it is silent: Every downstream number is correct for the configurations that ran; only the claim about which grid was explored is wrong. The surface's unexplored levels appear as NaN cells, which is the same thing an inexpressible grid point looks like, and the shape check then fails closed ("shape unmeasured") rather than complaining about the collapse.


## MEDIUM — orc/orchestrator/spec.py:195

**`size()` counts an empty grid axis as one level (`max(len(v), 1)`) while `expand()`'s `product` yields zero configurations, so the two disagree about how large a hypothesis is and a hypothesis that can produce no trials at all passes intake.**

- Trigger: A queue file with `grid: {"stride_days": [1.0,7.0,30.0], "hold_days": []}` — verified: `size()` returns 3, `expand()` returns 0, and `shape_is_measurable()` is True (the stride axis carries it), so it clears both intake gates, registers, and `run_hypothesis` records nothing while printing "0 configurations / evaluated 0, skipped 0". `write_report` then writes a report with `surfaces: {}`, no PBO and no search test.
- Why it is silent: Zero is a valid count everywhere it appears, and an empty `surfaces` dict is exactly what a family whose panels are missing also produces, so CYCLE_REPORT.md shows a registered family with no cells and no stated reason — and the size the intake ceiling was charged against was never the number of configurations that could exist.


## MEDIUM — orc/orchestrator/surface.py:85

**`provenance` accumulates the code and panel hash of every ledger row for a symbol, including the superseded rows the newest-wins rule at line 84 deliberately discarded, so `assembled_from` reports a mixed surface whenever a cell has ever been re-run.**

- Trigger: H0001/ADAUSDT has 12 rows across 6 code revisions and 4 panel revisions for the same 12 cells (verified in the ledger: trials 6, 118, 230, 1426, 6972, 11812 are the same config re-run after kernel edits). Every cell in the surface was taken from the newest revision alone, yet the report on disk carries `assembled_from: {code_revisions: 6, panel_revisions: 4}` for every symbol.
- Why it is silent: The counts are plausible integers and the failure direction is a warning that is always on, which is worse than one that is off: the field can no longer distinguish a surface genuinely assembled from two kernels — the case the comment says it exists to catch — from one that was simply re-run, so a real mix would be read as the usual noise.


## MEDIUM — orc/orchestrator/surface.py:83

**The cell key is built from the grid axes only, so `evaluator` is part of the ledger's uniqueness key but not of the surface's, and one grid can hold analytic and simulator rows chosen against each other purely by trial_id order with nothing in the report recording it.**

- Trigger: H0001's funded cells were analytic as recently as trial 11818 (`evaluator: analytic`, `n_starts: 9736`, `liquidation_rate: 0.0`, tm_q05 -0.4988 on ADAUSDT — the number spec.py's own docstring cites as impossible), and `uses_analytic` now excludes `include_funding=True`, so the next cycle writes simulate rows for exactly those cells: ~1279 daily starts with a real liquidation rate, sitting in the same grid as the unfunded analytic cells' 9736 hourly starts, compared by `nanargmax` and by `plateau_score` as if they were neighbours in one experiment.
- Why it is silent: Both rows are legitimate measurements of the same configuration and the newest simply wins, exactly as the comment intends; but `assembled_from` records code and panel revisions and not the evaluator, so a surface whose cells come from two different start ensembles and two different treatments of ruin reports the same provenance as a homogeneous one. Only `n_starts_best` hints at it, and only for the winning cell.


## MEDIUM — orc/orchestrator/spec.py:134

**`ordinal_axis` accepts any axis with three or more numeric levels without checking that they are in order, while `plateau_score` takes "one step away" from the position of a value in the JSON list, so the neighbour relation — and therefore the shape label — depends on how the grid list happened to be written.**

- Trigger: An axis written unsorted, e.g. `"n_contributions": [156, 52, 104]` (H0006's registered `enter_rate: [0.0, -0.0001]` shows grids are not written in sorted order). With cell values 52->0.90, 104->0.50, 156->0.95: written `[52,104,156]` the peak at 156 has neighbour 0.50, ratio 0.53 -> SPIKE; written `[156,52,104]` the same three numbers give the peak neighbour 0.90, ratio 0.947 -> PLATEAU. Separately, the surface.py:113-117 comment claims a None among numeric levels "is not a neighbour of anything", which nothing implements: `[null, 0.1, 0.2, 0.3]` is three numerics, so the axis is declared ordinal and the no-stop cell is averaged into the neighbour mean of the 0.1 cell.
- Why it is silent: Index adjacency is always well defined, so the ratio and the label are computed without complaint on any ordering; the report shows the axis values, but nothing compares them to the adjacency actually used, and both labels are legitimate outputs of the diagnostic.


## MEDIUM — orc/orchestrator/surface.py:392

**The three re-evaluation paths hard-code the `1h` panel (lines 178, 301, 366) and the Track B null hard-codes `BARS_PER_YEAR["1h"]`, while the ledger's number was computed on `cfg.clock`, so a hypothesis on any other clock has its PBO and its search-test null computed on different data and a different annualisation from the observed value they are compared against.**

- Trigger: A Track B hypothesis with `fixed: {"clock": "1m"}` — expressible and registerable today: 253 symbols have 1m panels and `metrics_fc.BARS_PER_YEAR` has a `1m` entry. The ledger's calmar annualises with 525,600 bars/yr; `score()` in the null annualises the same shape with 8,760, making every null CAGR (and hence null calmar) roughly 60x smaller than the observed one, so `p_value` collapses to the floor 1/200 and `survives_search` returns True. `p.bars(cfg.lookback_days)` in the same function also resolves a 21-day lookback to 504 bars instead of 30,240, so the null runs a different rule as well.
- Why it is silent: Both sides are finite, plausible ratios and the comparison produces `status: ok` with a real p-value; nothing in the result records which clock the null was run on, so a mismatched annualisation looks like an overwhelmingly significant result.


## MEDIUM — orc/orchestrator/runner.py:138

**Track B writes the trade count into `effective_independent_paths`, but section 4 says that count must come from the number of symbols and non-overlapping time blocks and "never from bar count", so verdict.py's few-paths floor is compared against a number that grows with trading frequency on a single equity curve.**

- Trigger: H0002/BTCUSDT on disk: `n_trades_best: 47` -> `independent_paths_best: 47.0`, from one rule on one symbol over one history — one path by section 4's definition. `FEW_PATHS = 5.0`, so the check clears nine times over; every H0002 cell with five or more trades clears it automatically, and the only cells it ever disqualifies are ones that barely traded (SOLUSDT at 2).
- Why it is silent: The number written is a true count of something and the comment above it honestly calls it a generous upper bound, so the report shows a plausible path count where a path count belongs; the disqualifier then reads as a check that ran and passed, when on this track it can essentially never fire.


## MEDIUM — orc/orchestrator/spec.py:273

**`load_registry` catches ValueError and TypeError per file and skips the hypothesis, so the one failure pre-registration exists to detect — `verify()` finding that a registered grid or claim was edited — removes the family from the registry instead of stopping the cycle.**

- Trigger: Edit any registered file's claim or grid (e.g. change one value in `configs/registry/H0002.json`) without touching `prereg_hash`. `verify()` raises, `load_registry` prints "registry: skipping H0002.json -- ..." and returns the other three, `daily_cycle` uses that list for `to_report`, and CYCLE_REPORT.md — the only document section 9 lets the reasoning pass read — contains no H0002 section, no kill-condition line and no trace that a family was dropped, while H0002's rows remain in the ledger and in N. A top-level key the dataclass does not accept (a hand-added `"notes"` field) produces the same silent disappearance via TypeError.
- Why it is silent: The cycle exits 0 and writes a complete-looking report; a missing family is indistinguishable from a family that was never registered, so tamper detection converts into invisibility rather than into a failure, and the family is never judged against its own kill condition.


## MEDIUM — orc/holdout.py:114

**`sealed_slice()` returns sealed bars without calling `note_sealed_read()`, so the one function in this module whose only purpose is to produce sealed data is the one entry point the permit, the log and the counter do not cover.**

- Trigger: Verified by execution with no final test open: `holdout.sealed_slice(pl.read_parquet(panel.panel_path("BTCUSDT", "1h")))` returns 21,505 rows starting 2024-03-01 00:00, while `holdout.sealed_reads_permitted()` is still False and `holdout.openings_used()` is still 0. No exception. It needs a raw `pl.read_parquet` to get an un-truncated frame, which the constitution already forbids — but because there is no sealed-only read through the gate (see the `final_test` finding), this two-line bypass is the natural thing a researcher writing a final test reaches for.
- Why it is silent: The module docstring states "the loader refuses to hand back sealed bars" outside an opening, and `panel.load(development_only=False)` does. This sibling in the same module does not, so the two paths that should agree disagree; the caller gets a normal DataFrame and every counter still reads zero.


## MEDIUM — orc/holdout.py:99

**`n_sealed_reads` counts `panel.load` calls rather than measurements, so the very thing the reads log was added to expose — one opening covering a whole grid — still logs as a couple of reads.**

- Trigger: Inside a final test, `panel.load_many(["BTCUSDT", "ETHUSDT"], development_only=False)` fires `note_sealed_read` exactly twice, and the orchestrator then reuses those two `Panel` objects across every cell (orc/orchestrator/runner.py:98 and :152 are `p = p or panel_mod.load(...)`, i.e. the panel is passed in and loaded once). A 972-cell H0002-sized grid over two symbols therefore writes `{"n_sealed_reads": 2, "sealed_reads": ["BTCUSDT/1h", "ETHUSDT/1h"]}` for 1,944 sealed measurements. Nothing records which candidate each read served either, so an opening booked for H0002 can measure H0011 and the record still names H0002.
- Why it is silent: `n_sealed_reads: 2` is a small, plausible number that reads as "two symbols, one measurement each", which is exactly what a disciplined single final test looks like. The count is proportional to how many times someone happened to call the loader, not to how many times the sealed period informed a decision — and the accompanying comment at line 82 asserts the opposite.


## MEDIUM — orc/holdout.py:133

**An absent `LOG_FILE` is treated as "never opened" rather than as unknown state, and `READS_FILE` — an independent record of the same openings — is never consulted, so the "three openings for the life of the project" counter is a single untracked local file with no integrity check and no cross-check.**

- Trigger: Verified: `ledger/FINAL_TEST_LOG.jsonl` does not exist on this machine, `git ls-files ledger` lists only `trials.sqlite`, and `.gitignore` never mentions the log — so nothing has ever committed it and nothing will create it until the first opening. `holdout.openings_used()` returns 0 and `scripts/status.py` prints `0/3 openings used`. Any fresh clone, any second working directory (both `LOG_FILE` and `READS_FILE` are pinned to `config.ORC_ROOT`, unlike `config.LEDGER_DB` which honours `$ORC_LEDGER`), or a `ledger/` restored from a backup taken before an opening resets the count to zero. If `LOG_FILE` is lost while `READS_FILE` survives, the two files disagree — `openings_used()` says 0, `READS_FILE` lists two openings — and no code path compares them.
- Why it is silent: `_openings()` returns `[]` for a missing file, which is indistinguishable from an empty one, so the failure of the durability mechanism is reported as the healthy initial state: a fresh, unspent holdout with all three measurements available.


## MEDIUM — orc/facts/fetch_vision.py:339

**The `if n >= 2` guard that bounds a settlement by the last bar's own width is skipped for a one-bar panel, so on a panel with a single development bar every sealed settlement — the entire post-seal funding history — is summed onto that bar by `searchsorted`, which is the exact defect the guard was added to fix.**

- Trigger: Verified by direct call: `funding_rate_per_bar(pl.Series("ts", np.array(["2024-02-29T23:00"], dtype="datetime64[us]")), fund)` where `fund` holds settlements at 2024-03-01 00:00 (0.001), 2024-03-01 08:00 (0.002) and 2025-01-01 (0.004) returns `funding_rate = [0.007]`, `settled = [True]`; the same call with two bars correctly returns `[0., 0.]`. The n==1 case is reachable through `panel.load`: `build_symbol` only requires `REQUIRE_DEVELOPMENT_BARS` to find at least one bar before the seal, and the missing-bar QA in orc/facts/panel.py:115 is degenerate at n==1 (`expected = (ts[-1]-ts[0])//step + 1 = 1`, so `missing = 0.0`) and passes. Any symbol whose first trade falls in the last hour before 2024-03-01 with 90 days of total history produces it. No symbol in the current archive has a development window of ≤5 bars, so the leak is latent rather than live today.
- Why it is silent: The result is a single finite float on a bar that legitimately exists in the development window. 0.007 for one hour is large but not absurd for a newly listed alt, so a carry or funding-drag statistic reads it as a real pre-seal observation of an extreme funding regime — sealed data driving a development-window number, with the panel passing every QA check on the way in.


## LOW — orc/eval/signal.py:159

**`side = int(entry[sig_bar])` is used both as a direction flag and as a P&L multiplier, and every branch tests `side == LONG` rather than `side > 0`, so any entry value outside {-1, 0, +1} silently scales the position while routing it through the short-side logic.**

- Trigger: entry[0] = 2 (not +1), leverage=1.0, close flat at 100 stepping to 110 at bar 10, stop_loss=0.10, take_profit=0.10, high[12]=130. With entry=+1 the trade is {reason 'take_profit', exit_bar 12, pnl +1000}. With entry=2 the identical series gives {reason 'stop', exit_bar 2, pnl -4000}: `adverse` becomes high instead of low, `favour` becomes low, the stop level lands at 80 which a flat high of 100 satisfies immediately, and liquidation_level takes its short branch so the level sits ~2x above the entry and can never fire on a long.
- Why it is silent: The function validates that close/high/low/entry/exit_ are the same length and that n >= 3, but never the side alphabet. int8 accepts 2 without complaint, qty stays a correct 1x quantity, and gross/funding/pnl remain internally consistent — the trade just describes a position nobody asked for. The shipped rules in signal_rules.py only emit ±1/0, so this is latent until the next rule shape is added.


## LOW — orc/eval/signal.py:139

**`funding_rate` is multiplied into `close` without any length check, so a scalar or one-element rate array broadcasts across the whole panel instead of raising.**

- Trigger: run_signals(close=200 flat bars, ..., funding_rate=np.array([1e-4])) charges 160.6 of funding on a 10,000 account — a settlement on every bar rather than every eighth, roughly 8x the true bill on an hourly panel.
- Why it is silent: numpy broadcasts a size-1 array without warning, and every other length (n-1, n+1) does raise, so the one shape that fails silently is the one that looks least like a mistake. The resulting figure is the right order of magnitude for a funding bill, and the same function raises loudly on high/low/entry/exit_ length mismatches, which makes the input look validated.


## LOW — orc/eval/signal.py:130

**The allowed-leverage check is made once against `spec.capital * spec.leverage`, but `qty` is sized from the compounding `cash` at line 161, so a run whose equity grows into a higher notional bracket keeps trading at a leverage the exchange caps lower.**

- Trigger: symbol='BTCUSDT', capital=10_000, leverage=25: notional 250,000, BTC_LIKE.leverage_at(250_000) = 100, so the check passes. After the curve compounds to cash=200,000 the notional is 5,000,000, where BTC_LIKE.leverage_at(5_000_000) = 20 — the position keeps running at 25x on an order the exchange would reject.
- Why it is silent: `allowed` is never consulted again after the constructor-time check, and the liquidation level does read the correct bracket via table.lookup, so the maintenance margin is right and only the position size is unattainable. The whole run stays arithmetically self-consistent; the divergence is between the model and the venue, and it appears only in the tail of the equity curve where the numbers are already large.


## LOW — orc/kernel/liquidation.py:70

**The BTC_LIKE bracket at the 480,000,000 cap carries cum_maint 11,098,050 where bracket continuity requires 6,348,050 + 230e6*(0.150-0.125) = 12,098,050, so maintenance margin jumps discontinuously by 1,000,000 USDT at the 230M notional boundary, and the two brackets above inherit the same 1,000,000 offset.**

- Trigger: maintenance_margin(np.array([230_000_000.0]), BTC_LIKE) = 22,401,950.00; maintenance_margin(np.array([230_001_000.0]), BTC_LIKE) = 23,402,100.00 — a 1,000,000 step for a 1,000 USDT increase in notional. Every other bracket in all three tables satisfies cum_i = cum_{i-1} + cap_{i-1}*(mmr_i - mmr_{i-1}) exactly; only this one and its two successors (59,098,050 and 209,098,050, which should be 60,098,050 and 210,098,050) do not.
- Why it is silent: maintenance_margin is a plain arithmetic expression that returns a plausible large number either way, and no test asserts bracket continuity. Unreachable at the sizes ORC actually runs — retail DCA never leaves tier 0 — but the comment at line 59-61 says the full table exists precisely 'so that capacity studies cannot silently use the wrong rate', which is what a capacity study above 230M notional would do.


## LOW — orc/eval/simulate.py:178

**A liquidated path's death bar is excluded from `bars_in_loss` and `bars_below_peak` (step 1 removes it from `act` before step 5 counts) but included in `bars_lived` (exit_bar + 1), so the single worst bar of the worst paths is missing from the numerator and present in the denominator; TP/SL exits count their exit bar, so the two exit routes disagree.**

- Trigger: close=[100,100,55,55,55,55], low=[100,100,49,55,55,55], starts=[0], SimSpec(contribution=100, stride_bars=1, n_contributions=3, hold_bars=2, leverage=2, zero fees): the path is wiped out at bar 2 having lost 100% of contributed capital, and reports exit_bar=2, bars_lived=3.0, frac_time_in_loss=0.0000, frac_time_below_peak=0.0000. The understatement is 1/(exit_bar+1), which is largest exactly for the paths that die soonest.
- Why it is silent: Both counters are integers over a positive denominator, so the ratio is always a well-formed fraction in [0,1]; runner.py records it as `frac_time_in_loss_q50`. It is the same bias the comment at lines 207-210 was written to remove — 'the paths that die earliest, the worst ones, looked the healthiest on this measure' — fixed in the denominator and left in the numerator.


## LOW — orc/eval/simulate.py:167

**Funding at bar e is charged on the quantity AFTER that bar's deployment, so capital deployed at the close of a settlement bar pays (or collects) a settlement it did not hold through; orc/eval/signal.py:210 does the opposite for the same mechanism, accruing funding only from bar a+1.**

- Trigger: Deposit bars are start + m*stride_bars, and 168 (weekly on 1h) is a multiple of 8, so whether a deposit ever coincides with a settlement is decided entirely by the panel's first-bar hour. Measured over the 251 built 1h panels: 28 of them start at an hour ≡ 0 mod 8 — ADAUSDT (2020-01-31T08:00), BNBUSDT, BCHUSDT, ETCUSDT, 1000PEPEUSDT and others — and with SIM_START_STRIDE_DAYS=1.0 every start and therefore every one of the 156 deposits lands on a settlement bar (measured hit rate 1.000). BTCUSDT starts at 19:00, so its hit rate is 0.000. On ADAUSDT the over-charge is a median 2.54 USDT, 0.016% of contributed and 0.023% of the funding bill.
- Why it is silent: The error is one settlement on one bar's worth of newly added notional, which is small against a bill that runs to tens of percent of capital, and it always lands inside `funding_paid` as an ordinary number. It is conservative for a long paying positive funding and a small free lunch in negative-funding regimes, and it makes a simulate-vs-signal cross-check of the same carry mechanism differ by a symbol-dependent constant.


## LOW — orc/eval/simulate.py:141

**On liquidation `terminal_equity` is set to 0.0 unconditionally, wiping the undeployed cash even when `undeployed_counts_as_margin=False` explicitly excluded that cash from the margin balance that decided the liquidation.**

- Trigger: close=[100,100,100,55,55,55], low=[100,100,100,44,55,55], gate=[True,False,False,False,False,False], SimSpec(contribution=100, stride_bars=1, n_contributions=3, hold_bars=2, leverage=2, zero fees, undeployed_counts_as_margin=False). 200 USDT accumulates as powder behind a closed gate and is subtracted out of `margin` at line 132, yet the run returns terminal_equity 0.0000, terminal_multiple 0.0000, max_dd_total 1.000 on invested 300.0 — the correct isolated-margin answer is 200/300 = 0.667.
- Why it is silent: Total loss is exactly what a liquidation is supposed to look like, so 0.0 and a full 1.000 drawdown read as the model working. The two halves of the flag disagree — one path honours it, the other does not — and no caller currently sets it to False, so the disagreement has never been exercised.


## LOW — orc/eval/simulate.py:254

**Both gates use a strict `>` where `>=` is correct (`elif n > lookback` here, `if n > window` at line 268), so when the series length equals the lookback the gate is returned entirely False instead of having its one evaluable bar.**

- Trigger: close = [100,99,98,97,50]; gate_below_trailing_peak(close, 0.10, 5) returns [F,F,F,F,F], while gate_below_trailing_peak(close, 0.10, 4) returns [F,F,F,F,T] — the bar at 50, half its trailing peak, is a deployment bar under a 10% dip rule and is dropped. gate_below_sma(close, 5) vs gate_below_sma(close, 4) behaves identically. sliding_window_view accepts n == lookback and produces exactly the one window the branch refuses to compute.
- Why it is silent: An all-False gate is indistinguishable from 'the rule correctly never fired': the powder simply accumulates and is returned at the horizon, so the cell reports terminal_multiple ≈ 1.0 with liquidation_rate 0.0 and no error. Realistic gate specs (dip:0.20:30 → 720 bars against ~39,000-bar panels) never approach the boundary, so it costs one bar in practice.


## LOW — orc/eval/simulate.py:63

**`horizon_bars` can go negative when `n_contributions` is 0, and nothing rejects it: the range guard at line 85 passes trivially, the loop body never runs, and the horizon exit at line 199 indexes `close[starts + H]` with a negative offset, which numpy wraps to the end of the panel.**

- Trigger: SimSpec(contribution=100, stride_bars=24, n_contributions=0) gives horizon_bars = -24. simulate(np.arange(1.,101.), same, np.array([0,5]), spec) returns without raising: exit_bar [-24,-24], terminal_multiple [0.,0.]. Nothing in orc/orchestrator/spec.py validates n_contributions >= 1, and runner.py's `starts = np.arange(0, len(p) - horizon - 1, step)` with a negative horizon generates start offsets past the end of the panel that line 85's guard then accepts, because starts.max() + H lands back inside the array.
- Why it is silent: The negative index reads real, in-range floats rather than erroring, and every path lands on terminal_equity = wallet = 0, so the cell reports terminal_multiple 0.0 across the ensemble — a catastrophic-looking but arithmetically clean result rather than a rejected config. The start-offset guard, the one line in the function whose job is to keep the ensemble inside the panel, is what the negative horizon defeats.


## LOW — orc/facts/panel.py:159

**load_many catches FileNotFoundError and ValueError per symbol and silently continues, so a symbol that fails the missing-bar QA at line 117 vanishes from the returned dict with no record that a check refused it.**

- Trigger: Call load_many(['BTCUSDT','ETHUSDT','SOLUSDT']) where SOLUSDT's panel exceeds MAX_MISSING_BAR_FRACTION: the caller receives a two-entry dict and a pre-registered three-symbol universe has become two. It has no callers today — run_hypothesis does its own try/except at runner.py:262 and at least counts the failure into skip_reasons — so this is a live trap on the public loader rather than a currently wrong number.
- Why it is silent: The return type is a dict keyed by symbol, so the shrunken universe is indistinguishable from the requested one unless the caller compares len() against its input; a cross-symbol robustness or PBO check written against `panels.values()` would run on a quietly different universe and report a clean pass.


## LOW — orc/kernel/metrics_fc.py:31

**max_drawdown returns 0.0 for an empty or single-bar equity curve, reporting the most flattering possible number for a curve on which drawdown is simply not defined.**

- Trigger: Verified: max_drawdown(np.array([])) -> 0.0 and max_drawdown(np.array([10000.0])) -> 0.0. Reached whenever summary() is handed a degenerate curve; run_signals currently always returns a full-length array, so this is not reachable through the runner today.
- Why it is silent: It returns a float in the valid range rather than nan, and it contradicts this file's own comment at lines 21-23 — calmar honours 'a strategy that never drew down has not proved it cannot' by returning nan, but max_drawdown, itself one of the four metrics section 4 requires, still writes 0.0 into the row.


## LOW — orc/orchestrator/runner.py:205

**The simulator's start grid uses `np.arange(0, len(p) - horizon - 1, step)`, whose exclusive stop excludes the last admissible start, while the analytic branch admits every start with `ends < N`, i.e. up to `len(p) - 1 - horizon` — so the two branches of the same function disagree on the admissible-start boundary.**

- Trigger: Any config where `(len(p) - horizon - 1) % step == 0`. Verified on BTCUSDT 1h (39,243 bars) with stride 7d, 52 contributions, hold 0: horizon 8568, last admissible start 30674 (analytic returns starts 0..30674), while the simulate grid's last start is 30672 and its last touched bar is 39240 of 39242; with `step = 24` the boundary start is dropped outright in roughly one grid cell in 24. The load-bearing cross-check test drives the two evaluators directly with `res["start_idx"]`, so it never exercises the runner's start grid.
- Why it is silent: One start out of ~1300 changes `n_starts`, `start_last` and `effective_independent_paths` by an amount no reader would question, and it is always the most recent start — the one nearest the seal — that is dropped, so the loss is invisible in the reported span.


## LOW — orc/orchestrator/surface.py:350

**`pbo_for_signal_hypothesis` reports `covers_reported_best: True` when `best_config is None`, while `pbo_for_hypothesis` reports False for the same input, so the two tracks' PBO paths disagree about whether an unlocated best cell counts as covered.**

- Trigger: Any caller that omits `best_config` — `pbo_for_signal_hypothesis(h, "BTCUSDT")` from a script or a notebook. The result carries `status: "ok"` and `covers_reported_best: true`, and `verdict.survivors` accepts exactly that pair as a PBO that clears the surface's best cell, even though the function never checked that the cell was among its columns. `write_report` always passes `best_config`, so nothing in the repo triggers it today.
- Why it is silent: The default reads as "nothing to cover, therefore covered" and produces the same two fields a genuine coverage check produces, so the strongest of the three structural disqualifiers would be cleared by a measurement that did not locate the cell it is applied to.


## LOW — orc/holdout.py:163

**`open_final_test` validates neither `candidate` nor `reason`, so `candidate_sha256` pins whatever the caller happened to pass — including nothing at all — while presenting itself as the record of what was measured.**

- Trigger: Verified: `open_final_test({}, "")` succeeds and logs `candidate_sha256 = 44136fa355b3678a...` (`sha256("{}")`) with `"candidate": {}` and `"reason": ""`. The existing test at tests/test_protocol.py:751 passes `{"id": "H0002"}`, which pins the hypothesis but not the cell — so the log cannot say which of H0002's 972 parameter combinations the opening actually measured, and two different cells produce byte-identical hashes.
- Why it is silent: A 64-character hex digest is present and unique-looking in the log, so the record satisfies every inspection that checks the field exists (as the test's `len(...) == 64` assertion does) while pinning strictly less than the thing it claims to pin.


## LOW — orc/holdout.py:176

**The opening is appended to the log before the token is consumed, with no lock around the read-then-append, so one hand-written token can burn two openings and a failed `unlink()` leaves an opening recorded that granted no read.**

- Trigger: Two processes each entering `final_test()` within the same moment with one `FINAL_TEST_TOKEN` present: both `openings_used()` calls return the same N, both pass the token text check, both append a record (giving two records with ordinal N+1), then one `TOKEN_FILE.unlink()` succeeds and the other raises a bare `FileNotFoundError` — not `HoldoutViolation` — after its record is already on disk. Because that exception escapes `open_final_test`, `final_test` never reaches `_sealed_reads = []`, so the `finally` block never runs and `READS_FILE` gets no line for that opening. Same outcome from a single process if the token file is read-only or held open by another handle.
- Why it is silent: The two files end up disagreeing in the direction that looks innocuous: `LOG_FILE` shows an opening, `READS_FILE` shows nothing against it, which reads as "an opening that was consumed but measured nothing" rather than as a lost record — and the count of openings still available has quietly dropped by one more than the number of tokens a human wrote.
