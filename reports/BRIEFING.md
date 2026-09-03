# ORC 연구 브리핑 — 2026-09-04 00:03 KST

## 지금 돌고 있는가

🟢 **24시간 감독자가 살아 있고 지금도 일하고 있습니다.**

- `ORC Reasoning Cycle`의 마지막 결과는 실행 실패였지만 경로는 지금 정상입니다 — 다음 발화에서 지워집니다
- 감독자 살아 있음 (pid 40628, 박동 13분 전). 지금 할 일: **kernel_review** — kernel_review: 이 저장소에서 한 번도 실행되지 않았습니다
- 마지막으로 한 일: execution_realism (13분 전) — exit 1: H0002 BTCUSDT  {'enter_rate': 0.0002, 'leverage': 1.0, 'lookback_days': 21.0, 'max_hold_days': 7.0, 'stop_loss': None} |   hourly  b
- 24시간 등록 예산 0/4 사용 — 제안과 검토는 공짜고, N을 올리는 것은 등록뿐입니다

| 무엇 | 언제 | 무슨 일이 있었나 |
|---|---|---|
| **마지막 신규 시행** (백테스트가 아무도 묻지 않았던 것에 답한 시각) | 2026-09-03 12:26 KST · 11시간 36분 전 | 시행 112건 추가 · H0001 · 소요 48초 |
| 마지막 워커 사이클 | 2026-09-03 19:25 KST · 4시간 37분 전 | 소요 34분 50초 · 신규 0건  ← 돌았지만 새로 답한 것이 없음 |
| 다음 워커 발화 (명목) | 2026-09-04 03:00 KST · 2시간 56분 후 | 6시간마다. 공개 저장소의 예약 실행은 2~4시간 지연이 흔합니다 |
| 마지막 추론 패스 (아이디어 발굴) | 2026-09-03 23:34 KST · 28분 전 | 판단 호출 실패 2건 |
| 추론 계층 마지막 기동 | 2026-09-03 23:34 KST · 28분 전 | 파이프라인을 실행했습니다 |
| 다음 추론 발화 | 2026-09-04 02:25 KST | 매일 02:25, 08:25, 14:25, 20:25 KST. 증거가 그대로면 스스로 건너뜁니다 |
| 대기 중인 질문 (큐) | — | 0개 — 다음 추론 패스가 만들 차례 |
| 열린 가족 | — | H0001 |
| 24시간 감독자 | 2026-09-03 23:49 KST | 살아 있음 (pid 40628, 박동 13분 전) |
| 지금 할 일 | — | **kernel_review** — kernel_review: 이 저장소에서 한 번도 실행되지 않았습니다 |
| 24시간 등록 예산 | — | 0/4 사용. 제안·적대자 검토·웹 정찰은 N을 쓰지 않고, 등록만 씁니다 |

### 가동 기록 — 감독자가 실제로 한 일

이 표가 비어 있거나 구멍이 나 있으면 감독자는 일하지 않은 것입니다. `reason` 만 연구가 아닙니다 — `scout`(웹에서 새 지불자 찾기), `kernel_review`(평가기 적대적 재독), `robustness`, `execution_realism`, `survivorship` 은 모두 원장에 한 줄도 더하지 않는 연구입니다.

| 시각 (KST) | 한 일 | 소요 | 결과 |
|---|---|---|---|
| 2026-09-03 23:49 KST | `execution_realism` | 2초 | exit 1: H0002 BTCUSDT  {'enter_rate': 0.0002, 'leverage': 1.0, 'lookback_days': 21.0, 'max_hold_days': 7.0, 'stop_loss': None} /   hourly  bars    39, |
| 2026-09-03 23:48 KST | `robustness` | 3초 | exit 0:   ETHUSDT    UNMEASURED: regime /       cost x2   +3.6056 -> +3.6016 /       walk        in +1.7285  out +0.9916 /       regime      the cell  |
| 2026-09-03 23:47 KST | `scout` | 4분 | exit 1: claude: SKIPPED -- exit 1:  / codex: SKIPPED -- exit 1: 2026-09-03T14:47:42.599840Z ERROR codex_models_manager::manager: failed to refresh ava |

### 정찰 노트북 — 외부에서 모은 지불자 6명

제안자의 도구는 `Read/Glob/Grep/Write` 뿐이라 저장소 안의 것만 재배열할 수 있고, 그래서 첫 여덟 가족 중 여섯이 펀딩 요율에 얹혀 있었습니다. 이 노트북은 웹과 두 번째 벤더에서 **지불자**를 모아 그 구멍을 막습니다. 성능 숫자는 규칙으로 금지돼 있습니다 — 이 파일을 읽는 단계는 이 프로젝트의 결과를 보지 않아야 하기 때문입니다.

| 언제 | 출처 | 확신 | 누가 지불하는가 |
|---|---|---|---|
| 2026-09-03 23:36 KST | codex | medium | a short-gamma BTC or ETH options dealer executing compulsory delta rebalancing through Binance USD-M perpetuals ⚠︎ 보유 데이터 부족 |
| 2026-09-03 23:36 KST | codex | high | a leveraged Binance USD-M perpetual short whose collateral has fallen below maintenance margin ⚠︎ 보유 데이터 부족 |
| 2026-09-03 23:34 KST | claude | medium | the holder of an open position in a perp Binance has announced it will retire, and the spot-versus-perp hedger who loses their only shortable leg on t ⚠︎ 보유 데이터 부족 |
| 2026-09-03 23:34 KST | claude | medium | the trader whose futures collateral is a private stablecoin that the venue values at exactly 1.0000 USD and who holds no par-redemption right of their ⚠︎ 보유 데이터 부족 |
| 2026-09-03 23:34 KST | claude | medium | the holder of a large position in a named symbol whose margin tiers Binance has announced it will tighten at a stated timestamp ⚠︎ 보유 데이터 부족 |
| 2026-09-03 23:34 KST | claude | high | the holder of a Binance dated (quarterly) futures contract, force-delivered at a published index average on a calendar minute ⚠︎ 보유 데이터 부족 |

### 가동 기록 — 최근 사이클

`+0`은 고장이 아닙니다. 워커는 큐가 비어 있어도 발화하고, 이미 답한 셀은 중복 제거되므로 **아무것도 새로 묻지 않은 사이클**이 그렇게 보입니다. 이 표의 목적은 그 줄이 몇 개나 연달아 있는지 보이게 하는 것입니다.

| 시작 (KST) | 소요 | 신규 시행 | 가설 |
|---|---|---|---|
| 2026-09-03 12:25 KST | 48초 (평가만) | +112 | H0001 |
| 2026-09-03 08:25 KST | 55초 (평가만) | +238 | H0001, H0006, H0007 |
| 2026-09-02 22:23 KST | 1분 29초 (평가만) | +1,210 | H0001, H0002, H0006, H0007 |
| 2026-09-02 21:20 KST | 1분 44초 (평가만) | +1,210 | H0001, H0002, H0006, H0007 |
| 2026-09-02 20:48 KST | 51초 (평가만) | +1,210 | H0001, H0002, H0006, H0007 |
| 2026-09-02 17:30 KST | 56초 (평가만) | +1,210 | H0001, H0002, H0006, H0007 |
| 2026-09-02 17:06 KST | 35초 (평가만) | +126 | H0006, H0007 |
| 2026-09-02 14:57 KST | 15초 (평가만) | +112 | H0001 |

### 가동 기록 — 최근 추론 패스

| 시각 (KST) | 등록 | 기각 | 거부/보류 |
|---|---|---|---|
| 2026-09-03 23:34 KST | 0 | 0 | 판단 불가 2건 |
| 2026-09-03 23:08 KST | 0 | 2 | — |

**다음 패스가 실제로 물을 것인가**: 아니오 — 마지막 패스가 28분 전입니다 — 패스 간 최소 45분을 둡니다

## 한 줄 요약

**지금 실전에 쓸 수 있는 전략은 없습니다.** 시행 6,736건을 기록했고 모든 검사를 통과한 셀은 0개입니다. 닫힌 가족 3개가 **왜** 안 되는지가 현재까지의 성과입니다 — 이 프로젝트의 산출물은 '되는 것 하나'가 아니라 '어디서 깨지는지의 지도'이고, `FAIL`은 발표 가능한 결과입니다.

## 지금까지 무엇을 확립했는가

### 사전 킬 테스트 (가설 이전에 확정된 것)

- **KT-1 펀딩 드래그**: 3년 주간 DCA에서 펀딩 청구서 중위값이 **납입자본의 36%**, BTC 정산의 87%가 양수. → **perpetual 롱 DCA 종결.** 시뮬레이터로 재라우팅하면 더 나쁩니다: 펀딩 포함 1배 롱이 ADAUSDT 시작일의 69%, SOLUSDT의 82%에서 **청산**됩니다.
- **KT-2 마틴게일**: **2배 이상에서 청산률 100%.** → 물타기에 레버리지 1배 초과 종결.
- **KT-3 생존 편향**: 거래된 적 있는 심볼 986개, 아카이브 481개, 상장폐지 266개. 사용 가능한 폐지 표본이 아직 너무 작음 → **결론 없음.** 해결 전까지 알트 바스켓 가설 금지.

### 닫힌 가족 — 시도했고, 왜 깨졌는지 기록됨

**H0002 `funding_carry_short`**

- 요지: 1. `configs/closed/H0002.json`의 종결 사유는 "단일 셀의 산술적 상한은 3개 심볼"이라고 적었지만, 108개 설정을 9심볼 횡단으로 세어 보면 **어떤 단일 셀도 2개 심볼을 넘지 못합니다**. 세 양수 심볼(BTC/LTC/XRP)의 최고값이 서로 다른 세 셀에 있기 때문입니다. 요구치 5에 대해 상한은 3이 아니라 2 — 종결이 한 칸 더 강해집니다.
- 종결 근거(원문, 번역하지 않음): The kill condition required a single cell with positive Calmar on at least five of the nine symbols and a liquidation on none. Six of the nine - SOLUSDT -0.0399, AVAXUSDT -0.0612, BNBUSDT -0.1249, ADAUSDT -0.1677, ETHUSDT -0.1691, DOGEUSDT -0.2928 - have no positive cell anywhere in the 108-cell grid. Counting the 108 …
- 부검 전문: `reports/POSTMORTEM_H0002.md`

**H0006 `negative_funding_carry_long`**

- 요지: H0002가 닫은 것은 숏 레그였다. 주장은 그 실패가 숫자가 아니라 구조 때문이라고 읽었다 — 정산률이 높은 때는 레버리지 롱 수요가 가장 강한 때이고 그때 가격은 오르므로, 리치한 펀딩을 숏하면 쿠폰과 방향 노출이 장부의 반대편에 놓인다는 것이다. H0006은 그 거울이다. 펀딩이 **음수**라는 것은 숏이 롱에게 지불한다는 뜻이고, 그 상태는 레버리지 베어 포지셔닝이 붐빌 때 — 드로다운 안쪽과 캐피출레이션 직후 — 나타나며, 붐빈 숏 베이스는 위쪽 스퀴즈를 만드는 바로 그 조건이므로 이번에는 쿠폰과 방향이 **같은 쪽을 가리…
- 종결 근거(원문, 번역하지 않음): H0006's kill condition carried four independent clauses and the third is met outright. PBO was computable on three of the nine symbols and reads at or above 0.5 on two of them - BTCUSDT 0.821 and SOLUSDT 0.516, both verdicted SELECTION_IS_NOISE, against BNBUSDT 0.278. Two of three is a majority of the symbols for which…
- 부검 전문: `reports/POSTMORTEM_H0006.md`

**H0007 `dislocation_gated_dca`**

- 발동한 조항 (사전등록 원문): Closed also - even if that bar is cleared - if the IRR improvement over the same control with include_funding false is at least as large as the improvement with it true on five or more symbols, since the gain then survives only by not paying the funding tax an…
- 요지: H0001은 구조상 무조건적이고 그 자신의 claim이 "아무도 구조적으로 지불하지 않는다"고 적었으므로, 448 trial 전부가 *돈이 얼마나 자주·몇 번 도착하는가*만 흔들고 *이 바가 살 만한 바인가*는 한 번도 묻지 않았다 — H0007은 H0001이 잡아본 적 없는 축, 즉 **게이트**를 제안했다. 지불자는 **청산당하는 레버리지 롱**이다. 유지증거금을 깬 포지션은 거래소가 호가가 주는 가격에, 크기로, 매도자가 고르지 않았고 거절할 수도 없는 순간에 닫아버리며, 한 포지션의 청산이 다음 포지션의 유지증거금 수준으로 …
- 종결 근거(원문, 번역하지 않음): [claude] clause: Closed also - even if that bar is cleared - if the IRR improvement over the same control with include_funding false is at least as large as the improvement with it true on five or more symbols, since the gain then survives only by not paying the funding tax and the shape has no home on a perpetual. -- …
- **평가 불가였던 조항 2건** — 통과한 것이 아니라 물어볼 수 없었던 것
- 부검 전문: `reports/POSTMORTEM_H0007.md`

## 현재까지 가장 좋은 셀 — 그리고 왜 아직 전략이 아닌가

각 가족이 **자기 사전등록된 리포트에서 이미 지목한** 최고 셀입니다. 원장을 새로 뒤져 찾은 것이 아니고, 가족 간 순위도 매기지 않습니다 — 그 두 가지가 이 프로토콜이 막으려는 골라잡기입니다. 등록 순서대로 나열합니다.

### H0001 `unconditional_dca_spot_style` — 진행 중 (트랙 A)

- **무엇을 물었나**: Baseline. Accumulating a major perpetual with equal deposits and no timing rule. Nobody is structurally paying us here; this exists to be the number every conditional rule must beat.
- **가장 좋았던 규칙** (ETHUSDT): 100 USDT를 30일마다 52번 매수, (총 5,200 USDT, 약 4.2년에 걸쳐), — 가격을 보지 않고 일정대로만, **펀딩 비용 제외** (perpetual에서는 실제로 낼 수 없는 조건), 만기까지 보유.
- **성과**: 연 수익률 +67.9%, 최대 낙폭 481.5% (투입자본 대비), mwrr_q05 +0.6789
- **근거의 두께**: 독립 경로 1.02개, 이 가족 시행 1120건
- **전략이 아닌 이유**:
    - spike  (SPIKE — 이웃 셀이 더 나쁘고 부호도 반대인 봉우리. 메커니즘이 아니라 격자의 모서리)
    - 1.02 paths  (독립 경로 부족 — 겹치는 시작일은 별개의 실험이 아니다)
    - PBO unmeasured  (PBO 미측정 — 같은 horizon을 공유하는 설정이 2개 미만)
    - p=1.000 vs a random search  (무작위 탐색과 구별 불가)

### H0002 `funding_carry_short` — 닫힘 (트랙 B)

- **무엇을 물었나**: Leveraged long demand on a perpetual pays the funding rate every eight hours for as long as it stays crowded, and keeps paying because the leverage is the whole point of being there: someone who merely wanted the asset would buy spot. KT-1 measured that tax from the paying side at a median 36 percent of contributed capital over a three-year weekly DCA, with 87 percent of BTC settlements positive, …
- **가장 좋았던 규칙** (BTCUSDT): 자본 10,000 USDT 고정, 직전 21일 평균 펀딩 요율이 8시간당 +0.020% 이상으로 비싸지면 공매도, 요율이 +0.005% 쪽으로 되돌아오면 청산, 노출 1배, 최대 7일 보유. 펀딩을 지불하는 쪽(레버리지 롱)에게서 쿠폰을 받는 것이 목적.
- **성과**: 연 수익률 +14.3%, 최대 낙폭 59.0% (자기자본 대비), calmar +0.2433
- **근거의 두께**: 독립 경로 47개, 이 가족 시행 4860건
- **전략이 아닌 이유**:
    - spike  (SPIKE — 이웃 셀이 더 나쁘고 부호도 반대인 봉우리. 메커니즘이 아니라 격자의 모서리)
    - p=0.360 vs a random search  (무작위 탐색과 구별 불가)

### H0006 `negative_funding_carry_long` — 닫힘 (트랙 B)

- **무엇을 물었나**: H0002 closed the short side of the funding trade for a structural reason, not a numerical one: shorting a rich settlement rate puts the coupon and the directional exposure on opposite sides of the book, because the rate is rich exactly when leveraged long demand is strongest, which is exactly when price is rising. Six of nine symbols had no positive cell anywhere in 972 trials. This is the leg tha…
- **가장 좋았던 규칙** (SOLUSDT): 자본 10,000 USDT 고정, 직전 21일 평균 펀딩 요율이 8시간당 -0.010% 이하로 내려가면 매수, 요율이 +0.010% 쪽으로 되돌아오면 청산, 노출 1배, 증거금의 15% 손실에서 손절. 펀딩이 마이너스일 때, 즉 숏이 롱에게 지불할 때 롱을 잡는 것이 목적.
- **성과**: 연 수익률 +93.4%, 최대 낙폭 66.7% (자기자본 대비), calmar +1.4007
- **근거의 두께**: 독립 경로 12개, 이 가족 시행 432건
- **전략이 아닌 이유**:
    - shape unmeasured  (shape 미측정 — 격자에 3단계 이상 수치 축이 없어 진단 자체가 불가)
    - PBO 0.52  (PBO — 0.5에서 선택은 아무 정보도 담지 않는다)
    - p=0.650 vs a random search  (무작위 탐색과 구별 불가)

### H0007 `dislocation_gated_dca` — 닫힘 (트랙 A)

- **무엇을 물었나**: H0001 is unconditional by construction and its own claim says nobody is structurally paying it; its 448 trials vary how often and how many times money arrives, never whether a given bar is a bar worth buying. This proposes the axis H0001 has never held: a gate. Who pays: the liquidated leveraged long. On a perpetual venue a position that breaches maintenance margin is closed by the exchange at wha…
- **가장 좋았던 규칙** (BNBUSDT): 100 USDT를 7일마다 52번 매수, (총 5,200 USDT, 약 1.0년에 걸쳐), — 단, 직전 30일 최고가에서 20% 이상 하락한 봉에서만 집행, 펀딩 비용 포함, 만기까지 보유.
- **성과**: 연 수익률 -36.2%, 최대 낙폭 46.7% (투입자본 대비), mwrr_q05 -0.3619
- **근거의 두께**: 독립 경로 4.15개, 이 가족 시행 324건
- **전략이 아닌 이유**:
    - at or below 0  (손익분기 이하)
    - shape unmeasured  (shape 미측정 — 격자에 3단계 이상 수치 축이 없어 진단 자체가 불가)
    - 4.15 paths  (독립 경로 부족 — 겹치는 시작일은 별개의 실험이 아니다)
    - PBO unmeasured  (PBO 미측정 — 같은 horizon을 공유하는 설정이 2개 미만)
    - p=1.000 vs a random search  (무작위 탐색과 구별 불가)

## 다음에 할 일

1. **열린 가족**: H0001. 매 사이클마다 자기 킬 조건에 대해 투표에 부쳐집니다.
2. **큐가 비어 있습니다.** 다음 제안은 추론 패스가 만듭니다 (매일 02:25, 08:25, 14:25, 20:25 KST, 증거가 바뀌었을 때만).
3. **새 메커니즘의 첫 등록은 96셀 탐침으로 제한**됩니다. 살아남으면 새 id로 넓게 열거할 수 있습니다 — 깊이는 결과로 벌어야 합니다.
4. **펀딩 기반 제안은 재론 금지.** 롱·숏 양쪽 다리가 닫혔습니다. 펀딩은 KT-1이 측정한 **비용**으로만 남고 신호로는 남지 않습니다.
5. **차단 없음.** medium/low 38건이 열려 있고, 그중 트랙 A 서치 테스트의 귀무모형 오설정이 판정 신뢰도에 직접 걸립니다 (부트스트랩 95분위가 역사상 최댓값의 35배).

## 봉인된 홀드아웃

**0/3 회 사용.** 2024-03-01 이후는 물리적으로 부재하며, 평생 3번만 열립니다. 통과한 셀이 0개인 지금 열 이유는 없습니다.

---
시행 6,736건 (N), 마지막 신규 시행 2026-09-03T03:26:42Z. 자세한 표는 `python scripts/status.py`, 기계 상태는 `python scripts/health.py`.