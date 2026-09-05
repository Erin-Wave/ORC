# Response surfaces

Written 2026-09-05T04:01:25.709980+00:00

## H0001 — unconditional_dca_spot_style

`stride_days` dominates. At `n_contributions=156`, funding off, moving stride 1→7 moves the metric by +0.59 (ADA −0.912→−0.320), +0.74 (BNB −0.727→+0.017), +1.35 (SOL −0.980→+0.373). `n_contributions` is second and only inside the stride-7 slab: ADA 52→156 gives +0.52 there but only +0.07 at stride 1. `include_funding` is third in magnitude but first in interest — see below.

The good region is not a region. Seven of nine symbols peak at (funding off, 156, 7), which is the corner of the *measurable* grid: `n=156` is the top of its axis, and the stride-30 column is NaN in 50 of 54 cells, so stride 7 is the last measured step. The surface is a monotone ramp running straight off two edges, not a plateau with an interior maximum. The two exceptions, BTC 0.362 and ETH 0.679 at (off, 52, 30), are single cells whose every neighbour in `n` is NaN — corners with no support at all, and the only reason those symbols differ is that they have the longest history, not that 30 is doing something for them.

Funding reverses the sign of the `n` effect: with it on, ADA/DOGE/LTC/SOL/XRP/ETH at stride 7 go to exactly −1.0 as `n` rises. Exactly −1.0 is a floor, so those cells are censored, not measured.

Mechanism: none is on offer. This is unconditional DCA; the ramp is calendar coverage of one 2021–24 path, and 105 of ~112 measured cells are negative.

## H0002 — funding_carry_short

**1. 축의 지배력.** `leverage`가 압도한다. 0.25 → 1.0에서 거의 모든 셀이 -0.2~-0.4대에서 -0.5~-0.8대로 내려간다(ADA -0.30 → -0.71, SOL -0.40 → -0.79; 폭 0.3~0.4). 다음은 출구 제약: `stop_loss=null`이 `max_hold=null`과 겹치면 -1.0(완전 파괴)로 떨어지고, leverage 1.0에서는 stop만 없어도 대부분 -1.0이다. 그 다음 `lookback_days`(60이 알트에서 0.10~0.15 개선), `enter_rate`(0.0001→0.0002가 0.05~0.20, BTC는 -0.13 → +0.05), 마지막이 `max_hold_days`(0.02~0.05).

**2. 연결성.** BTC의 enter 0.0002 / lev 0.25 블록만 약하게 연결된 양수대(0.02~0.13)를 이룬다. 그러나 최고점 0.2433은 코너다 — 같은 셀의 stop 이웃이 0.1010과 0.0218, max_hold 이웃 하나는 -1.0. LTC 0.0907, XRP 0.0385도 고립점이다.

**3. 경계.** 8/9가 leverage 최소값, 8/9가 enter_rate 최대값, 5/9가 lookback 최대값에서 최고를 낸다. 세 축 모두 격자 끝이다. 다만 레버리지 방향이 "더 적게"이므로 격자 밖의 답은 노출 0이다.

**4. 심볼 일치.** 노출을 줄이는 두 축에서만 일치한다. 메커니즘을 담은 축은 흩어진다: lookback 7/21/60 = 1/3/5, stop 0.1/0.25/null = 4/2/3, max_hold 7/30/null = 2/4/3.

**5. 메커니즘.** 캐리 수취가 방향성 손실을 상쇄하지 못한다는 것 외에는 말하는 바가 없다. 지표가 단조적으로 "노출을 줄여라"를 가리키고, 강제 청산 없이 들고 있으면 -1.0으로 끝나며, 숏 기대값이 음수이고 파라미터는 손실의 배율일 뿐이다. Calmar 최고 0.2433은 종료 조건 4.0과 비교 대상이 아니다.

## H0006 — negative_funding_carry_long

**1. 축 지배력.** 셀 전체 평균 |Δ| 기준으로 `enter_rate` 0.274, `lookback_days` 0.267, `stop_loss` 0.128. 크기는 앞의 둘이 비슷하지만 부호 일관성이 다르다. `enter_rate`는 9개 심볼 중 7개에서 같은 방향(평균 +0.206), `lookback_days`는 부호가 뒤집혀 평균 −0.008이다. 그리고 셋 다 심볼 간 격차보다 작다 — AVAX 평균 −0.075에서 BTC +0.822, 범위 0.90.

**2. 연결성.** 갈린다. BTC의 `enter_rate=-0.0001` 사분면 네 셀은 1.113~1.280으로 붙어 있고, BNB의 `lookback=7` 면도 1.023~1.377이다. 반면 DOGE 최고값 1.180의 세 이웃은 0.148, −0.181, 0.514이고 SOL 1.401의 이웃은 0.373, 0.599, 0.924다. 이 둘은 고원이 아니라 코너다.

**3. 가장자리.** 축이 전부 2점이라 내부 셀이 존재하지 않는다. 모든 최적 셀이 정의상 모서리다. 8/9가 `enter_rate`의 더 음수인 끝을 고르므로 방향은 읽히지만 어디서 멈추는지는 격자 밖에 있다.

**4. 합의.** `enter_rate` 8/9, `stop_loss` 8/9로 보이지만 후자는 효과가 0.128로 작고, BTC는 0.15와 null이 1.2803051041008862로 완전히 동일하다 — 스톱이 한 번도 걸리지 않았다는 뜻이라 그 합의는 공허하다. `lookback_days`는 5:4로 갈린다.

**5. 메커니즘.** 72셀 중 31셀이 음수, 최대 1.401. 결과가 파라미터가 아니라 심볼로 정렬된다는 것이 유일하게 큰 구조다. 1bp 임계값 이동이 수취 펀딩의 경제성을 바꿀 수는 없으므로 `enter_rate` 효과는 표본에 어떤 에피소드가 들어오는지를 바꾼 것이다. 표면은 캐리를 수취한 결과와 헤지 없는 롱 노출을 구분해 주지 않는다.

## H0007 — dislocation_gated_dca

**1. 축 서열.** 두 축 모두 미미하다. `include_funding`이 근소하게 앞서고(폭 0.005 AVAX ~ 0.082 BNB, 다수는 0.03 근방), `gate`가 그 다음(폭 −0.005 SOL ~ 0.055 BNB, 중앙값 0.018 정도). 정작 지배적인 것은 격자 축이 아니라 심볼이다. BNB −0.362에서 SOL −0.945까지 0.54 — 두 축을 합친 것보다 한 자릿수 크다. 그리고 54개 셀이 전부 음수다.

**2. 연결성.** 코너이긴 하나 고립된 스파이크는 아니다. `gate`를 따라 대부분 단조롭게 개선되고 `include_funding`의 부호는 심볼 내에서 일정하다. 표면은 매끄럽다. 다만 "좋은 영역"이라는 말은 성립하지 않는다. 최고점이 −0.362, 즉 5분위 연환산 −36 %다.

**3. 경계.** 닿는다. 9개 중 7개의 최적 셀이 `gate=dip:0.20:30`, 즉 격자의 끝이며 그 방향으로 단조롭다. 더 깊고 더 긴 게이트는 측정되지 않았다. 그러나 개선폭이 수준(−0.7~−0.9) 대비 0.005~0.055에 불과해, 격자 밖에 답이 있다기보다 그 방향으로도 답이 없다고 읽는 편이 정직하다. `include_funding`은 애초에 바깥이 없는 축이다 — 실제로 지불하는 비용을 세느냐 마느냐의 회계 선택이지 고를 수 있는 파라미터가 아니다.

**4. 심볼 일치.** 형식상 7/9가 같은 코너이지만, 그 일치의 절반은 선택 불가능한 축이 만든 것이다. BNB와 SOL은 `include_funding=true`가 유리하게 뒤집힌다(0.082, 0.045) — 해당 구간 펀딩이 순수취였다는 뜻이며, 메커니즘이 아니라 확인해야 할 주장이다.

**5. 메커니즘.** 게이트는 무엇을 시사하지 않는다. 결과를 정하는 것은 창의 베타이고 dislocation 게이트는 진입 타이밍을 미세하게 옮길 뿐이다. 남는 신호는 하나뿐 — 7개 심볼에서 펀딩이 일관된 비용이라는 것, 즉 KT-1이 이미 닫은 결론의 재확인이다.

## H0017 — cci_forced_flow_duel

**1. 축의 지배력.** `rule`이 압도합니다. breakout 평균 +0.221, reversion 평균 −0.632 — 격차 약 0.85. 반면 `timeframe_hours`의 심볼 내 변동폭은 breakout에서 중앙값 약 0.40, reversion에서는 약 0.15에 불과합니다(LTC는 0.026, AVAX는 0.037로 사실상 평평). 시간축이 의미 있게 움직이는 곳은 DOGE(2.69)와 SOL(1.56) 둘뿐이고, 나머지 일곱 심볼에서는 rule 격차보다 작습니다.

**2. 연결성.** 갈립니다. AVAX(0.405~0.808)와 DOGE(0.315~3.006)는 다섯 칸 모두 양수인 연결된 영역입니다. SOL의 4h=1.170은 이웃이 0.336과 −0.113 — 고립된 첨점, 코너입니다. BNB의 4h=0.331, ADA의 4h=0.079은 크기 자체가 잡음 안입니다. LTC의 최고 칸은 −0.341, 즉 음수입니다.

**3. 경계.** BTC와 ETH의 최적점이 1h, 즉 격자 끝에 있습니다. BTC는 1h에서 12h로 단조 감소(0.265→−0.078)하므로 답은 1h 아래, 격자 밖일 수 있습니다. ETH는 최고값이 −0.033이라 경계 문제 이전에 값이 없습니다. 12h는 아홉 중 여섯에서 breakout 최악 열입니다.

**4. 심볼 합의.** rule 축에서는 9개 중 8개가 breakout으로 일치합니다. 시간축은 흩어집니다: 1h 둘, 2h 둘, 4h 셋, 8h 하나. 그리고 최고값의 크기가 3.006부터 −0.341까지 벌어져, "어디가 좋은가"보다 "무엇이라도 있는가"에서 이미 불일치합니다.

**5. 메커니즘.** 이 표면이 말하는 것은 완화(reversion) 다리의 부정입니다 — 45칸 전부 음수이고 시간축에 반응조차 없어, 신호의 실패라기보다 꾸준한 비용 출혈의 모양입니다. 반대로 continuation이 입증된 것은 아닙니다. 양수는 DOGE·AVAX·SOL에 몰려 있고 BTC·ETH·LTC는 비어 있는데, 이는 강제 청산 흐름의 변위와 그 창에서 가장 크게 추세를 낸 고베타 심볼의 단순 추세 베타를 구분하지 못합니다. 청산 스트림이 이 아카이브에 없으므로 표면만으로는 갈라지지 않습니다. 더불어 소진 메커니즘이라면 있어야 할 고유 시간 지평이 보이지 않는 점은 명시된 메커니즘에 불리한 증거입니다.

## H0019 — cci_mtf_regime_pullback

**1. 어느 축이 지배하나.** `filter_timeframe_hours`가 압도한다. 24h 전체 평균 Calmar −0.0275(중앙값 −0.060, 양수 13/36), 48h 평균 +0.1316(중앙값 +0.094, 양수 23/36) — 차이 0.159. `filter_level`의 행 평균은 60:0.070, 80:0.044, 100:0.069, 120:0.025로 폭이 0.045에 불과하고 단조도 아니다. 약 3.5배 차이.

**2. 연결되어 있나.** 눈에 띄는 값은 AVAX(80, 48h)=1.579 하나뿐이고 이웃은 0.676 / 0.920 / 0.476이다. 다만 AVAX는 8셀 전부 양수(최소 0.097, 심볼 평균 0.693)라 이건 코너라기보다 심볼 하나가 통째로 들려 있는 것이다. AVAX를 빼면 48h 평균은 0.030, 중앙값 −0.028, 최대값은 ETH 0.420으로 내려앉는다. 72셀 중 정확히 36셀이 음수, 전체 중앙값 0.001.

**3. 경계.** `filter_timeframe`은 값이 둘뿐이라 두 값 모두 경계이며, 9심볼 중 8심볼의 최적이 바깥쪽 48h다. 답이 48h 너머에 있는지 이 그리드는 답하지 못한다. `filter_level`도 9심볼 중 4개(BNB·BTC·LTC=120, XRP=60)가 경계에 최적점을 둔다.

**4. 심볼 간 일치.** timeframe만 일치한다(8/9). level은 60·80·100·120 네 값에 최적이 고르게 흩어져 있어 전혀 일치하지 않는다. 레짐 문턱이라면 심볼마다 문턱이 다를 이유가 없다.

**5. 메커니즘.** 분산의 대부분이 축이 아니라 심볼 간에 있다 — AVAX 8/8 양수, BTC 0/8(전 셀 음수, 최대 −0.102), DOGE 1/8. 문턱 축은 결과를 거의 못 움직이고 집계 캔들 길이만 움직인다. 강제 청산 흐름이 payer라면 BTC에서 무언가 보여야 하는데 전 셀 음수다. 이 표면이 메커니즘에 대해 지지하는 것은 없다.
