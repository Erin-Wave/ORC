# 파이프라인 — 질문이 답이 되어 눈에 보이기까지

이 문서는 **고치기 전에 읽는 지도**다. 2026-09-04 하루에 이 영역을 국소적으로
네 번 수정했고, 네 번 모두 "수정 → 예상 못 한 결과 발견 → 또 수정"이었다.
문제는 수정의 크기가 아니라 **수정 전에 경로 전체를 보지 않은 것**이었다.

| 오늘의 사고 | 국소적으로 보면 | 실제로 무엇을 건드렸나 |
|---|---|---|
| `.git/hooks` 존재를 단정한 테스트 | 테스트 한 줄 | `orc-cycle`의 **테스트 게이트**를 빨갛게 만들어 **연구를 2시간 정지** |
| CI에 `pytest tests -q` 무조건 실행 | 스텝 한 줄 | 러너에 `facts/`가 없다는 사실은 뮤테이션 스텝에만 반영돼 있었음 |
| `git reset --soft HEAD~1`로 인덱스 재현 | 스텝 한 줄 | 뒤 스텝의 `HEAD~1 HEAD` diff가 엉뚱한 쌍을 비교 → **초록인데 검사 건너뜀** |
| 커밋 로직을 `commit_results.py`로 추출 | 파일 하나 | 상주 창 스텝에 **머지 정책 사본이 하나 더** 있었음 |

그래서 이 파일에는 단계, 각 단계의 소유자, 불변식, 그리고 **이 경로를 고칠 때
반드시 확인할 목록**이 있다.

---

## 1. 단계

```
 (A) 제안            워크스테이션 supervisor → reasoning.py
                     configs/proposed/ → 적대자 거부권 → configs/queue/
                     스스로 커밋·푸시한다 (N을 올리는 유일한 커밋)
        │
 (B) 등록 + 평가     orc-cycle 잡 (6시간 크론 + dispatch)
                     ├ 패널 내려받기 (봉인 이전 구간만 담긴 번들)
                     ├ 봉인 데이터 접근 거부 확인
                     ├ ★ Kernel test suite  ← 빨간색이면 여기서 연구가 멈춘다
                     ├ daily_cycle.py
                     │   ├ intake_queue()  큐 파일은 항상 사라진다:
                     │   │                 등록되면 unlink, 거부되면 queue/rejected/
                     │   ├ run_hypothesis() → 원장(append-only, N)
                     │   ├ 서피스 리포트 / 서치 테스트 / PBO
                     │   ├ robustness 게이트
                     │   └ TARGET.json, BRIEFING.md, NEWS.json
        │
 (C) 착지            commit_results.py  ← 머지 정책의 유일한 정의 위치
                     사이클 직후 1회, 잡 마지막에 1회
                     stage(named dirs) → commit → pull --rebase → push ×3
        │
 (D) 상주 창         forever.py --until-minutes 300 --skip reason,scout,kernel_review
                     매 tick runstate.next_action():
                       findings 차단 → 종료조건 후보 → 큐(GITHUB_ACTIONS면 cycle)
                       → reason → zero-N 작업 → rest
                     액션마다 land()로 리포트 커밋·푸시
        │
 (E) 관측            health.py (한 화면) / briefing.py (한글) / notify.py → NEWS.json
                     → GitHub 이슈, orc-watchdog(루프 밖에서 루프를 본다)
        │
 (F) 게이트          로컬: pre-commit(스위트·원장·새 파일) + commit-msg(마커)
                     원격: orc-guard — 같은 스위트, 같은 마커 검사, 뮤테이션
                     러너에는 훅이 없고 --no-verify는 존재한다: (F)-원격이 유일한
                     "에이전트가 통제하지 못하는 기계"
```

## 2. 불변식 — 고칠 때 깨뜨리면 안 되는 것

| # | 불변식 | 지키는 것 | 오늘 상태 |
|---|---|---|---|
| I1 | **스위트는 연구의 게이트다.** 이 기계에서만 통과하는 테스트는 연구를 멈춘다 | `orc-cycle`의 테스트 스텝 | 오늘 깨졌다 → `fce5c39`에서 3개를 이식 가능하게 |
| I2 | 결과는 계산된 즉시 원격에 도달한다 | `commit_results.py` ×2 호출 | 오늘까지 5시간 지연 → `ea161fd` |
| I3 | N은 커지기만 한다. 원장은 union으로 병합하고, 한쪽을 고르지 않는다 | `.gitattributes` + `merge_ledger.py` + 단일 정책 위치 | 실제 이진 충돌로 검증(3+4=7행) |
| I4 | 등록된 질문은 이미 떠 있는 기계를 기다리지 않는다 | `next_action`의 `cycle` 분기 | 오늘 1h29m 대기 → `e1d0e51` |
| I5 | 모든 게이트는 에이전트가 통제하지 못하는 기계에서도 돌아야 한다 | `orc-guard` | `c78b506` |
| I6 | 오라클은 조용히 약해질 수 없다 | `orc/guard.py` + commit-msg 훅 | `af5046d` |
| I7 | 테스트 자체가 검사된다 | `scripts/mutation.py`, 매일 | 18/18, 구멍 4개 발견 |
| I8 | 오너 화면의 모든 줄은 참이어야 한다 | `health.py` + 테스트 | 4줄 수정 |
| I9 | **어떤 액션도 실패하면서 hot loop가 되지 않는다** | `FAILURE_COOLDOWN_MIN` | **`cycle` 분기에 빠져 있다 → 이 문서가 찾은 것** |

## 3. I9 — 이 지도가 찾아낸 구멍

`FAILURE_COOLDOWN_MIN`(12분)은 `ZERO_N_WORK` 루프 **안에서만** 적용된다.
`cycle` 분기는 그 루프보다 먼저 반환하므로 쿨다운이 없다. 큐가 남은 채
`daily_cycle.py`가 실패하면(패널 다운로드 실패, 크래시) 상주 창은
`WORKED_SLEEP_S = 30초`마다 같은 실패를 무한히 재시도하고, zero-N 작업은
영원히 순번을 얻지 못한다.

`intake_queue()`가 큐 파일을 항상 없애기 때문에(등록 또는 `rejected/` 이동)
"같은 파일을 영원히 다시 등록"하는 경로는 없다. 위험한 것은 **intake 이전에
죽는 실패**뿐이다 — 그리고 그것이 정확히 재시도해도 소용없는 종류다.

→ 조치: `cycle` 분기도 `FAILURE_COOLDOWN_MIN`을 통과해야 한다. 실패 후
12분 안에는 zero-N 작업으로 내려가고, 12분 뒤에 다시 시도한다.

## 4. 이 경로를 고치기 전 확인 목록

1. **이 변경이 (B)의 테스트 게이트를 통과할 수 있나?** 이 기계에만 있는 것
   (`.git/hooks`, `facts/` 9.7 GB, Windows 예약 작업, 전역 git 신원)을
   단정하는 테스트는 러너에서 실패하고 **연구를 멈춘다.**
   확인: `ORC_FACTS=<빈 디렉터리> python -m pytest tests -q`
2. **HEAD·인덱스·작업 트리를 건드리나?** 건드리면 그 스텝은 **마지막**이어야
   하고 원상복구해야 한다. 뒤에 오는 스텝은 조용히 다른 커밋을 보게 된다.
3. **`git config merge.*`를 쓰려 하나?** 정의는 `commit_results.py`에만 있다.
   사본을 만들면 둘 중 하나가 표류하고, 표류한 쪽이 실행된다.
4. **새 액션인가?** `plan()`, `TIMEOUTS_S`, `DONE_EXIT_CODES`,
   `COMMIT_PATHS`, 쿨다운(I9), 그리고 zero-N인지 N을 올리는지를 모두 답해야
   한다. 하나라도 빠지면 조용히 아무 일도 하지 않거나 hot loop가 된다.
5. **워크플로에 조건 분기를 넣으려 하나?** 조용히 틀릴 수 있는 조건은
   그것이 아끼는 시간보다 비싸다(run 33845845287: 32초에 초록, 검사는 건너뜀).
   공용 저장소의 러너 시간은 무제한이다.
6. **오너 화면에 새 사실이 생기나?** `health.py`에 줄을 추가하고, 그 줄이
   다른 줄과 모순되지 않는지 확인한다(정지 시계는 **작업**을 따라가야 하고
   호출자를 따라가면 안 된다).
7. **`python scripts/mutation.py`를 돌렸나?** 커널이나 테스트를 건드렸다면
   이것이 "테스트가 아직 물고 있는가"에 답하는 유일한 방법이다.

## 5. 아직 열려 있는 것 (판단 필요, 임의로 손대지 않음)

- **상주 창과 dispatch의 동시성 그룹.** `cancel-in-progress: false`이므로
  dispatch된 사이클은 최대 5시간 줄을 선다. I4는 러너가 스스로 큐를 걷게 해서
  *증상*을 없앴지만, 그룹 설계 자체는 그대로다. 창을 짧게 하거나 그룹을
  나누는 것은 러너 시간·중복 실행 위험과의 교환이라 소유자 판단이 필요하다.
- **medium/low findings 94건.** 차단하지 않지만 읽히지도 않는다.
- **워크스테이션은 큐를 걷지 않는다.** 의도된 분업이다(동시 원장 쓰기로
  run #19이 112 trial과 39분을 잃었다). 바꾸려면 잠금부터 설계해야 한다.
