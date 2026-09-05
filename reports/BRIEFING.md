# ORC 브리핑 — 2026-09-05 23:10 KST

**루프** 🟡 IDLE — 마지막 신규 시행 9시간 49분 전, 큐는 비었고 감독자도 떠 있지 않습니다
**원장** N = 7,230 · 새 질문이 마지막으로 답된 것 9시간 49분 전 · 열린 가족 H0001, H0023 · 닫힌 가족 5개
**종료 조건** CAGR 100% / MDD 25% → **NO_CANDIDATE** · 최고 +209.8% (MDD 70%, H0017 DOGEUSDT)
**전략** 없음. 모든 검사를 통과한 셀 0개 — `FAIL`이 이 프로젝트의 산출물입니다
**홀드아웃** 0/3 개봉, 2024-03-01부터 봉인

## 가장 좋은 셀과 실격 사유

- **H0001** `unconditional_dca_spot_style` (진행) ETHUSDT mwrr_q05 +0.6789 — SPIKE, 1.02 paths, PBO 미측정, p=0.540
- **H0002** `funding_carry_short` (닫힘) BTCUSDT calmar +0.2433 — SPIKE, p=0.360
- **H0006** `negative_funding_carry_long` (닫힘) SOLUSDT calmar +1.4007 — shape 미측정, PBO 0.52, p=0.650
- **H0007** `dislocation_gated_dca` (닫힘) BNBUSDT mwrr_q05 -0.3619 — 0 이하, shape 미측정, 4.15 paths, PBO 미측정, p=1.000
- **H0017** `cci_forced_flow_duel` (닫힘) DOGEUSDT calmar +3.0063 — SPIKE, p=0.125
- **H0019** `cci_mtf_regime_pullback` (닫힘) AVAXUSDT calmar +1.5785 — SPIKE, p=0.050

## 다음

- 감독자: **reason** — 이 저장소에서 지문이 기록된 패스가 없습니다
- 자세히: `python scripts/briefing.py --full` · `python scripts/watch.py` · `python scripts/status.py`
