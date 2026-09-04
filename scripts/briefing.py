"""ORC | 연구 브리핑: 어디까지 왔고, 지금 가장 좋은 것은 무엇이며, 왜 아직 전략이 아닌가.

health.py는 "기계가 살아 있나"에 답한다. status.py는 표와 숫자를 보여준다.
둘 다 답하지 않는 질문이 남는다 — **그래서 무엇을 알아냈고, 다음은 무엇인가.**

이 파일은 새로 탐색하지 않는다.  status.py의 주석이 말하는 그대로,
원장에서 최댓값을 사냥하는 것은 이 프로토콜 전체가 억제하려는 선택 편향이고
편의 명령이 바로 그것이 스며드는 경로다.  그래서 여기서 하는 일은
**각 가족이 자기 사전등록된 리포트에서 이미 지목한 최고 셀**을 읽어
한글로 옮기고, 실격 사유를 빠짐없이 붙이는 것뿐이다.
가족 간 순위표는 만들지 않는다 — 그것이 곧 "골라잡기"이기 때문이다.

  python scripts/briefing.py              짧은 판 (기본, 30줄 내외)
  python scripts/briefing.py --full       전체 판
  python scripts/briefing.py --write      reports/BRIEFING.md 에도 기록

`--write` 는 사이클이 매번 갱신할 수 있게 하려는 것이다.  저장소에 커밋되면
휴대폰의 GitHub 앱에서도 읽을 수 있고, 그것이 이 프로젝트를 지켜보는 가장
낮은 마찰의 방법이다.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    sys.stdout.reconfigure(errors="replace")
except (AttributeError, OSError):                                  # pragma: no cover
    pass

from orc import config, runstate                                   # noqa: E402
from orc.orchestrator.verdict import disqualifiers                 # noqa: E402

KST = timezone(timedelta(hours=9))

# 실격 사유를 한글로.  verdict.py가 내는 영어 문구를 그대로 옮긴다 --
# 새 판정을 만들지 않고 번역만 한다.
WHY_KO = {
    "spike": "SPIKE — 이웃 셀이 더 나쁘고 부호도 반대인 봉우리. 메커니즘이 아니라 격자의 모서리",
    "shape unmeasured": "shape 미측정 — 격자에 3단계 이상 수치 축이 없어 진단 자체가 불가",
    "PBO unmeasured": "PBO 미측정 — 같은 horizon을 공유하는 설정이 2개 미만",
    "search test unmeasured": "서치 테스트 미측정",
    "at or below": "손익분기 이하",
    "paths": "독립 경로 부족 — 겹치는 시작일은 별개의 실험이 아니다",
    "PBO": "PBO — 0.5에서 선택은 아무 정보도 담지 않는다",
    "vs a random search": "무작위 탐색과 구별 불가",
}


def _ko_why(reasons: list[str]) -> list[str]:
    out = []
    for r in reasons:
        hit = next((v for k, v in WHY_KO.items() if k in r), None)
        out.append(f"{r}  ({hit})" if hit else r)
    return out


def describe_a(cfg: dict, fixed: dict) -> str:
    """트랙 A 셀을 한글 한 문단으로.  실제로 무엇을 하는 규칙인가."""
    g = {**fixed, **cfg}
    amt = g.get("contribution", 100.0)
    stride = g.get("stride_days", 7.0)
    n = g.get("n_contributions", 52)
    total_days = (n - 1) * stride
    lev = g.get("leverage", 1.0)
    gate = g.get("gate", "none")
    parts = [f"{amt:,.0f} USDT를 {stride:g}일마다 {n}번 매수",
             f"(총 {amt * n:,.0f} USDT, 약 {total_days / 365:.1f}년에 걸쳐)"]
    if gate in ("none", "", None):
        parts.append("— 가격을 보지 않고 일정대로만")
    else:
        kind, *rest = str(gate).split(":")
        if kind == "dip":
            parts.append(f"— 단, 직전 {rest[1]}일 최고가에서 "
                         f"{float(rest[0]) * 100:.0f}% 이상 하락한 봉에서만 집행")
        elif kind == "sma":
            parts.append(f"— 단, {rest[0]}일 이동평균 아래인 봉에서만 집행")
    if lev != 1.0:
        parts.append(f"레버리지 {lev:g}배")
    if g.get("stop_loss") is not None:
        parts.append(f"증거금의 {g['stop_loss'] * 100:.0f}% 손실에서 손절")
    if g.get("take_profit") is not None:
        parts.append(f"증거금의 {g['take_profit'] * 100:.0f}% 이익에서 익절")
    parts.append("펀딩 비용 포함" if g.get("include_funding") else
                 "**펀딩 비용 제외** (perpetual에서는 실제로 낼 수 없는 조건)")
    parts.append("만기까지 보유")
    return ", ".join(parts) + "."


def describe_b(cfg: dict, fixed: dict) -> str:
    """트랙 B 셀을 한글 한 문단으로."""
    g = {**fixed, **cfg}
    rule = g.get("rule", "?")
    side = "공매도" if rule == "carry_funding" else "매수"
    lb = g.get("lookback_days", 21)
    enter = g.get("enter_rate", 0.0)
    exit_r = g.get("exit_rate", 5e-05)
    cap = g.get("capital", 10_000.0)
    lev = g.get("leverage", 1.0)
    cmp_ = "이상으로 비싸지면" if rule == "carry_funding" else "이하로 내려가면"
    parts = [
        f"자본 {cap:,.0f} USDT 고정",
        f"직전 {lb:g}일 평균 펀딩 요율이 8시간당 {enter * 100:+.3f}% {cmp_} {side}",
        f"요율이 {exit_r * 100:+.3f}% 쪽으로 되돌아오면 청산",
        f"노출 {lev:g}배",
    ]
    if g.get("max_hold_days"):
        parts.append(f"최대 {g['max_hold_days']:g}일 보유")
    if g.get("stop_loss") is not None:
        parts.append(f"증거금의 {g['stop_loss'] * 100:.0f}% 손실에서 손절")
    mech = ("펀딩을 지불하는 쪽(레버리지 롱)에게서 쿠폰을 받는 것이 목적"
            if rule == "carry_funding" else
            "펀딩이 마이너스일 때, 즉 숏이 롱에게 지불할 때 롱을 잡는 것이 목적")
    return ", ".join(parts) + f". {mech}."


def _span(a: str | None, b: str | None) -> str:
    """How long a run took, from its own two timestamps."""
    ta, tb = runstate._utc(a), runstate._utc(b)
    if ta is None or tb is None:
        return "?"
    secs = int((tb - ta).total_seconds())
    if secs < 0:
        return "?"
    return f"{secs // 60}분 {secs % 60}초" if secs >= 60 else f"{secs}초"


def running_section() -> list[str]:
    """돌고 있는가, 그리고 마지막으로 실제 연구가 일어난 시각.

    이 파일은 커밋돼서 몇 시간 뒤에 휴대폰에서 읽힙니다.  그래서 여기 들어가는
    사실은 전부 **지속되는 것**입니다 — 파일과 시각.  "생성 시점에 실행 중이었다"
    는 문장이 바로 2026-09-03에 하루 종일 모든 화면을 초록색으로 유지한 것이고,
    그날 새로 물어진 질문은 하나도 없었습니다.

    두 시계를 나눠 적는 것이 요점입니다.  워커는 큐가 비어 있어도 6시간마다
    발화해서 리포트를 새로 쓰고 커밋합니다.  시행은 (설정, 심볼, 평가기, 패널,
    코드)로 중복 제거되므로 그 사이클은 **0행**을 넣고도 성공합니다.  그러니
    "워커가 돌았다"와 "연구가 됐다"는 다른 사실이고, 둘 다 적습니다.
    """
    now = datetime.now(timezone.utc)
    a = runstate.activity(now)
    L: list[str] = []
    L.append("## 지금 돌고 있는가")
    L.append("")
    L.append(f"{a['mark']} {a['headline']}")
    L.append("")
    for r in a["reasons"]:
        L.append(f"- {r}")
    L.append("")

    last_trial = a["last_new_trial"]
    attempt = a["last_attempt"] or {}
    passes = runstate.reasoning_passes(1)
    rt = a["reasoning_task"]

    L.append("| 무엇 | 언제 | 무슨 일이 있었나 |")
    L.append("|---|---|---|")
    if last_trial:
        L.append(f"| **마지막 신규 시행** (백테스트가 아무도 묻지 않았던 것에 "
                 f"답한 시각) | {runstate.kst(last_trial['last_utc'])} · "
                 f"{runstate.ago(last_trial['last_utc'], now)} | "
                 f"시행 {last_trial['trials']:,}건 추가 · "
                 f"{', '.join(last_trial['hypotheses'])} · "
                 f"소요 {_span(last_trial['first_utc'], last_trial['last_utc'])} |")
    else:
        L.append("| **마지막 신규 시행** | 기록 없음 | 원장에 행이 없습니다 |")
    if attempt:
        added = attempt.get("trials_added")
        L.append(f"| 마지막 워커 사이클 | "
                 f"{runstate.kst(attempt.get('started_utc'))} · "
                 f"{runstate.ago(attempt.get('started_utc'), now)} | "
                 f"소요 {_span(attempt.get('started_utc'), attempt.get('finished_utc'))} · "
                 f"신규 {'?' if added is None else format(added, ',')}건"
                 + ("  ← 돌았지만 새로 답한 것이 없음"
                    if added == 0 else "") + " |")
    L.append(f"| 다음 워커 발화 (명목) | "
             f"{runstate.kst(a['next_worker_slot'])} · "
             f"{runstate.until(a['next_worker_slot'], now)} | "
             f"6시간마다. 공개 저장소의 예약 실행은 2~4시간 지연이 흔합니다 |")
    if passes:
        p = passes[0]
        what = []
        if p.get("blocked"):
            what.append(f"거부됨 (high 결함 {len(p['blocked'])}건)")
        if p.get("registered"):
            what.append(f"등록 {len(p['registered'])}건")
        if p.get("killed"):
            what.append(f"적대자가 기각 {len(p['killed'])}건")
        if p.get("held"):
            what.append(f"심사 보류 {len(p['held'])}건")
        if p.get("unavailable"):
            what.append(f"판단 호출 실패 {len(p['unavailable'])}건")
        L.append(f"| 마지막 추론 패스 (아이디어 발굴) | "
                 f"{runstate.kst(p.get('utc'))} · "
                 f"{runstate.ago(p.get('utc'), now)} | "
                 f"{', '.join(what) or '아무것도 등록되지 않음'} |")
    elif rt:
        sev, note = runstate.task_result_note(rt.get("result"))
        L.append(f"| 마지막 추론 패스 (아이디어 발굴) | "
                 f"{runstate.task_time(rt.get('last'))} | {note} |")
    # 두 시계를 나눕니다.  "깨어났다"는 스케줄이 아직 발화한다는 뜻이고,
    # "물었다"는 질문이 실제로 등록됐다는 뜻입니다.  증거 게이트가 들어온 뒤로
    # 건너뛰는 것이 정상 동작이 됐으므로, 출력이 없다는 사실만으로는 기계가
    # 죽었는지 알 수 없습니다.
    wake = runstate.reasoning_wakeups(1)
    if wake:
        w = wake[0]
        note = (f"게이트: {w.get('why')}" if w.get("gate")
                else "파이프라인을 실행했습니다")
        L.append(f"| 추론 계층 마지막 기동 | "
                 f"{runstate.kst(w.get('utc'))} · "
                 f"{runstate.ago(w.get('utc'), now)} | {note} |")
    next_reason = (runstate.task_time(rt.get("next")) if rt and rt.get("next")
                   else runstate.kst(runstate.next_reasoning_slot(now)))
    L.append(f"| 다음 추론 발화 | {next_reason} | "
             f"매일 {', '.join(runstate.REASONING_SLOTS_KST)} KST. "
             "증거가 그대로면 스스로 건너뜁니다 |")
    L.append(f"| 대기 중인 질문 (큐) | — | "
             f"{len(a['queued'])}개"
             + (f": {', '.join(a['queued'])}" if a['queued'] else
                " — 다음 추론 패스가 만들 차례") + " |")
    L.append(f"| 열린 가족 | — | "
             f"{', '.join(a['open_families']) if a['open_families'] else '없음'} |")
    sup = a.get("supervisor") or {}
    L.append(f"| 24시간 감독자 | "
             f"{runstate.kst(sup.get('heartbeat_utc')) if sup.get('heartbeat_utc') else '기록 없음'} | "
             + ("살아 있음 (pid {}, 박동 {})".format(
                 sup.get("pid"), runstate.ago(sup.get("heartbeat_utc"), now))
                if sup.get("alive") else
                "**떠 있지 않습니다** — `python scripts/schedule.py --install` "
                "로 등록하거나 `python scripts/forever.py` 로 띄웁니다")
             + " |")
    act, act_why = a.get("next_action") or ("?", "")
    L.append(f"| 지금 할 일 | — | **{act}** — {act_why} |")
    L.append(f"| 24시간 등록 예산 | — | "
             f"{len(a.get('registrations_24h') or [])}/"
             f"{a.get('registration_budget')} 사용"
             + (f" ({', '.join(a['registrations_24h'])})"
                if a.get("registrations_24h") else "")
             + ". 제안·적대자 검토·웹 정찰은 N을 쓰지 않고, "
               "등록만 씁니다 |")
    L.append("")

    acts = runstate.activities(10)
    if acts:
        L.append("### 가동 기록 — 감독자가 실제로 한 일")
        L.append("")
        L.append("이 표가 비어 있거나 구멍이 나 있으면 감독자는 일하지 않은 "
                 "것입니다. `reason` 만 연구가 아닙니다 — `scout`(웹에서 새 "
                 "지불자 찾기), `kernel_review`(평가기 적대적 재독), "
                 "`robustness`, `execution_realism`, `survivorship` 은 모두 "
                 "원장에 한 줄도 더하지 않는 연구입니다.")
        L.append("")
        L.append("| 시각 (KST) | 한 일 | 소요 | 결과 |")
        L.append("|---|---|---|---|")
        for r in acts:
            secs = r.get("seconds")
            took = "—" if secs is None else (
                f"{secs / 60:.0f}분" if secs >= 60 else f"{secs:.0f}초")
            L.append(f"| {runstate.kst(r.get('utc'))} | "
                     f"`{r.get('action')}` | {took} | "
                     f"{str(r.get('detail'))[:150].replace('|', '/')} |")
        L.append("")

    scout_nb = config.REPORTS / "SCOUT.jsonl"
    if scout_nb.exists():
        rows = runstate._read_jsonl(scout_nb, 6, "utc")
        total = len(runstate._read_jsonl(scout_nb, 10_000, "utc"))
        L.append(f"### 정찰 노트북 — 외부에서 모은 지불자 {total}명")
        L.append("")
        L.append("제안자의 도구는 `Read/Glob/Grep/Write` 뿐이라 저장소 안의 "
                 "것만 재배열할 수 있고, 그래서 첫 여덟 가족 중 여섯이 펀딩 "
                 "요율에 얹혀 있었습니다. 이 노트북은 웹과 두 번째 벤더에서 "
                 "**지불자**를 모아 그 구멍을 막습니다. 성능 숫자는 규칙으로 "
                 "금지돼 있습니다 — 이 파일을 읽는 단계는 이 프로젝트의 결과를 "
                 "보지 않아야 하기 때문입니다.")
        L.append("")
        L.append("| 언제 | 출처 | 확신 | 누가 지불하는가 |")
        L.append("|---|---|---|---|")
        for r in rows:
            need = " ⚠︎ 보유 데이터 부족" if r.get("needs_data_we_lack") else ""
            L.append(f"| {runstate.kst(r.get('utc'))} | {r.get('provider')} | "
                     f"{r.get('confidence')} | "
                     f"{str(r.get('payer'))[:150].replace('|', '/')}{need} |")
        L.append("")

    tl = runstate.timeline(8)
    if tl:
        L.append("### 가동 기록 — 최근 사이클")
        L.append("")
        L.append("`+0`은 고장이 아닙니다. 워커는 큐가 비어 있어도 발화하고, "
                 "이미 답한 셀은 중복 제거되므로 **아무것도 새로 묻지 않은 "
                 "사이클**이 그렇게 보입니다. 이 표의 목적은 그 줄이 몇 개나 "
                 "연달아 있는지 보이게 하는 것입니다.")
        L.append("")
        L.append("| 시작 (KST) | 소요 | 신규 시행 | 가설 |")
        L.append("|---|---|---|---|")
        for r in tl:
            added = r.get("trials_added")
            # 원장에서 온 줄은 첫 행과 마지막 행의 간격, 즉 평가에 걸린 시간만
            # 압니다.  체크아웃·설치·패널 다운로드는 그 앞에 있고 원장에 흔적을
            # 남기지 않으므로, 두 숫자를 같은 열에 말없이 섞으면 사이클이
            # 실제보다 짧아 보입니다.
            span = _span(r.get("started_utc"), r.get("finished_utc"))
            if r.get("source") == "ledger":
                span += " (평가만)"
            L.append(f"| {runstate.kst(r.get('started_utc'))} | {span} | "
                     f"{'?' if added is None else format(added, '+,d')} | "
                     f"{', '.join(r.get('hypotheses_run') or []) or '—'} |")
        L.append("")

    rp = runstate.reasoning_passes(6)
    if len(rp) > 1:
        L.append("### 가동 기록 — 최근 추론 패스")
        L.append("")
        L.append("| 시각 (KST) | 등록 | 기각 | 거부/보류 |")
        L.append("|---|---|---|---|")
        for p in rp:
            block = []
            if p.get("blocked"):
                block.append(f"high 결함 {len(p['blocked'])}건으로 거부")
            if p.get("held"):
                block.append(f"보류 {len(p['held'])}건")
            if p.get("unavailable"):
                block.append(f"판단 불가 {len(p['unavailable'])}건")
            L.append(f"| {runstate.kst(p.get('utc'))} | "
                     f"{len(p.get('registered') or [])} | "
                     f"{len(p.get('killed') or [])} | "
                     f"{', '.join(block) or '—'} |")
        L.append("")

    due, why = a["reasoning_due"]
    L.append(f"**다음 패스가 실제로 물을 것인가**: "
             f"{'예' if due else '아니오'} — {why}")
    L.append("")
    return L


def _postmortem_gist(name: str | None) -> str:
    """부검의 첫 산문 문단.  부검은 한글로 쓰여 있으므로 번역이 아니라 인용이다."""
    if not name:
        return ""
    p = config.REPORTS / name
    if not p.exists():
        return ""
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for line in lines:
        t = line.strip()
        # 제목, 표, 목록, 코드 울타리는 건너뛰고 실제 문장을 찾는다.
        if not t or t[0] in "#|-*>`" or t.startswith("---"):
            continue
        if len(t) < 40:
            continue
        return t[:300] + ("…" if len(t) > 300 else "")
    return ""


def _load(name: str):
    p = config.REPORTS / name
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return None


# 짧은 판의 실격 사유. WHY_KO 는 한 줄에 60자를 쓰는 설명문이고, 그것을 네
# 가족에 붙이면 브리핑이 다시 길어진다. 여기서는 라벨만 쓴다 -- 설명은
# `--full` 과 status.py 에 그대로 남아 있다.
WHY_SHORT = {
    "spike": "SPIKE",
    "shape unmeasured": "shape 미측정",
    "PBO unmeasured": "PBO 미측정",
    "path count unmeasured": "paths 미측정",
    "search test unmeasured": "서치 미측정",
    "at or below 0": "0 이하",
    "at or below 1": "1 이하",
}


def _why_short(reasons: list[str]) -> str:
    out = []
    for w in reasons:
        if w in WHY_SHORT:
            out.append(WHY_SHORT[w])
        else:
            # "p=0.725 vs a random search" -> "p=0.725", "PBO 0.52" 는 그대로
            out.append(w.split(" vs ")[0])
    return ", ".join(out)


def build_short() -> str:
    """폰에서 읽는 길이. 답해야 하는 질문은 셋뿐이다 -- 돌고 있나, 어디까지
    왔나, 다음은 무엇인가.

    긴 판은 지웠기 때문에 짧아진 것이 아니다. 180줄에 13,433자를 읽는 사람은
    아무도 없고, 읽히지 않는 브리핑은 없는 브리핑과 같다. 자세한 것은 남아
    있다: `--full`, `python scripts/status.py`, `reports/CYCLE_REPORT.md`.
    """
    import contextlib
    import io

    from orc import holdout
    from orc.orchestrator.spec import closed_families, load_registry

    with contextlib.redirect_stdout(io.StringIO()):
        open_h = load_registry()
    closed = closed_families()
    open_ids = [h.hypothesis_id for h in open_h]

    try:
        from orc.ledger.trials import Ledger
        with Ledger() as led:
            n_trials, newest = led.total_trials(), led.newest_trial_utc()
    except Exception:                                              # noqa: BLE001
        n_trials, newest = 0, None

    L: list[str] = [f"# ORC 브리핑 — {datetime.now(KST):%Y-%m-%d %H:%M} KST", ""]

    # 기계가 먼저다. 결과를 먼저 읽게 하면 루프가 멈춰 있어도 어제와 똑같이
    # 읽히고, 실제로 그렇게 하루가 지나갔다.
    try:
        a = runstate.activity()
        mark = {runstate.RUNNING: "🟢", runstate.QUEUED: "🟢",
                runstate.WORKING: "🟢", runstate.IDLE: "🟡",
                runstate.STALLED: "🟠", runstate.STOPPED: "🔴"}.get(a["status"], "🟡")
        L.append(f"**루프** {mark} {a['status']} — "
                 + (a["reasons"][0] if a["reasons"] else "").split(" — ")[0][:80])
    except Exception as exc:                                       # noqa: BLE001
        L.append(f"**루프** 🟡 상태를 읽을 수 없음 ({type(exc).__name__})")

    L.append(f"**원장** N = {n_trials:,} · 새 질문이 마지막으로 답된 것 "
             f"{runstate.ago(newest)} · 열린 가족 "
             f"{', '.join(open_ids) or '없음'} · 닫힌 가족 {len(closed)}개")

    tgt = _load("TARGET.json") or {}
    if tgt:
        t = tgt.get("target", {})
        best = tgt.get("best_cagr") or {}
        L.append(f"**종료 조건** CAGR {t.get('cagr', 0):.0%} / MDD "
                 f"{t.get('max_drawdown', 0):.0%} → **{tgt.get('state')}**"
                 + (f" · 최고 {best['cagr']:+.1%} (MDD {best['max_drawdown']:.0%},"
                    f" {best['hypothesis_id']} {best['symbol']})" if best else ""))

    survived = []
    for hid in open_ids:
        rep = _load(f"{hid}_SURFACE.json")
        if rep is None:
            continue
        pbo_ok = {sy: r.get("pbo") for sy, r in (rep.get("pbo") or {}).items()
                  if r.get("status") == "ok" and r.get("covers_reported_best")}
        search = rep.get("search_test") or {}
        for sym, srf in (rep.get("surfaces") or {}).items():
            if not disqualifiers(srf, rep["metric"], pbo_ok.get(sym), search.get(sym)):
                survived.append(f"{hid}/{sym}")
    if survived:
        L.append(f"**전략** 모든 검사를 통과한 셀 {len(survived)}개: "
                 f"{', '.join(survived)} — `python scripts/robustness.py` 확인 필수")
    else:
        L.append("**전략** 없음. 모든 검사를 통과한 셀 0개 — "
                 "`FAIL`이 이 프로젝트의 산출물입니다")

    L.append(f"**홀드아웃** {holdout.openings_used()}/{holdout.MAX_FINAL_TESTS} 개봉, "
             f"{config.HOLDOUT_START}부터 봉인")

    mut = _load("MUTATION.json") or {}
    if mut.get("survived"):
        L.append(f"**뮤테이션** ⚠ 결함 {len(mut['survived'])}개를 테스트가 못 잡음 "
                 f"({', '.join(mut['survived'][:2])}) — 코드가 아니라 테스트의 구멍")

    # 가족별 최고 셀 -- 자기 사전등록 리포트가 지목한 것만. 가족 간 순위는
    # 만들지 않는다. 그것이 골라잡기다.
    L.append("")
    L.append("## 가장 좋은 셀과 실격 사유")
    L.append("")
    for hid in open_ids + sorted(closed):
        rep = _load(f"{hid}_SURFACE.json")
        if rep is None:
            continue
        metric = rep.get("metric", "tm_q05")
        pbo_ok = {sy: r.get("pbo") for sy, r in (rep.get("pbo") or {}).items()
                  if r.get("status") == "ok" and r.get("covers_reported_best")}
        search = rep.get("search_test") or {}
        surfaces = rep.get("surfaces") or {}
        if not surfaces:
            continue
        sym, srf = max(surfaces.items(), key=lambda kv: kv[1].get("best_value") or -9e9)
        why = disqualifiers(srf, metric, pbo_ok.get(sym), search.get(sym))
        state = "닫힘" if hid in closed else "진행"
        L.append(f"- **{hid}** `{rep.get('family')}` ({state}) {sym} "
                 f"{metric} {srf['best_value']:+.4f} — "
                 + (_why_short(why) if why else "이 검사들은 통과"))

    L.append("")
    L.append("## 다음")
    L.append("")
    queued = sorted(p.stem for p in config.QUEUE.glob("*.json")) \
        if config.QUEUE.exists() else []
    if queued:
        L.append(f"- 큐: {', '.join(queued)} — 워커가 평가할 차례")
    try:
        action, why = runstate.next_action()
        L.append(f"- 감독자: **{action}** — {why.split('. ')[0][:90]}")
    except Exception:                                              # noqa: BLE001
        pass
    L.append("- 자세히: `python scripts/briefing.py --full` · "
             "`python scripts/watch.py` · `python scripts/status.py`")
    return "\n".join(L) + "\n"


def build() -> str:
    import contextlib
    import io
    from orc.orchestrator.spec import closed_families, load_registry

    with contextlib.redirect_stdout(io.StringIO()):
        open_h = load_registry()
    closed = closed_families()
    open_ids = [h.hypothesis_id for h in open_h]
    fixed_by = {h.hypothesis_id: h.fixed for h in open_h}
    for hid in closed:
        p = config.REGISTRY / f"{hid}.json"
        if p.exists():
            fixed_by[hid] = json.loads(p.read_text(encoding="utf-8")).get("fixed", {})

    try:
        from orc.ledger.trials import Ledger
        with Ledger() as led:
            n_trials = led.total_trials()
            newest = led.newest_trial_utc()
    except Exception:                                              # noqa: BLE001
        n_trials, newest = 0, None

    L: list[str] = []
    now = datetime.now(KST)
    L.append(f"# ORC 연구 브리핑 — {now:%Y-%m-%d %H:%M} KST")
    L.append("")

    # 기계 상태가 첫 번째입니다.  연구 결과를 먼저 읽게 하면 루프가 멈춰 있어도
    # 어제와 똑같이 읽히고, 실제로 그렇게 하루가 지나갔습니다.
    L.extend(running_section())

    # ── 한 줄 요약 ────────────────────────────────────────────────────────
    survived = []
    for hid in open_ids:
        rep = _load(f"{hid}_SURFACE.json")
        if rep is None:
            continue
        pbo_ok = {s: r.get("pbo") for s, r in (rep.get("pbo") or {}).items()
                  if r.get("status") == "ok" and r.get("covers_reported_best")}
        search = rep.get("search_test") or {}
        for sym, srf in (rep.get("surfaces") or {}).items():
            if not disqualifiers(srf, rep["metric"], pbo_ok.get(sym), search.get(sym)):
                survived.append((hid, sym))

    L.append("## 한 줄 요약")
    L.append("")
    if survived:
        L.append(f"**모든 검사를 통과한 셀이 {len(survived)}개 있습니다**: "
                 + ", ".join(f"{h}/{s}" for h, s in survived)
                 + ". 아래 '가장 좋은 셀'에서 확인하고, "
                 "`python scripts/robustness.py` 게이트를 통과했는지 반드시 보십시오.")
    else:
        L.append(f"**지금 실전에 쓸 수 있는 전략은 없습니다.** 시행 {n_trials:,}건을 "
                 f"기록했고 모든 검사를 통과한 셀은 0개입니다. "
                 f"닫힌 가족 {len(closed)}개가 **왜** 안 되는지가 현재까지의 성과입니다 — "
                 "이 프로젝트의 산출물은 '되는 것 하나'가 아니라 "
                 "'어디서 깨지는지의 지도'이고, `FAIL`은 발표 가능한 결과입니다.")
    L.append("")

    # ── 종료 조건 ─────────────────────────────────────────────────────────
    # 소유자가 정한 정지 조건이고, 이 브리핑에서 가장 먼저 확인하고 싶은 것.
    # 사이클이 써 둔 reports/TARGET.json 만 읽는다 -- 이 파일의 원칙대로
    # 원장을 직접 뒤지지 않는다.
    tgt = _load("TARGET.json")
    if tgt:
        t = tgt.get("target", {})
        L.append("## 연구 종료 조건까지의 거리")
        L.append("")
        L.append(f"- 종료 조건: **CAGR {t.get('cagr', 0):.0%} 이상, "
                 f"MDD {t.get('max_drawdown', 0):.0%} 이하**를 만족하는 규칙이 "
                 f"여러 차례 검증을 통과할 때 (Calmar "
                 f"{(t.get('cagr', 0) / max(t.get('max_drawdown', 1), 1e-9)):.0f} "
                 "이상에 해당). 이것은 정지 조건이지 개별 결과를 재는 잣대가 "
                 "아닙니다 — 실패한 가족은 여전히 실패로 발표됩니다.")
        L.append(f"- 현재 상태: **{tgt.get('state')}** — {tgt.get('headline')}")
        best = tgt.get("best_cagr")
        if best:
            L.append(f"- 지금까지 최고 CAGR: **{best['cagr']:+.1%}** "
                     f"(MDD {best['max_drawdown']:.1%}, {best['hypothesis_id']} "
                     f"{best['symbol']}) — 목표는 두 조건을 **동시에** 요구합니다.")
        near = tgt.get("best_cagr_within_drawdown")
        if near:
            L.append(f"- MDD {t.get('max_drawdown', 0):.0%} 이내에서 최고 CAGR: "
                     f"**{near['cagr']:+.1%}** (MDD {near['max_drawdown']:.1%}, "
                     f"{near['hypothesis_id']} {near['symbol']})")
        for c in tgt.get("candidates", []):
            missing = ", ".join(c["failed"] + c["unmeasured"]) or "없음"
            L.append(f"- 후보 {c['hypothesis_id']} `{c.get('family')}` — "
                     f"심볼 {len(c['symbols'])}개, 남은 검증: {missing}")
        L.append("")

    # ── 지금까지 ──────────────────────────────────────────────────────────
    L.append("## 지금까지 무엇을 확립했는가")
    L.append("")
    L.append("### 사전 킬 테스트 (가설 이전에 확정된 것)")
    L.append("")
    L.append("- **KT-1 펀딩 드래그**: 3년 주간 DCA에서 펀딩 청구서 중위값이 "
             "**납입자본의 36%**, BTC 정산의 87%가 양수. → **perpetual 롱 DCA 종결.** "
             "시뮬레이터로 재라우팅하면 더 나쁩니다: 펀딩 포함 1배 롱이 "
             "ADAUSDT 시작일의 69%, SOLUSDT의 82%에서 **청산**됩니다.")
    L.append("- **KT-2 마틴게일**: **2배 이상에서 청산률 100%.** → 물타기에 "
             "레버리지 1배 초과 종결.")
    L.append("- **KT-3 생존 편향**: 거래된 적 있는 심볼 986개, 아카이브 481개, "
             "상장폐지 266개. 사용 가능한 폐지 표본이 아직 너무 작음 → "
             "**결론 없음.** 해결 전까지 알트 바스켓 가설 금지.")
    L.append("")

    if closed:
        L.append("### 닫힌 가족 — 시도했고, 왜 깨졌는지 기록됨")
        L.append("")
        for hid, rec in sorted(closed.items()):
            L.append(f"**{hid} `{rec.get('family')}`**")
            L.append("")
            clause = " ".join(str(rec.get("clause") or "").split())
            if clause:
                L.append(f"- 발동한 조항 (사전등록 원문): {clause[:260]}"
                         f"{'…' if len(clause) > 260 else ''}")
            # 종결 근거는 기록이므로 번역하지 않는다. 부검은 이미 한글로
            # 쓰여 있으니 그 첫 문단을 요지로 인용한다 -- 새로 쓰는 것보다
            # 기록을 가리키는 편이 정직하다.
            gloss = _postmortem_gist(rec.get("postmortem"))
            if gloss:
                L.append(f"- 요지: {gloss}")
            reason = " ".join(str(rec.get("reason", "")).split())
            L.append(f"- 종결 근거(원문, 번역하지 않음): {reason[:320]}"
                     f"{'…' if len(reason) > 320 else ''}")
            if rec.get("unevaluable_clauses"):
                L.append(f"- **평가 불가였던 조항 "
                         f"{len(rec['unevaluable_clauses'])}건** — 통과한 것이 "
                         "아니라 물어볼 수 없었던 것")
            pm = rec.get("postmortem")
            if pm:
                L.append(f"- 부검 전문: `reports/{pm}`")
            L.append("")

    # ── 가장 좋은 셀 ──────────────────────────────────────────────────────
    L.append("## 현재까지 가장 좋은 셀 — 그리고 왜 아직 전략이 아닌가")
    L.append("")
    L.append("각 가족이 **자기 사전등록된 리포트에서 이미 지목한** 최고 셀입니다. "
             "원장을 새로 뒤져 찾은 것이 아니고, 가족 간 순위도 매기지 않습니다 — "
             "그 두 가지가 이 프로토콜이 막으려는 골라잡기입니다. "
             "등록 순서대로 나열합니다.")
    L.append("")

    for hid in sorted(set(open_ids) | set(closed)):
        rep = _load(f"{hid}_SURFACE.json")
        if rep is None:
            continue
        surfaces = rep.get("surfaces") or {}
        if not surfaces:
            continue
        track = rep.get("track", "A")
        metric = rep["metric"]
        pbo_ok = {s: r.get("pbo") for s, r in (rep.get("pbo") or {}).items()
                  if r.get("status") == "ok" and r.get("covers_reported_best")}
        search = rep.get("search_test") or {}

        # 가족 안에서만, 그 가족의 자기 지표로 최고 셀 하나.
        sym, srf = max(surfaces.items(), key=lambda kv: kv[1].get("best_value") or -9e9)
        state = "닫힘" if hid in closed else "진행 중"
        L.append(f"### {hid} `{rep.get('family')}` — {state} (트랙 {track})")
        L.append("")
        claim = " ".join(str(rep.get("claim", "")).split())
        L.append(f"- **무엇을 물었나**: {claim[:400]}{'…' if len(claim) > 400 else ''}")
        cfg = srf.get("best_config") or {}
        desc = describe_b(cfg, fixed_by.get(hid, {})) if track == "B" \
            else describe_a(cfg, fixed_by.get(hid, {}))
        L.append(f"- **가장 좋았던 규칙** ({sym}): {desc}")
        hd = srf.get("headline") or {}
        r_pa, mdd = hd.get("return_pa"), hd.get("mdd")
        basis = "투입자본 대비" if hd.get("mdd_kind") == "invested" else "자기자본 대비"
        L.append(f"- **성과**: 연 수익률 "
                 f"{'n/a' if r_pa is None else format(r_pa * 100, '+.1f') + '%'}, "
                 f"최대 낙폭 "
                 f"{'n/a' if mdd is None else format(mdd * 100, '.1f') + '%'} ({basis})"
                 + (f", {metric} {srf['best_value']:+.4f}"))
        paths = srf.get("independent_paths_best")
        L.append(f"- **근거의 두께**: 독립 경로 "
                 f"{'n/a' if paths is None else format(paths, 'g')}개"
                 + (f", 이 가족 시행 {rep.get('trials_in_family')}건"))
        why = disqualifiers(srf, metric, pbo_ok.get(sym), search.get(sym))
        if why:
            L.append(f"- **전략이 아닌 이유**:")
            for w in _ko_why(why):
                L.append(f"    - {w}")
        else:
            L.append("- **실격 사유 없음** — robustness 게이트를 확인하십시오.")
        L.append("")

    # ── 다음 ──────────────────────────────────────────────────────────────
    L.append("## 다음에 할 일")
    L.append("")
    queued = sorted(config.QUEUE.glob("*.json"))
    if open_ids:
        L.append(f"1. **열린 가족**: {', '.join(open_ids)}. 매 사이클마다 "
                 "자기 킬 조건에 대해 투표에 부쳐집니다.")
    else:
        L.append("1. **열린 가족이 없습니다.** 등록된 메커니즘이 전부 닫혔으므로, "
                 "다음 추론 패스는 **새 메커니즘을 명명해야** 하고 그렇지 않으면 "
                 "루프는 할 일이 없습니다.")
    if queued:
        L.append(f"2. **큐 대기**: {', '.join(p.stem for p in queued)} — "
                 "다음 워커 실행에서 등록·평가됩니다.")
    else:
        L.append("2. **큐가 비어 있습니다.** 다음 제안은 추론 패스가 만듭니다 "
                 f"(매일 {', '.join(runstate.REASONING_SLOTS_KST)} KST, "
                 "증거가 바뀌었을 때만).")
    L.append("3. **새 메커니즘의 첫 등록은 96셀 탐침으로 제한**됩니다. 살아남으면 "
             "새 id로 넓게 열거할 수 있습니다 — 깊이는 결과로 벌어야 합니다.")
    L.append("4. **펀딩 기반 제안은 재론 금지.** 롱·숏 양쪽 다리가 닫혔습니다. "
             "펀딩은 KT-1이 측정한 **비용**으로만 남고 신호로는 남지 않습니다.")

    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import findings as fl
        blocking = fl.blocking()
        gating = [f for f in fl.load()["findings"].values()
                  if f["status"] == "open" and f["severity"] == "medium"]
        if blocking:
            L.append(f"5. **차단 중**: high 결함 {len(blocking)}건이 열려 있어 "
                     "모든 사이클이 거부됩니다.")
        else:
            L.append(f"5. **차단 없음.** medium/low {len(gating)}건이 열려 있고, "
                     "그중 트랙 A 서치 테스트의 귀무모형 오설정이 판정 신뢰도에 "
                     "직접 걸립니다 (부트스트랩 95분위가 역사상 최댓값의 35배).")
    except Exception:                                              # noqa: BLE001
        pass

    L.append("")
    L.append("## 봉인된 홀드아웃")
    L.append("")
    try:
        from orc import holdout
        used = holdout.openings_used()
        L.append(f"**{used}/{holdout.MAX_FINAL_TESTS} 회 사용.** "
                 f"{config.HOLDOUT_START} 이후는 물리적으로 부재하며, "
                 "평생 3번만 열립니다. 통과한 셀이 0개인 지금 열 이유는 없습니다.")
    except Exception:                                              # noqa: BLE001
        pass
    L.append("")
    L.append(f"---")
    L.append(f"시행 {n_trials:,}건 (N), 마지막 신규 시행 "
             f"{'기록 없음' if not newest else newest[:19] + 'Z'}. "
             f"자세한 표는 `python scripts/status.py`, "
             f"기계 상태는 `python scripts/health.py`.")
    return "\n".join(L)


def main(argv: list[str]) -> int:
    # 짧은 것이 기본이다. 180줄 13,433자짜리 판은 폰에서 읽히지 않았고,
    # 읽히지 않는 브리핑은 없는 브리핑과 같다.
    text = build() if "--full" in argv else build_short()
    print(text)
    if "--write" in argv:
        out = config.REPORTS / "BRIEFING.md"
        out.write_text(text, encoding="utf-8")
        print(f"\n[written: {out}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
