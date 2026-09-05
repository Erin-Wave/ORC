# Kernel review

Written 2026-09-05T02:14:54.857543+00:00. Confidence high. 4 finding(s) over 4 file(s) read.
13 file(s) were NOT read this run and are not covered by the result below: orc/eval/__init__.py, orc/eval/analytic.py, orc/eval/signal.py, orc/eval/signal_rules.py, orc/kernel/metrics_cf.py, orc/kernel/metrics_fc.py, orc/facts/panel.py, orc/ledger/trials.py, orc/orchestrator/runner.py, orc/orchestrator/verdict.py, orc/orchestrator/surface.py, orc/orchestrator/spec.py, orc/holdout.py

## MEDIUM — orc/eval/simulate.py:88

**funding_rate is checked for non-finite values with an explicit guard and a comment naming the exact failure mode, but close and low are coerced with np.asarray and never checked, so one NaN bar makes every path holding through it permanently unliquidatable.**

- Trigger: close=[100]*5+[55]*35, low identical except low[5]=49.0, starts=[0], SimSpec(contribution=100, stride_bars=1, n_contributions=4, hold_bars=20, leverage=2.0), table=BTC_LIKE gives liquidation_rate 1.0 and terminal_multiple 0.0. Setting low[5]=np.nan and changing nothing else gives liquidation_rate 0.0 and terminal_multiple 0.0988. On a 10-start ensemble with the same NaN, 5 of 10 paths that were certainly liquidated report as survivors and liquidation_rate reads 0.0. panel.load performs no finiteness check on price columns, so such a panel loads: _assert_bar_index_is_a_clock only inspects timestamps. The 325 panels currently in facts/panel_1h are clean (0 non-finite, 0 low<=0, 0 inverted bars), so no recorded result is affected -- this is a hole in the guard, not a live corruption.
- Why it is silent: NaN <= maintenance_margin is False, so is_liquidated answers False forever after, exactly as the funding_rate guard's own comment describes. liquidated stays all-False and liquidation_rate -- the only number KT-2 reads -- comes back finite, understated, and with no non-finite flag of its own. max_dd_total does go NaN, but start_date_profile drops non-finite values into n_non_finite and still emits quantiles from the survivors, so the drawdown column reads as a smaller clean sample rather than as a broken one.


## MEDIUM — orc/eval/simulate.py:214

**Liquidation (line 162) and drawdown (line 156) are both tested against the bar LOW, but stop-loss is tested only against the bar CLOSE, so the same function reports a drawdown deeper than the registered stop threshold while reporting that the stop never fired.**

- Trigger: close=[100.0]*30, low identical except low[6]=45.0, SimSpec(contribution=100, stride_bars=1, n_contributions=3, hold_bars=20, leverage=1.0, stop_loss=0.30, all costs 0), starts=[0]. Result: max_dd_total 0.55, exit_reason 0 (EXIT_HORIZON), terminal_multiple 1.0. Printing the identical -55% move as a close instead (close[6]=45.0, low unchanged) gives max_dd_total 0.55, exit_reason 3 (EXIT_STOP_LOSS), terminal_multiple 0.45. A registered cell with stop_loss=0.30 therefore stores dd_q50 = 0.55, which its own rule makes impossible. Currently latent: runner.py:363 records that of 1332 Track A rows none has take_profit or stop_loss set, so no stored row carries it -- but the shape is registrable today.
- Why it is silent: The stop simply never triggers on a wick, and the path runs on to the horizon and produces an ordinary terminal_multiple. The bias is not random: it deletes the whipsaw cost that is the dominant cost of a stop rule, so every stop-loss variant is measured as better-behaved than it is, and the one artefact that would give it away -- a drawdown larger than the stop -- appears in a different column of the same ledger row from the exit_reason that would contradict it. take_profit has the mirror asymmetry but errs conservatively and cannot be fixed here anyway, since `high` is never passed to simulate; `low` is.


## LOW — orc/eval/simulate.py:207

**The liquidation bar is removed from `act` at line 175, before step 5 counts bars_in_loss/bars_below_peak, but `lived` at line 240 is exit_bar+1 and does include it -- so the bar on which the account was wiped out is in the denominator and not in the numerator.**

- Trigger: close=[100,100]+[50]*38, low identical, SimSpec(contribution=100, stride_bars=1, n_contributions=5, hold_bars=20, leverage=3.0), starts=[0], table=BTC_LIKE. The path is liquidated at exit_bar 2 with bars_lived 3.0 and reports frac_time_in_loss 0.6667. It was in loss on every bar it lived, including the one that wiped it out, so the correct value is 1.0. The error is 1/(exit_bar+1), so it is negligible for a late liquidation and large for an early one.
- Why it is silent: 0.6667 is a perfectly ordinary value for this field, and the sign of the error is the same one the comment at lines 236-239 was written to remove: the paths that die earliest still look the healthiest on this measure. run_trial writes frac_time_in_loss_q50 on every simulate row, and nothing downstream can distinguish an understated fraction from a true one.


## LOW — orc/kernel/liquidation.py:70

**BTC_LIKE's cum_maint for the 480M tier is 11_098_050.0 where bracket continuity requires 12_098_050.0 (= 6_348_050 + 230e6 * (0.15 - 0.125)), putting a 1,000,000 USDT step discontinuity in maintenance_margin at a notional of 230M.**

- Trigger: maintenance_margin(230_000_000.0, BTC_LIKE) = 22,401,950.00; maintenance_margin(230_000_000.000001, BTC_LIKE) = 23,401,950.00. I checked every bracket boundary in all three tables: 17 of 18 are continuous to 0.00 and this one alone jumps by exactly 1e6, which is what identifies it as a transcription slip (11 for 12) rather than a modelling choice. Not reachable at the project's current scale -- retail DCA at a few thousand USDT never leaves tier 0 -- so no result in the ledger is affected.
- Why it is silent: maintenance_margin is monotone and of the right order of magnitude either side of the boundary, so a capacity study crossing 230M would just see a slightly harsher liquidation level and a plausible liquidation_price_long; the closed-form and is_liquidated agree with each other because both read the same wrong constant. The module's own comment at lines 59-61 states the full table exists specifically 'so that capacity studies cannot silently use the wrong rate', and nothing tests the tables for continuity.
