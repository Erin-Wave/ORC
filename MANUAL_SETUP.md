# ORC 수동 설정 가이드

자동화가 돌아가려면 **사람만 할 수 있는 일** 4가지가 있습니다. 계정 생성, 인증,
그리고 "봉인 해제" 같은 되돌릴 수 없는 결정입니다. 나머지는 전부 코드가 합니다.

전체 소요: 처음 한 번 **약 40분**. 이후에는 손댈 일이 없습니다.

---

## 준비 상태 확인

먼저 지금까지 자동으로 만들어진 게 정상인지 확인하세요.

```bash
cd D:\Project\ORC
python -m pytest tests -q
```

`38 passed` 가 나와야 합니다. 안 나오면 그 아래 단계는 진행하지 마세요.

---

## STEP 1 — 전체 패널 빌드 (로컬, 약 15분)

지금은 10개 심볼만 만들어져 있습니다. 481개 전부 만듭니다.

```bash
cd D:\Project\ORC
python -m orc.facts.build_panel
```

- 심볼당 약 1.4초 → 전체 약 11분
- 디스크: 1분봉 약 36GB, 1시간봉 약 750MB (D드라이브 여유 781GB이므로 충분)
- 진행 중 `SKIP` 이 보이는 건 정상입니다 (90일 미만 심볼은 제외됨)

끝나면 QA 결과를 보세요:

```bash
python -c "import json;d=json.load(open('facts/QA_PANEL.json',encoding='utf-8'));print(sum(1 for x in d if x['usable']),'usable /',len(d))"
```

이어서 펀딩비 데이터를 받습니다. **네트워크 작업이라 오래 걸립니다 (약 30~60분).**
백그라운드로 돌려놓고 STEP 2를 진행하세요.

```bash
python -c "import sys;sys.path.insert(0,'.');from orc.facts import panel,fetch_vision as fv;fv.fetch_funding_for(panel.available_symbols('1h'))"
```

---

## STEP 2 — GitHub 저장소 만들기 (약 10분)

무료 24시간 연산은 **public 저장소**에서만 무제한입니다. private은 월 2,000분뿐이라
24시간 가동이 안 됩니다.

### 2-1. 저장소 생성

```bash
cd D:\Project\ORC
git init
git branch -M main
```

`.gitignore` 를 만듭니다 (데이터는 저장소에 넣지 않습니다):

```bash
cat > .gitignore <<'EOF'
facts/panel_1m/
facts/panel_1h/
facts/funding/
dist/
__pycache__/
*.pyc
.pytest_cache/
FINAL_TEST_TOKEN
EOF
```

```bash
git add -A
git commit -m "ORC: DCA research infrastructure"
gh auth login          # 브라우저 인증. 이미 로그인돼 있으면 건너뛰세요
gh repo create orc --public --source=. --push
```

> **공개해도 되는 이유:** 저장소에 들어가는 건 범용 엔진과 워크플로뿐입니다.
> 가격 데이터도, 살아남은 전략 설정도 들어가지 않습니다. 알파가 생기면 그때
> `configs/registry/` 만 private 저장소로 분리하면 됩니다.

### 2-2. 워커에게 줄 데이터 번들 업로드

```bash
python scripts/deploy_panel.py
gh release create panel-latest dist/orc-panel.tar.gz dist/orc-panel.sha256 ^
  --title "ORC panel" --notes "development data only"
```

이 번들에는 **2024-03-01 이후 데이터가 물리적으로 들어있지 않습니다.** 클라우드
워커가 코드 버그로도 홀드아웃을 볼 수 없게 만든 장치입니다.

패널을 다시 만들 때마다 갱신하세요:

```bash
python scripts/deploy_panel.py
gh release upload panel-latest dist/orc-panel.tar.gz --clobber
```

### 2-3. Actions 쓰기 권한 켜기

브라우저에서 저장소를 열고:

```
Settings → Actions → General → Workflow permissions
  → "Read and write permissions" 선택 → Save
```

이게 없으면 워커가 결과를 커밋하지 못합니다.

### 2-4. 첫 실행 확인

```bash
gh workflow run orc-cycle.yml
gh run watch
```

성공하면 6시간마다 자동으로 돕니다. **PC를 꺼도 계속 돕니다.**

---

## STEP 3 — 추론 계층 등록 (완료됨, 로컬 작업 스케줄러)

여기가 "아이디어를 계속 바꿔가며" 담당하는 계층입니다.

원래 계획은 Anthropic 클라우드의 `/schedule` 루틴이었습니다. **이 계정에서는
불가능합니다.** Team/Enterprise 플랜은 조직 Owner가 `Admin settings > Connectors`
에서 GitHub 커넥터를 켜야 클라우드 세션이 저장소에 닿는데, Innobase 조직은 이게
꺼져 있고 계정 역할이 `user` 라 직접 켤 수 없습니다. 우회로인 `/web-setup` 도
`allow_quick_web_setup: false` 로 같이 막혀 있습니다. 개인 Max 계정으로 전환하면
클라우드 루틴이 가능해지고, 그때는 이 STEP을 `/schedule` 로 되돌리면 됩니다.

그래서 추론 계층만 로컬로 내렸습니다. 평가는 그대로 GitHub Actions가 합니다.

| | |
|---|---|
| 작업 이름 | `ORC Reasoning Cycle` |
| 실행 | 매일 00:00 KST |
| 스크립트 | `scripts/reasoning_cycle.ps1` |
| 프롬프트 | `scripts/reasoning_prompt.txt` |
| 모델 | `claude-opus-5` |
| 허용 도구 | `Read`, `Glob`, `Grep`, `Write`, `Edit`, `Bash(git *)` |
| 로그 | `logs/reasoning_YYYY-MM-DD.log` (커밋 안 됨) |

**대가: 00:00 KST에 PC가 켜져 있어야 합니다.** 꺼져 있었다면
`StartWhenAvailable` 설정 때문에 다음 부팅 직후 한 번 따라잡습니다.

상태 확인과 수동 실행:

```powershell
Get-ScheduledTaskInfo -TaskName "ORC Reasoning Cycle" | Select-Object LastRunTime, LastTaskResult, NextRunTime
Start-ScheduledTask -TaskName "ORC Reasoning Cycle"     # 지금 한 번 돌리기
```

프롬프트를 바꾸려면 `scripts/reasoning_prompt.txt` 만 고치면 됩니다. 스케줄러는
건드릴 필요 없습니다.

멈추려면:

```powershell
Disable-ScheduledTask -TaskName "ORC Reasoning Cycle"
```

추론 계층이 커밋하면 GitHub Actions가 6시간 안에 집어가서 평가합니다.
**이걸로 루프가 닫힙니다.**

---

## STEP 4 — 봉인 홀드아웃 (평생 3번, 지금은 하지 마세요)

최종 후보가 나왔을 때만, 그리고 **일생에 3번만** 가능합니다.

```bash
# 이 파일을 직접 손으로 만들어야만 열립니다
notepad D:\Project\ORC\FINAL_TEST_TOKEN
```

정확히 이 두 줄을 넣으세요 (한 글자라도 다르면 거부됩니다):

```
I am opening the sealed holdout. I understand this consumes one of three
openings for the life of this project and cannot be undone.
```

사용하면 토큰 파일은 **자동 삭제**되고, 후보 해시가 `ledger/FINAL_TEST_LOG.jsonl`
에 영구 기록됩니다. 3회를 다 쓰면 프로젝트가 끝날 때까지 다시 열리지 않습니다.

> 지금 이 단계를 하지 마세요. 후보가 없습니다.

---

## 선택 사항

### Oracle Cloud 상시 무료 VM
GitHub Actions가 6시간마다 재시작되는 게 불편하면 상시 VM을 쓸 수 있습니다.
2026-06-15부터 2 OCPU / 12GB로 축소됐고 용량 확보 실패가 잦습니다.
안 되면 미련 없이 건너뛰세요 — Actions만으로 충분합니다.

### Hetzner CX22 (월 약 €4)
Oracle 용량 싸움이 싫으면 이쪽이 가장 편합니다. 삽질 대비 가성비가 제일 좋습니다.

### 1분봉 클라우드 배포
현재 번들은 1시간봉만 담습니다(9심볼 기준 9.6MB, 481심볼이면 약 500MB).
1분봉은 36GB라 클라우드에 올리지 않습니다. **최종 후보의 체결 현실성 검증만
로컬에서** 하면 되므로 문제없습니다.

---

## 매일 무슨 일이 벌어지는가

```
00:00 KST   추론 계층 (로컬 스케줄러)   새 가설 1~3개 → configs/queue/ 커밋
00:00~      GitHub Actions (6시간마다)  큐 수거 → 사전등록 해시 → 전 그리드 평가
            (public 저장소, 무제한 무료)  → 원장 기록 → 반응표면 + PBO
                                        → reports/ 커밋
다음날      추론 계층이 CYCLE_REPORT.md 읽고 다음 질문 결정
```

**00:00 KST에만 PC가 켜져 있으면 됩니다. 평가는 PC와 무관하게 돕니다. 총 비용 ₩0.**

당신이 개입해야 할 때는 두 번뿐입니다:
1. 패널을 갱신할 때 (`deploy_panel.py` + `gh release upload`)
2. 최종 시험을 열 때 (STEP 4)

---

## 문제가 생기면

| 증상 | 원인 | 조치 |
|---|---|---|
| Actions가 `panel-latest` 를 못 찾음 | 릴리스 미업로드 | STEP 2-2 |
| Actions가 커밋 실패 | 쓰기 권한 없음 | STEP 2-3 |
| `test_analytic_matches_simulator` 실패 | 두 평가기가 어긋남 | **다른 모든 작업 중단.** 모든 결과가 무효입니다 |
| `HoldoutViolation` | 봉인 구간이 새어들어옴 | 정상 동작. `panel.load()` 를 쓰지 않은 코드가 있는지 확인 |
| 큐 파일이 `rejected/` 로 감 | 스키마 오류 | `configs/queue/rejected/` 에서 원인 확인 |
| 아침에 새 가설이 없음 | 00:00에 PC가 꺼져 있었음 | `logs/reasoning_*.log` 확인. 없으면 `Start-ScheduledTask -TaskName "ORC Reasoning Cycle"` |
