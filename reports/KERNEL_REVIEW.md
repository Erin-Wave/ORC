# Kernel review

Written 2026-09-03T23:23:42.157142+00:00. Confidence medium. 39 finding(s) over 64 file(s) read.

## HIGH — orc/eval/signal.py:150

**run_signals accepts a non-finite funding_rate that simulate.py:34 raises on, and the resulting NaN wallet makes `adverse <= liq` false forever, so liquidation is never detected again — while both RuntimeError guards (the wallet invariant at :281 and the trade-log reconciliation at :310) compare against NaN and are silently False.**

- Trigger: close = np.linspace(100, 40, 60) (a 60% fall), a 10x long entered at bar 0, symbol='SOMEALTUSDT'. With funding_rate=np.zeros(60) it returns n_liquidations=1, final_equity=0.0. With the same array plus fr[3]=np.nan it returns n_liquidations=0, final_equity=nan, n_trades=1 and raises nothing; runner.py:191 then writes liquidation_rate = 0/1 = 0.0 into the ledger. Reachability today is latent — I scanned all 430 files in FACTS/funding and found 0 non-finite or null rates — so this is one bad vendor row away, not currently firing.
- Why it is silent: NaN <= x, NaN >= x and NaN > tol are all False, so every comparison in the module that is supposed to catch a hole answers 'no hole'. The one number that would betray it, n_liquidations, comes back as 0 — an ordinary, publishable integer. simulate.py:30-38 has a comment describing this exact failure mode and refuses the input; signal.py never got the same guard.


## HIGH — orc/ledger/trials.py:67

**canonical_hash의 identity가 값이 아니라 JSON 표현 타입에 의존한다 — 7과 7.0이 서로 다른 config_hash를 만들고, np.int64(7)은 default=str에 걸려 문자열 "7"이 되므로 같은 셀이 세 가지 정체성을 가질 수 있다.**

- Trigger: 실제 ledger에서 이미 발생했다. `SELECT config_json, config_hash FROM trials`를 타입 정규화 후 묶으면, (numerically-identical config, symbol, evaluator, panel_hash, code_hash)가 동일한데 config_hash가 둘인 그룹이 90개 있고 metrics_json은 바이트 단위로 동일하다. 예: trial 6968 vs 8124 (ADAUSDT, analytic) — 유일한 차이가 `stride_days: 7.0` 대 `7`. 재현: `"grid": {"stride_days": [7]}` (int)로 등록한 뒤 `[7.0]` (float)로 다시 등록하면 된다. spec.expand()는 grid 값을 frozen dataclass에 그대로 넣고 타입 강제를 하지 않는다.
- Why it is silent: INSERT OR IGNORE가 UNIQUE에 걸리지 않으므로 새 행으로 들어가고 정상적인 신규 trial처럼 보인다. 두 행의 숫자는 완전히 같아서 어떤 리포트에서도 이상하게 읽히지 않는다. N은 줄일 수 없다고 헌장이 못박았으므로, 중복 90행이 다중검정 분모에 영구히 남는다.


## HIGH — orc/facts/panel.py:132

**bar index가 시계라는 것을 보장하는 연속성 검사가 단방향이다 — `missing = 1 - height/expected`는 bar가 모자랄 때만 발동하고, 중복 bar나 비단조 ts로 height가 expected 이상이면 missing이 음수가 되어 그대로 통과한다. 정렬 여부는 아예 검사하지 않는다.**

- Trigger: 실행해서 확인했다. BTCUSDT 1h 패널을 `pl.concat([src, src]).sort("ts")`로 만들어 load()에 넣으면 거부되지 않고 78,486 bars로 로드된다. `p.bars(7)`은 여전히 168을 반환하지만 인덱스 168개가 덮는 실제 시간은 86시간이고 `np.all(np.diff(ts) > 0)`은 False다. 또 `pl.concat([src[20000:], src[:20000]])`처럼 회전된 프레임은 expected가 0이 되어 line 132에서 의도된 거부 메시지 대신 맨 ZeroDivisionError가 난다.
- Why it is silent: load()가 예외 없이 Panel을 돌려주므로 모든 stride_days / hold_days / lookback_days / max_hold_days가 절반 길이로 조용히 재척도되고, _span이 기록하는 horizon_days와 effective_independent_paths도 같은 배수만큼 틀린다. 게다가 fetch_vision.funding_rate_per_bar는 bars가 정렬되어 있다고 가정한 searchsorted를 쓰는데, 그 전제를 검증하는 유일한 자리가 바로 이 검사다.


## HIGH — orc/kernel/metrics_fc.py:69

**파산 계좌를 거부하려고 둔 `np.any(equity <= 0.0)` 가드가 NaN에 무력하다 (`nan <= 0`은 False). NaN이 섞인 equity는 가드를 통과하고, np.log/np.diff가 만든 NaN 수익률을 `r[np.isfinite(r)]`가 삭제한 뒤 남은 수익률을 연속된 bar처럼 취급해 Sharpe를 계산한다.**

- Trigger: 실행해서 확인했다. `equity = [10000, 10100, nan, 9000, 9100, 9200]`에 대해 metrics_fc.summary는 `max_drawdown: nan`, `calmar: nan`을 주면서 `sharpe: 1652.06`을 반환한다. 같은 배열을 읽는 두 경로가 어긋난다.
- Why it is silent: 같은 curve에 대해 다른 지표는 전부 nan으로 '측정 불가'를 말하는데 Sharpe만 유한한 수를 내놓고, 그 수는 sqrt(bars_per_year) 연율화를 삭제된 bar 수를 무시한 채 적용한 값이라 크기만 클 뿐 형식상 정상으로 읽힌다. section 4가 보고하라고 요구하는 네 지표 중 하나가 바로 이것이다.


## HIGH — orc/orchestrator/surface.py:581

**The Track A search test compares an observed annualised money-weighted return against a null distribution of terminal multiples: `write_report` passes `surfaces[sym]["best_value"]`, which is ranked on `mwrr_q05` (see `ranking_metric`, line 69), while the Track A null closure at line 507 scores each synthetic path with `tm_q05_on_path`, i.e. `tm_q05`.**

- Trigger: Any Track A hypothesis; it is already in the committed reports. reports/H0001_SURFACE.json ETHUSDT: `best_value` 0.6789 == `mwrr_q05_best` 0.6789 (the cell's `tm_q05` is 3.6056) is passed as `observed_best` against `null_mean` 24.73 / `null_q95` 72.0 — terminal multiples. reports/H0007_SURFACE.json BNBUSDT: `observed_best` -0.3619 (an IRR) against `null_mean` 0.777, `null_q95` 1.206 (multiples).
- Why it is silent: Both quantities are plain floats, so `best_of_g_pvalue` computes a p-value, the status is "ok" and a verdict prints. On today's symbols the multiples sit above the IRRs so p=1.0 and it errs toward rejection, which is why nobody noticed; the sign flips the moment the null's tm_q05 distribution falls below the observed IRR — on H0007/BTCUSDT `null_q95` is 1.036, so any cell with mwrr_q05 above ~1.04 would be reported SURVIVES_SEARCH at p<0.05 by the one test that consumes N.


## HIGH — orc/orchestrator/runner.py:340

**The panel cache in `run_hypothesis` is keyed on `cfg.symbol` alone (`panels: dict[str, Panel]`), so when `clock` varies across the grid every configuration after the first is evaluated against the panel loaded for the first clock.**

- Trigger: A hypothesis with clock as an axis, e.g. track B, universe ["BTCUSDT"], grid {"clock": ["1h","1m"], "lookback_days": [7.0,21.0,60.0]} — both panels exist on disk (facts/panel_1h/BTCUSDT.parquet and facts/panel_1m/BTCUSDT.parquet). Executed against a spy on panel_mod.load: 6 configurations produced exactly one load, ('BTCUSDT','1h'). The three "1m" cells then run on hourly bars while `run_signal_trial` line 175 annualises with `metrics_fc.BARS_PER_YEAR[cfg.clock]` = 525600 on a curve of 8760 bars/yr, so `years` is 60x too small and CAGR/Sharpe/Calmar explode; that cell then wins `nanargmax` and clears the break-even floor.
- Why it is silent: A Panel is a Panel: every downstream call succeeds and returns finite numbers, the row is written with `evaluator`, `n_starts` and `panel_hash` all present — the panel_hash is simply the 1h one under a config that says 1m, and nothing cross-checks the two.


## HIGH — orc/orchestrator/runner.py:360

**`hypothesis_id` is passed to `ledger.record` but is not part of the ledger's UNIQUE key (config_hash, symbol, evaluator, panel_hash, code_hash), so a second hypothesis that re-enumerates cells an earlier one already ran gets INSERT OR IGNORE'd — the rows keep the first hypothesis's id, and `surface_from_ledger`'s `WHERE hypothesis_id=?` (surface.py:118) reports those cells as never run.**

- Trigger: Exactly the follow-up section 6 prescribes: H0006 (family negative_funding_carry_long, an 8-cell probe, fixed {rule, exit_rate 0.0001, leverage 1.0, max_hold_days null, take_profit null, capital 10000.0, clock "1h"}) re-registered wide as H0010 with the same fixed block and grid lookback_days [7,14,21,30] x enter_rate [0.0,-0.0001] x stop_loss [0.15,null]. The 8 overlapping cells produce byte-identical config dicts. Reproduced on a temp ledger: second record() returned (1, False), the single row still reads hypothesis_id H0006, and `SELECT count(*) WHERE hypothesis_id='H0010'` returns 0.
- Why it is silent: `done` counts the evaluation rather than the insert, so the summary prints "evaluated 8" and only `new` is smaller; the surface then has NaN at exactly those lattice points, `plateau_score` skips NaN neighbours without complaint, and the family reads as a grid that was run and produced fewer filled cells.


## HIGH — orc/holdout.py:133

**The irreversible opening counter is reconstructed entirely from ledger/FINAL_TEST_LOG.jsonl, and a missing file is read as "never opened" rather than as "the count is unknown", so losing or not carrying that one untracked file restores all three openings.**

- Trigger: Verified by execution: with TOKEN_FILE/LOG_FILE patched to a tmp dir, spend all three openings (the fourth is correctly refused with "all 3 final-test openings are spent"), then point LOG_FILE at a path that does not exist. openings_used() returns 0 and open_final_test({"id": "after a clone"}, "fresh checkout") succeeds, logging {"opening": 1, "of": 3}. In the real project this needs no patching: `git ls-files ledger` lists only trials.sqlite, .gitignore names FINAL_TEST_TOKEN but never the log, and ledger/FINAL_TEST_LOG.jsonl does not exist on this machine. Any fresh clone, any second working directory (LOG_FILE and READS_FILE are pinned to config.ORC_ROOT and, unlike config.LEDGER_DB, honour no env override), or a ledger/ restored from a backup taken before an opening resets the count to zero.
- Why it is silent: `_openings()` returns [] for both "the file was never written" and "the file is gone", and nothing downstream can tell them apart. The record then written is well-formed — {"opening": 1, "of": 3} — and scripts/status.py, scripts/briefing.py and scripts/daily_cycle.py all print `0/3 openings used`, which is exactly what an untouched project looks like. READS_FILE records the same openings independently and no code path ever compares the two files, so the one surviving witness is never consulted.


## HIGH — orc/holdout.py:149

**openings_used() takes max() of the recorded ordinals, so two records claiming the same opening collapse into one, and open_final_test never checks that the ordinal it is about to write is unused — the count can under-report real openings.**

- Trigger: Verified by execution: a log holding ordinals [1, 2, 3, 3] — four records — returns openings_used() == 3, leaving the cap apparently intact. Two records share an ordinal whenever two processes enter open_final_test with one FINAL_TEST_TOKEN present: both openings_used() calls return the same N before either writes, both pass the token-text check, and both append `used + 1`. CLAUDE.md §10 already records one unguarded concurrent write in this project that cost 39 minutes and 112 trials, so the interleaving is not hypothetical here. The append is not atomic with the read and there is no lock, no O_EXCL claim, and no post-write re-read.
- Why it is silent: Nothing compares the number of records to the ordinals the records themselves state; the two are allowed to disagree in the direction that hands out extra openings. The extra opening returns a normal record dict reading {"opening": 3, "of": 3} and every display prints `3/3 openings used` — indistinguishable from a project that spent exactly its three. The docstring at lines 140-147 justifies max() over len() as a defence against a lost line, which is true, but the swap traded one failure mode for its exact mirror and neither the code nor a test checks both.


## MEDIUM — orc/eval/signal.py:139

**The exchange leverage bracket is checked once against `spec.capital * spec.leverage`, but every position is sized `cash * spec.leverage`, so once the account compounds above its starting capital the evaluator opens positions at a leverage the tier table forbids.**

- Trigger: capital=10_000, leverage=10.0, symbol='SOMEALTUSDT' (LONG_TAIL). The door check passes because leverage_at(100_000) == 10. A first trade that takes equity to 32,000 is followed by a second trade whose notional is 320,000, where leverage_at(320_000) == 5. Reproduced: trade 1 notional 100,000 (allowed 10x), trade 2 notional 320,000 (allowed 5x), no error.
- Why it is silent: The margin math still looks the bracket up at the true notional, so the liquidation price is internally consistent and the equity curve is arithmetically correct — it is just the curve of a position the exchange would have rejected. The comment at :135-138 states the intent as 'Check the bracket the position actually lands in', which is the bracket at entry, not the bracket at t=0.


## MEDIUM — orc/eval/analytic.py:133

**Track A charges each deposit the funding settlement that landed on the deposit bar itself, but funding_rate_per_bar places a settlement on the bar whose OPEN contains it while the fill is at that bar's CLOSE — so the position is billed for a cash flow that cleared before it existed; lump_sum_reference:184 does the same.**

- Trigger: close = np.full(40, 100.0), funding_flow F[0] = 100.0*0.01, one contribution at stride 8, zero fees. evaluate() returns funding_paid[start=0] = 1.0 and lump_sum_reference() returns 1.0, where the correct charge is 0.0. signal.py:236 given the mirror-image input (settlement on the fill bar) returns funding == 0.0 and documents the inclusive version as a defect it fixed ('credited a full-notional settlement to a position that did not yet exist'). On the real KT-1 run (BTCUSDT, stride 168, n=156) every stride is a multiple of 8, so the artefact concentrates in one residue class: 1,650 of 13,203 start offsets (start % 8 == 3) carry a mean 2.21 USDT of phantom funding on 15,600 invested and the other 11,553 carry exactly 0.00; median bill moves 36.407% -> 36.405%.
- Why it is silent: The overcharge is contribution * f per deposit — 0.014% of capital on the configs tested — so it never looks anomalous, and it splits the start-date ensemble into two structurally different populations rather than shifting the whole distribution. tests/test_kernel.py::test_analytic_matches_simulator_with_funding cannot see it because simulate.py:175-178 charges funding after the same bar's deployment, so the cross-check pins the two evaluators to each other on the wrong convention.


## MEDIUM — orc/eval/signal.py:219

**A stop exit is booked at the stop level itself regardless of how far the bar traded through it, so a bar that gaps past the stop is filled at a price that never printed — the opposite of the 'adverse first' rule the module's own docstring sets out.**

- Trigger: fill at close=100, stop_loss=0.05 at leverage 1 (stop = 95), then a bar whose open, high, low and close are all 60. Reproduced: reason='stop', exit_price=95.0, pnl=-500.00, where a market stop fills near 60 for roughly -4000. Latent on the registered grid: across H0002's full grid (9 symbols x lookback x enter_rate x stop_loss x leverage) I measured 3,676 stop exits and 0 of them occurred on a bar that had already opened past the stop, because at leverage <= 1.0 with stop_loss 0.10/0.25 the stop sits 10-25% away in price. It bites as soon as leverage or a tighter stop puts the stop inside an hourly bar's range.
- Why it is silent: The trade is arithmetically consistent — an entry, an exit, a pnl that reconciles with the equity curve — and the invented money is bounded by the bar's range, so it shows up as a slightly better Calmar rather than as anything that looks wrong.


## MEDIUM — orc/eval/simulate.py:221

**반환 dict에 '자본이 실제로 배치되었는가'를 나타내는 값이 하나도 없어서, 게이트가 한 번도 열리지 않아 아무것도 매수하지 않은 경로와 매수 후 정확히 본전으로 끝난 경로가 출력상 완전히 동일하다.**

- Trigger: facts/panel_1h/BTCDOMUSDT.parquet 의 development 구간(seal 이전)에 gate='dip:0.20:30' (gate_below_trailing_peak(close, 0.20, 720)), SimSpec(contribution=100, stride_bars=168, n_contributions=52), starts=arange(0, N-H-1, 168) 로 simulate 실행. 90개 start 중 30개(33%)가 horizon 전체에서 게이트가 한 번도 열리지 않아 terminal_multiple 이 정확히 1.0. 실측: tm_q50 = 1.000000, tm_q05 = 0.895017, max_dd q95 = 0.2288, funding_frac q50 = 0.0. runner.py:272 는 이 out 을 그대로 _profile('tm', ...) 에 넣어 PRIMARY_METRIC 인 tm_q05 를 ledger 에 기록하며, 게이트 개방 여부를 검사하는 코드는 runner/surface 어디에도 없다(grep 확인).
- Why it is silent: 예치는 실제로 일어나 invested = 5200.0 이 정상 기록되고, wallet 에 현금이 그대로 남아 terminal_equity = contributed 가 되므로 terminal_multiple 은 NaN 도 0 도 아닌 정확히 1.0 이 된다. max_dd_total 0.0, funding_frac 0.0, frac_time_in_loss 0.0 이 함께 나와 '무손실·무낙폭 전략'으로 읽히고, 손실을 내는 DCA 셀들보다 tm_q05 상위에 랭크된다. 즉 '측정 불가'가 '완벽한 결과'로 보고된다.


## MEDIUM — orc/eval/simulate.py:220

**frac_time_in_loss / frac_time_below_peak 의 분모 lived = exit_bar + 1 은 청산 바를 포함하지만, 분자는 step 1에서 act 가 이미 지워진 뒤라 그 바를 셀 수 없어, 청산 경로만 구조적으로 e/(e+1) 로 상한이 눌린다(TP/SL 종료 경로는 step 6에서 마킹 이후에 닫히므로 이 격차가 없다).**

- Trigger: close = low = [100.0, 45.0, 45.0, 45.0], SimSpec(contribution=100, stride_bars=1, n_contributions=3, leverage=2.0), starts=[0]. e=1 에서 청산(exit_reason=1, exit_bar=1), 살아있던 모든 바에서 수중이었는데 frac_time_in_loss = 0.5000, frac_time_below_peak = 0.5000 으로 보고됨(정답 1.0). 동일 가격에 stop_loss=0.30 으로 종료시키면 1.0 이 나온다 — 같아야 할 두 경로가 갈린다.
- Why it is silent: 0.5 는 완벽하게 그럴듯한 비율이고 NaN 도 1 초과도 아니다. runner.py 는 이 값을 frac_time_in_loss_q50 으로 ledger 에 저장한다. 왜곡은 조기 사망 경로에서 가장 크므로(e=1 이면 2배 과소평가) 가장 빨리 죽는 최악의 경로가 이 지표상 가장 건강해 보이는데, 이는 바로 위 주석(216–219행)이 고쳤다고 주장하는 편향과 같은 방향이다. KT-2 처럼 청산률 100% 구간에서는 앙상블 전체가 영향을 받는다.


## MEDIUM — orc/kernel/metrics_cf.py:96

**hi와 lo가 bisection의 bracket 경계이면서 동시에 반환값이다. bracket 밖의 IRR은 정확히 +1000.0 (연 100,000 %) 또는 -0.9999로 ledger에 기록되며, 진짜로 측정된 rate와 구별할 표식이 없다.**

- Trigger: 구성해서 확인했다. `mwrr_equal_interval(100.0, n_contributions=[1.0], years_between=7/365, terminal_value=[110.0], horizon_years=[2/365])` → `[1000.]`. runner.py의 simulate 분기는 `n_real`과 `years_real`을 path별로 넘기므로 take_profit/stop_loss로 며칠 만에 V>C로 빠져나온 path가 그대로 이 값을 만든다. 현재 ledger에도 이미 mwrr_best >= 1000이 435행, mwrr_q95 >= 1000이 205행, mwrr_q99 >= 1000이 330행, mwrr_worst <= -0.9999가 186행 들어 있다.
- Why it is silent: 포화값이 예외나 NaN이 아니라 float이므로 _profile의 start_date_profile을 그대로 통과해 mwrr_mean, mwrr_q90, mwrr_q95, mwrr_q99 안으로 섞여 들어간다. section 4가 horizon 변화에 견디는 유일한 비교라고 지정한 annualised IRR이 실제로는 bracket 상수를 평균낸 값이 된다.


## MEDIUM — orc/kernel/metrics_fc.py:31

**max_drawdown이 측정할 수 없는 입력에 대해 0.0을 반환한다 — 빈 배열과 1-bar curve 모두 '낙폭이 없었다'로 읽히는 수를 돌려준다.**

- Trigger: 실행해서 확인했다. `max_drawdown(np.array([]))` → `0.0`. `summary(np.array([10000.]))` → `{"cagr": nan, "calmar": nan, "sharpe": nan, "max_drawdown": 0.0, "years": 0.0}`.
- Why it is silent: 나머지 세 지표는 모두 nan으로 '측정 불가'를 정직하게 말하는데 max_drawdown만 0.0을 말한다. max_drawdown은 Track B 주 지표인 Calmar의 분모이자 section 4가 요구하는 좌측 꼬리 진술 자체이므로, 2026-09-02의 '실행할 수 없었던 검사가 결과처럼 기록된' 패턴과 정확히 같다.


## MEDIUM — orc/facts/panel.py:175

**load_many가 FileNotFoundError와 ValueError를 삼키고 더 작은 dict를 반환한다. load()가 거부하는 모든 이유 — line 122의 'no bars left in the ... span', line 133의 시계 신뢰성 거부 — 가 전부 ValueError라서, 시계를 믿을 수 없어 제외된 심볼과 애초에 요청하지 않은 심볼이 구별되지 않는다.**

- Trigger: `load_many(["BTCUSDT", "ETHUSDT"], development_only=True)`에서 ETHUSDT 패널에 1 % 갭이 있으면 load()가 line 134에서 ValueError를 던지고, 호출자는 키가 하나뿐인 dict를 받는다. 2-심볼 universe로 등록된 가설이 1개 심볼로 평가되고, 그 사실을 담는 키가 반환값 어디에도 없다. (현재 프로덕션 호출자는 없으므로 잠재 결함이다.)
- Why it is silent: 반환 타입이 정상이고 dict.items()로 도는 코드는 있는 심볼만 처리한다. universe가 줄었다는 신호가 없으므로 결과는 등록된 universe 전체에 대한 것으로 읽히고, 시계 검사가 잡아낸 구멍이 '검사가 작동한 결과'처럼 보이지 않고 아예 사라진다.


## MEDIUM — orc/ledger/trials.py:179

**`json.dumps(metrics, default=float)`가 맨 `NaN` 리터럴을 쓴다 — 유효한 JSON이 아니며, 그 결과 best()의 `json_extract(...) IS NOT NULL` 필터가 해당 행을 순위 모집단에서 조용히 제외한다.**

- Trigger: 실제 ledger에서 측정했다. 6,736행 중 751행이 metrics_json에 맨 NaN을 담고 있다. `"sharpe"` 키를 가진 행은 5,292개인데 `json_extract(metrics_json,'$.sharpe') IS NOT NULL`로 보이는 행은 4,541개다 — 차이 751행은 전부 equity가 0에 닿아 sharpe가 NaN이 된 청산 케이스다. 재현: `run_signal_trial`이 청산으로 끝난 셀 하나를 기록한 뒤 `Ledger.best(family, "sharpe")`를 부르면 된다.
- Why it is silent: best()는 limit개를 채워 정상적으로 반환하고, 몇 행이 모집단에서 빠졌는지 알려주는 카운트가 없다. 빠진 행은 N에는 그대로 남으므로 분모는 유지되고 분자만 줄어든다. 로컬 SQLite 3.50.4는 JSON5로 파싱해 NULL을 주지만 JSON5 이전 빌드에서는 같은 문서가 'malformed JSON' 오류가 되므로, ledger의 유일한 순위 API 동작이 SQLite 버전에 따라 달라진다.


## MEDIUM — orc/orchestrator/spec.py:66

**`to_dict()` returns the values exactly as they were passed — the dataclass annotations (`stride_days: float`, `n_contributions: int`) are not enforced — so `canonical_hash` json-dumps 7 as "7" and 7.0 as "7.0" and the same configuration acquires two different trial identities.**

- Trigger: Live in the ledger today: H0007 carries fixed {"stride_days": 7, "n_contributions": 52} (ints from JSON) while H0001's grid carries [1.0, 7.0, 30.0] / [52, 104, 156]. Normalising every numeric to float collapses 90 groups of rows that currently hold two config_hashes each — e.g. ADAUSDT, funded, weekly, 52 deposits, recorded twice with tm_q05 0.43153789886329497 and 0.4315378988632958.
- Why it is silent: Nothing errors and both rows carry the same measurement to fourteen digits; the only visible effect is that N — the multiple-testing denominator, and the ledger's documented "every backtest lands here once" guarantee — is larger than the number of distinct measurements, and re-running a trial whose spelling changed prints "new 1" as though a new experiment had happened.


## MEDIUM — orc/orchestrator/surface.py:464

**`search_test_for` (line 464), `pbo_for_hypothesis` (line 276) and `pbo_for_signal_hypothesis` (line 399) hardcode `panel_mod.load(symbol, "1h")`, and the Track B null at line 490 hardcodes `BARS_PER_YEAR["1h"]`, while the trial itself was run on `cfg.clock`.**

- Trigger: A hypothesis with fixed {"clock": "1m"} — legal on both config types, and 1m panels exist. `run_signal_trial` annualises the observed Calmar at 525600 bars/yr; the null at line 490 annualises the same rule at 8760, so the observed value is ~60x the scale of every null draw, `np.sum(nb >= observed_best)` is 0, and p = 1/200 = 0.005 → SURVIVES_SEARCH. The PBO for the same hypothesis is computed over an entirely different bar series from the one the reported cell was measured on, yet returns status "ok" and covers_reported_best true.
- Why it is silent: Every path returns a well-formed result dict; the clock never appears in the PBO or search-test output, so nothing in the report says the null and the observation came from different data.


## MEDIUM — orc/orchestrator/surface.py:194

**The lattice is built from `h.grid[a]` in declaration order (line 201) while `plateau_score` treats index adjacency as value adjacency; `ordinal_axis` (spec.py:120) checks only that three numeric levels exist, never that they are sorted, and the comment at lines 184-189 claiming a None level "is not a neighbour of anything" is implemented nowhere.**

- Trigger: (a) A queue file with "lookback_days": [21, 7, 60] — declared ordinal, laid out as 21,7,60, so the neighbours of a peak at 7 are 21 and 60 and the diagnostic measures a jump of two grid steps as a perturbation. (b) "stop_loss": [0.1, 0.2, 0.3, null] — three numerics make the axis ordinal, so the peak at index 2 (stop 0.3) takes index 3, the no-stop-at-all cell, as its neighbour; if the unstopped cell scores near the peak the surface is labelled PLATEAU on the strength of a different mechanism. H0002 already ships stop_loss [0.1, 0.25, null] and max_hold_days [7.0, 30.0, null] in that spelling — one more numeric level on either turns the None into a neighbour.
- Why it is silent: `plateau_ratio` comes out as an ordinary number and the label reads PLATEAU/SLOPE/SPIKE exactly as it does on a sorted axis; nothing records which index held which value.


## MEDIUM — orc/orchestrator/runner.py:268

**The simulator's start grid is `np.arange(0, len(p) - horizon - 1, step)`, which stops one short of the last admissible start — `simulate` documents and enforces `start + horizon_bars < len(close)`, so `len(p) - horizon - 1` is itself valid — and the same expression appears at runner.py:104 and surface.py:92.**

- Trigger: A cell whose horizon is exactly len(p)-1 (e.g. N=100 bars, stride 1 bar, 100 contributions, hold 0): it passes the `horizon >= len(p)` guard at line 222, `arange(0, 0)` is empty, and the trial is recorded as skipped with reason "no_admissible_start_dates" — while the identical shape with include_funding=False routes to the analytic evaluator, which admits start 0 (ends0 = 99 < 100) and returns a number. Verified by running both: analytic n_starts 1, simulate on the same start returns terminal_multiple 1.1766, runner's grid empty. One bar shorter (horizon 98) the analytic returns 2 starts and the runner offers 1.
- Why it is silent: A skipped configuration is recorded as a fact about the grid rather than as an error, and on a normal panel losing one start out of thousands moves a quantile in the fifth decimal — so the two evaluators disagree about whether a cell is measurable at all, and the disagreement reads as grid coverage.


## MEDIUM — orc/orchestrator/spec.py:231

**`expand()` does `params.update(self.fixed)` after the grid point, so a key present in both `fixed` and `grid` silently collapses that axis to the fixed value while `size()` (line 192) still counts every level of it.**

- Trigger: A queue file with grid {"stride_days": [1,7,30], "n_contributions": [52,104,156]} and fixed {"stride_days": 7, "contribution": 100.0}: intake accepts it (size() = 9 per symbol, inside the ceiling), the prereg hash seals a three-level stride axis, and expand() emits three identical stride-7 configs per n_contributions. The cycle prints "9 configurations, evaluated 9", the ledger dedupes to 3 rows, and the surface fills 3 of 9 lattice cells.
- Why it is silent: No code anywhere checks for a key in both dicts; every emitted config is well-formed, the run summary counts the duplicates as evaluations, and the six never-run cells appear in the report as unfilled rather than as never enumerated — indistinguishable from a cell the evaluator could not express.


## MEDIUM — orc/holdout.py:114

**sealed_slice() is exported beside the gated loader but never calls note_sealed_read(), so it hands back the sealed period with no token, no log record and no counter increment.**

- Trigger: Verified by execution with no final test open: `holdout.sealed_slice(pl.read_parquet(panel.panel_path('BTCUSDT','1h')))` returns 21,505 rows beginning 2024-03-01 00:00, while `holdout.sealed_reads_permitted()` is still False and `holdout.openings_used()` is still 0. No exception. The same data through the door — `panel.load('BTCUSDT','1h', sealed_only=True)` — correctly raises HoldoutViolation. Two code paths that cut on the same boundary, one gated and one not.
- Why it is silent: It returns an ordinary DataFrame of ordinary bars. Both audit counters keep their untouched values, so status.py and briefing.py still report the seal as intact and the reads log has no line to contradict them. The module docstring at lines 14-22 claims "the loader refuses to hand back sealed bars outside one" — true of orc/facts/panel.py, but sealed_slice is the function that actually performs the cut, and the docstring's claim reads as if it covered the module.


## MEDIUM — orc/holdout.py:172

**open_final_test validates neither `candidate` nor `reason`, and json.dumps(..., default=str) derives identity from the Python type rather than the value, so candidate_sha256 presents itself as the record of what was measured while pinning whatever the caller happened to pass.**

- Trigger: Verified by execution: `open_final_test({}, "")` succeeds and logs `"candidate": {}`, `"reason": ""`, `"candidate_sha256": "44136fa355b3678a..."` — sha256 of the literal string "{}". Separately, default=str makes the digest depend on provenance: `{"start": date(2021,1,1)}` and `{"start": "2021-01-01"}` both serialise to '{"start": "2021-01-01"}' and collide, while a value json cannot serialise natively is quoted and a plain one is not, so the same cell hashes two ways. The existing test at tests/test_protocol.py:209 passes {"cfg": "candidate A"} and asserts only `len(...) == 64`, which any of these satisfy.
- Why it is silent: Every case yields 64 valid hex characters, and nothing in the project ever reads a candidate_sha256 back or compares two openings' digests. So the log cannot say which of H0002's 972 parameter cells an opening measured, cannot distinguish an opening that pinned a full configuration from one that pinned {}, and cannot reveal that a second opening re-measured the first opening's candidate — the exact reuse the three-opening cap exists to prevent.


## MEDIUM — orc/holdout.py:185

**The token is unlinked after the log record is already on disk, so an unlink failure burns an opening that measured nothing, leaves the token in place for the next attempt to burn another, and writes no corresponding READS_FILE line.**

- Trigger: Verified by execution: mark the token read-only (`os.chmod(tok, stat.S_IREAD)` — Windows `attrib +R`, a file on a read-only or synced share, or a handle held by another process) and enter `final_test({"id": "X"}, "r")`. It raises PermissionError — a bare OSError, not HoldoutViolation — after the record is written. Final state: token still present (True), LOG_FILE holds 1 opening, READS_FILE does not exist. Because the exception escapes open_final_test, final_test never reaches `_sealed_reads = []`, so the try/finally never runs. The concurrent case at line 149 produces the same shape with FileNotFoundError for whichever process unlinks second.
- Why it is silent: The exception itself is loud, but the state it leaves is not. The log record is byte-for-byte indistinguishable from a real opening, so an opening that measured nothing permanently consumes one of three, and no code path reconciles LOG_FILE against READS_FILE — the only witness that the opening measured nothing is a file that was never written.


## LOW — orc/eval/analytic.py:125

**evaluate() has no finiteness guard on `close` or `funding_flow`, and because W is a suffix cumsum a single non-finite funding value poisons every start offset in the panel, not just the ones holding through it.**

- Trigger: close = np.full(60, 100.0), funding_flow F[7] = np.nan, stride 8, n=4: all 36 of 36 terminal multiples come back non-finite with no exception. close[5] = np.nan on the same spec: 4 of 36. simulate.py:34 raises ValueError on exactly the funding input. Also `R = 1.0/close` will turn a close of 0.0 into inf without complaint.
- Why it is silent: Nothing checks, and the arrays flow straight into terminal_multiple. It is partly caught downstream — start_date_profile (metrics_cf.py:179-194) drops non-finite rows but reports n_non_finite and frac_non_finite alongside — so the hole is recorded rather than hidden; the ledger row still carries the full n_starts as its path count while the metric was computed on none of them. The current archive has no non-finite rates, so this is latent.


## LOW — orc/eval/signal_rules.py:45

**_trailing_sum builds its window from a prefix sum, so one non-finite input makes every trailing window from that bar to the end of the series NaN, rather than only the `window` bars that actually contain it — which silently shuts the rule down for the remainder of history.**

- Trigger: x = np.zeros(20) with x[3] = np.nan and window=4: the NaN belongs in windows ending at i=3..6, but all 20 outputs are NaN. Fed through carry_funding, entry is FLAT and exit_ is False for every bar after the poisoned one, so run_signals finds no signals and runner.py raises UnsupportedConfig('no_trades_fired') for the whole cell.
- Why it is silent: 'No trades fired' is a legitimate and common outcome for a carry rule whose threshold is never met, so a cell that was silenced by one bad data point is recorded identically to a cell whose mechanism simply never triggered. Latent for the same reason as the findings above: the current funding archive is clean.


## LOW — orc/eval/signal.py:170

**The side is read once at the opening signal and never re-read, so an `entry` array that flips from +1 to -1 while a position is open holds the original side until an independent exit signal, stop or liquidation fires.**

- Trigger: entry = +1 on bars 0-9 then -1 on bars 10-29 with exit_ all False, on a series that rises 100 -> 200 over bars 10-29. Reproduced: one trade, side=+1, bars 1..29, pnl=+10,000 — the flip to short at bar 10 is discarded and the run collects the move the short signal said it would be on the wrong side of. Not reachable from the repo today: both entries in signal_rules.RULES are one-sided (carry_funding emits SHORT/FLAT, carry_funding_long emits LONG/FLAT). It becomes reachable the first time a two-sided rule is registered, which is what CLAUDE.md section 4 describes Track B as being.
- Why it is silent: The trade log, the equity curve and the reconciliation check are all consistent; nothing anywhere compares `entry[t]` against the side actually held, so the run reports a perfectly well-formed set of trades that the rule did not ask for.


## LOW — orc/eval/signal.py:256

**The equity curve is marked at closes only while the liquidation, stop and take-profit checks all use intrabar extremes, so maximum drawdown — one of the four metrics CLAUDE.md section 4 requires for Track B — cannot see an excursion that did not survive to a close.**

- Trigger: A 10x long filled at close=100 on a flat series with low[5]=95.2 and close[5]=100: true mark equity at that low is 5,200 of a 10,000 wallet, reported max_drawdown is 0.0, and n_liquidations is 0 (the wick was checked, just not recorded). On the registered grid the effect is small: at leverage 0.25 on H0002's lookback=21d/enter=0.0001 cell, BTCUSDT reports max_dd 0.5219 close-marked against 0.5228 marked at each bar's adverse extreme — 0.09 pp.
- Why it is silent: The curve is a valid mark-to-market path and every other number derived from it reconciles; the drawdown simply describes a coarser path than the one the liquidation check was allowed to see. The comment at :255 reads 'so drawdown sees the path, not just the fills', which is true of fills and not of wicks.


## LOW — orc/kernel/liquidation.py:70

**BTC_LIKE tier 7 의 cum_maint 가 11,098,050 인데 브라켓 연속성(cum_{k+1} = cum_k + cap_k*(mmr_{k+1}-mmr_k) = 6,348,050 + 230e6*0.025)이 요구하는 값은 12,098,050 이며, 오차가 tier 8·9로 전파되어 notional 230,000,000 지점에서 maintenance_margin 이 1,000,000 만큼 불연속 점프한다. 그 결과 is_liquidated 가 mark 가격에 대해 비단조가 되고 liquidation_price_long 과 불일치한다.**

- Trigger: wallet=23,000,000, qty=1000, entry_price=230,000, table=BTC_LIKE. liquidation_price_long → 229,316.51 (청산가). 그런데 is_liquidated 는 mark=230,100 에서 True, mark=230,000 과 229,500 에서 False, mark=229,316.50 에서 다시 True 를 반환한다. 즉 가격이 내려가면서 청산 상태에 들어갔다 나왔다 하며, 폐형해가 0.342% 만큼 생존을 과대평가한다. MAJOR_ALT, LONG_TAIL 은 모든 경계에서 연속임을 확인했다(BTC_LIKE tier6→7 만 유일한 불연속).
- Why it is silent: 두 함수 모두 예외 없이 float 를 반환하고, simulate 는 bar low 한 점에서만 is_liquidated 를 호출하므로 비단조성이 드러나지 않는다. 어떤 바의 low 가 230,100 이면 죽고 229,500 이면 사는 — 더 낮은 저가가 생존을 낳는 — 결과가 나오지만 liquidation_rate 는 그대로 유한한 숫자로 나온다. 현재 연구의 소액 DCA(대개 수천 USDT)로는 230M notional 에 도달하지 않으므로 실질 도달 불가이나, 모듈 docstring 이 '용량(capacity) 연구가 잘못된 요율을 조용히 쓰지 않도록 표를 전부 구현했다'고 주장하는 바로 그 지점이 틀려 있다.


## LOW — orc/eval/simulate.py:262

**gate_below_trailing_peak 의 `elif n > lookback:` 와 gate_below_sma 의 `if n > window:` 가 off-by-one 이라 n == lookback 일 때 sliding_window_view 가 정상 동작함에도 계산을 건너뛰고, n <= window 인 경우와 함께 roll/sma 가 전부 NaN 으로 남아 '전부 False' 게이트를 오류 없이 반환한다.**

- Trigger: n=50 하강 시리즈에서 gate_below_sma(c, 48)=2개 개방, 49→1개, 50→0개, 51→0개. 실데이터로는 development 구간이 720바보다 짧은 1h 패널 9개(DYMUSDT 545, GLMUSDT 182, JUPUSDT 702, MAVIAUSDT 206, OMUSDT 394, PIXELUSDT 249, RONINUSDT 572, STRKUSDT 223, ZETAUSDT 664)에 등록된 게이트 'dip:0.20:30'(lookback = p.bars(30) = 720) 을 적용하면 모두 0바 개방. panel.load 는 이 패널들을 거부하지 않으며(MIN_BARS_REQUIRED 는 build 시점 전체 span 기준), 짧은 horizon(예: stride_days=1, n_contributions=5 → 96바)이면 runner 의 no_admissible_start_dates 도 통과한다.
- Why it is silent: '하락이 없어서 게이트가 안 열렸다'와 '게이트를 계산할 수 없었다'가 동일한 all-False 배열로 표현된다. 이것이 위 첫 번째 findings 와 결합해 terminal_multiple 정확히 1.0, 낙폭 0 인 결과를 낳는다 — 실측: window=399 는 1바 개방, window=400/401 은 0바이며 세 경우 모두 terminal_multiple=1.000000, max_dd_total=0.0000 으로 구분 불가.


## LOW — orc/kernel/inference.py:235

**ordinal_axes 기본값 `[d > 2 for d in g.shape]` 이 축의 '순서성'을 값의 개수로 추정하기 때문에, 2수준 수치 축(leverage=[1,2], n_contributions=[52,104])은 범주형으로 간주되어 이웃 검사에서 통째로 제외되고, 3수준 범주 축(symbol=[BTC,ETH,SOL])은 순서 축으로 간주되어 섭동으로 평가된다. 또한 ordinal_axes 를 g.ndim 보다 짧게 주면(239행 `axis < len(ordinal_axes)`) 남는 축은 조용히 순서형으로 취급된다.**

- Trigger: plateau_score(np.array([[1.40,0.20],[1.50,0.20],[1.45,0.20]])) → plateau_ratio 0.95, shape 'PLATEAU'. 정점 1.50 은 2수준 축을 한 칸 움직이면 0.20 (87% 붕괴)인데 그 축이 건너뛰어진다. 같은 격자에 ordinal_axes=[True,True] 를 주면 0.678 / 'SPIKE'. 반대 방향: plateau_score(np.array([[2.0,0.1,0.1],[0.1,0.1,0.1]])) 는 3수준 symbol 축을 이웃으로 써서 다른 심볼을 같은 메커니즘의 섭동으로 취급한다. 3차원 격자에 ordinal_axes=[True,True] 를 주면 이웃 5개(축2 포함), [True,True,False] 면 4개.
- Why it is silent: CLAUDE.md 6장이 '값보다 shape 컬럼을 먼저 읽으라'고 규정한 바로 그 라벨이 PLATEAU/SPIKE 사이에서 뒤집히는데, 반환값은 언제나 유한한 비율이고 n_neighbours 도 그럴듯한 정수다. 현재 유일한 프로덕션 호출부인 surface.py:217 은 ordinal_axis() 로 계산한 리스트를 명시적으로 넘기므로 오늘은 도달하지 않는다 — 기본값은 새 호출부가 인자를 생략하는 순간 발동하는 잠복 함정이다.


## LOW — orc/eval/simulate.py:85

**start 오프셋 검증이 starts.max()+H >= N 과 starts.min() < 0 만 보고 horizon_bars 자체가 음수인 경우를 잡지 못해, starts + H 가 음수 인덱스가 되어 시리즈 끝에서 값을 읽는다.**

- Trigger: SimSpec(contribution=100, stride_bars=5, n_contributions=0) → horizon_bars = -5. simulate(close(len=100), low, starts=[0], spec) 이 검증을 통과하고 루프는 range(-4) 로 비어 있으며, 205–213행이 close[0 + (-5)] = close[95] 를 읽는다. 결과: exit_bar=-5, terminal_multiple=0.0, invested=0.0, bars_lived=1.0. orc/orchestrator/spec.py 에는 n_contributions 하한 검증이 없어(grep 확인) 큐 JSON 에 "n_contributions": [0, 52, 104] 를 쓰면 그대로 등록·실행된다.
- Why it is silent: terminal_multiple = 0 / max(0, 1e-12) = 0.0 은 '전손'으로 읽히는 완전히 그럴듯한 숫자이며, 잘못된 설정으로 거부되는 대신 ledger 에 행으로 남아 N(다중검정 분모)을 영구히 올린다. 동시에 시리즈 시작 지점의 경로가 시리즈 끝의 가격을 읽는 미래 참조가 발생하지만 invested 가 0 이라 숫자로 드러나지 않는다.


## LOW — orc/kernel/metrics_cf.py:182

**모든 path가 non-finite인 앙상블에서 start_date_profile이 예외 대신 분위수 키가 전혀 없는 dict를 반환한다.**

- Trigger: 실행해서 확인했다. `start_date_profile(np.array([np.nan, np.inf, -np.inf]))` → `{'n': 0, 'n_non_finite': 3}`. _profile을 거치면 그 trial의 metrics에는 tm_q05도 tm_worst도 tm_mean도 없다. (현재 Track A 1,444행은 전부 tm_q05를 갖고 있으므로 실현되지는 않았다.)
- Why it is silent: 행은 정상적으로 ledger에 들어가 N을 1 올리고, `json_extract(metrics_json,'$.tm_q05')`는 NULL을 반환해 best()와 PRIMARY_METRIC으로 선택하는 모든 surface에서 조용히 사라진다. 측정할 수 없었던 셀이 거부로 남지 않고 '키가 없는 정상 행'으로 남는다.


## LOW — orc/orchestrator/spec.py:195

**`size()` scores an empty axis as `max(len(v), 1)` = 1 while `expand()`'s `product()` yields nothing, so a grid with an empty list registers as a sized hypothesis and enumerates zero configurations.**

- Trigger: A queue file with grid {"stride_days": [1,7,30], "hold_days": []}: `shape_is_measurable()` passes on stride_days, `size()` returns 3 x |universe| so the probe ceiling is cleared, the hypothesis is hashed and saved, `expand()` returns [], and `run_hypothesis` reports configurations 0 / evaluated 0 / skipped 0 while `write_report` writes a report with an empty `surfaces` dict.
- Why it is silent: `max(len(v), 1)` reads as a defensive guard rather than a divergence; registration succeeds, an id and a prereg hash are permanently spent, and the family shows up in the registry as asked-and-answered with no rows behind it.


## LOW — orc/orchestrator/surface.py:151

**`provenance` accumulates the code and panel hash of every row returned by the query, including the superseded ones that the newest-wins overwrite at line 145 discarded, so `assembled_from` describes the history of the cell rather than the revisions the surface is actually made of.**

- Trigger: H0001 as committed: reports/H0001_SURFACE.json reports assembled_from {"code_revisions": 10, "panel_revisions": 4} for every symbol, while grouping the same rows by config and keeping the newest per cell (exactly what line 145 does) leaves 1 distinct code_hash across all 12 used rows on ADAUSDT/AVAXUSDT/BNBUSDT. H0002 reports the same warning from 5 revisions over 540 rows and 1 over the 108 used.
- Why it is silent: It is a count that is always at least the true value, so it never contradicts anything; the flag whose stated meaning is "the cells on this surface are not comparable to each other" is permanently on for every hypothesis and therefore carries no signal when it is genuinely true.


## LOW — orc/orchestrator/verdict.py:32

**`floor = BREAK_EVEN.get(metric)` returns None for any metric outside the three-entry table and the break-even check is then skipped entirely, while every other unrunnable check in this function is deliberately recorded as a disqualifier.**

- Trigger: `write_report(h, metric="tm_q50")` — the metric parameter is public and threaded straight into `report["metric"]` — produces a report in which a cell at tm_q50 0.4, having lost 60 % of contributed capital, collects no "at or below" reason and is announced by notify.py as clearing every check. The mirror case: `survivors()` falls back to "tm_q05" when a report has no "metric" key, applying a multiple's floor of 1.0 to a Calmar or an IRR.
- Why it is silent: The other four disqualifiers still run and print, so the verdict looks complete; the one line that would have said the cell loses money simply never appends, which is the same failure this module was written to close.


## LOW — orc/holdout.py:169

**The token comparison decodes as strict UTF-8 and canonicalises with str.strip(), which removes neither a byte-order mark nor a UTF-16 encoding, so a byte-correct token written by the environment's default tools is rejected.**

- Trigger: Verified by execution: a UTF-8-with-BOM token reads back as '\ufeffI am opening...' and compares unequal, because U+FEFF is not whitespace to str.strip(); a UTF-16LE token reads back as 'I\x00 \x00a\x00m\x00'. This environment's own PowerShell notes record that `>` and `Out-File` here default to UTF-8 with BOM, and MANUAL_SETUP.md:287 instructs the operator to create the file with an editor. (CRLF is not affected — Path.read_text uses universal newlines, which I checked before reporting.)
- Why it is silent: It is not silent: it fails closed with "FINAL_TEST_TOKEN text does not match; refusing to open." It is listed only because the door's identity check depends on an incidental encoding rather than on the text, and the message names no differing byte — the operator sees a correct-looking file rejected, which is the state that invites editing the check or TOKEN_TEXT rather than the token.
