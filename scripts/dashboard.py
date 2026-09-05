"""ORC | 한 화면으로 보는 연구소 상태.

`health.py`는 "고장났나", `briefing.py`는 "무엇을 알아냈나", `watch.py`는 "지금
무엇이 도는가"에 답한다. 셋 다 터미널이고 셋 다 이 프로젝트를 아는 사람을 위해
쓰였다. 남은 독자가 하나 있다 -- 소유자가 폰으로 열어서 **"잘 돌고 있나"** 한 번에
보고 싶을 때.

그래서 이 파일은 다른 화면과 다른 것을 한다: 숫자를 새로 계산하지 않고, 이미
기록된 것을 읽어 **설명과 함께** 그린다. 용어는 전부 풀어 쓴다 -- N이 무엇이고
가설이 무엇이고 왜 `FAIL`이 산출물인지 모르는 사람이 읽어도 무슨 일이 일어나고
있는지 알 수 있어야 한다.

아무것도 쓰지 않는다(HTML 한 장 말고는). 원장도 리포트도 건드리지 않는다.

    python scripts/dashboard.py            reports/DASHBOARD.html 생성
    python scripts/dashboard.py --open     생성하고 브라우저로 연다
"""
from __future__ import annotations

import html
import json
import sys
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    sys.stdout.reconfigure(errors="replace")
except (AttributeError, OSError):                                  # pragma: no cover
    pass
sys.path.insert(0, str(Path(__file__).resolve().parent))

from orc import config, runstate                                   # noqa: E402

KST = timezone(timedelta(hours=9))
OUT = config.REPORTS / "DASHBOARD.html"

# 여섯 단계. 헌법 9절이 서술하는 순서 그대로이고, 번호가 장식이 아니라 정보다 --
# 실제로 이 순서로만 진행하며 앞 단계를 건너뛸 수 없다.
STAGES = [
    ("후보 찾기", "누가 구조적으로 계속 돈을 내는지 밖에서 찾아옵니다",
     "웹과 두 번째 모델에게 '무엇을 사고파는 게 아니라, 누가 어쩔 수 없이 "
     "계속 손해를 보는가'를 묻습니다. 패턴이 아니라 사람을 찾습니다."),
    ("가설 제안", "그 후보를 반증 가능한 규칙과 사망 조건으로 바꿉니다",
     "'이 규칙이 이런 결과를 내면 이 가설은 죽는다'를 결과를 보기 <b>전에</b> "
     "적어둡니다. 나중에 기준을 옮길 수 없게 하려는 장치입니다."),
    ("반론 심사", "등록 전에 모델 둘이 그 가설을 죽여봅니다",
     "서로 다른 회사의 모델 둘이 각자 거부권을 갖습니다. 하나라도 죽이면 "
     "등록되지 않습니다. 통과보다 기각이 훨씬 많은 게 정상입니다."),
    ("백테스트", "심사를 통과한 규칙만 과거 데이터에 전부 돌립니다",
     "골라 돌리지 않고 격자 전체를 돌립니다. 잘 나온 것만 세면 우연을 "
     "실력으로 착각하기 때문입니다."),
    ("검증", "우연인지 진짜인지 거릅니다",
     "같은 폭의 무작위 탐색이 우연히 내는 최고 성적과 비교하고(서치테스트), "
     "고른 설정이 정보를 담고 있는지 보고(PBO), 1분봉으로 다시 체결해봅니다."),
    ("판정·종결", "미리 써둔 사망 조건과 대조하고 부검서를 남깁니다",
     "가문이 닫히는 것은 실패가 아니라 <b>결과</b>입니다. 이 프로젝트의 산출물은 "
     "'어디서 깨지는가'의 지도이지 '무엇이 잘 되는가'가 아닙니다."),
]

ACTION_STAGE = {"scout": 0, "reason": 2, "cycle": 3,
                "robustness": 4, "execution_realism": 4, "survivorship": 4}

ACTION_KO = {
    "scout": "새 후보 찾는 중", "reason": "가설 제안·심사 중",
    "cycle": "백테스트 도는 중", "robustness": "비용·시기별 검증 중",
    "execution_realism": "1분봉으로 재현 중", "survivorship": "상장폐지 표본 확대 중",
    "kernel_review": "평가기 감사 중", "mutation": "테스트 자체를 검사 중",
    "rest": "다음 작업 대기", "blocked": "결함 때문에 멈춤", "done": "종료 조건 달성",
}

GLOSSARY = [
    ("N", "지금까지 돌린 백테스트 총 횟수. 많이 시도할수록 우연히 좋아 보이는 게 "
          "나오므로, 결과를 판단할 때 이 숫자로 기준을 높입니다. <b>절대 줄지 "
          "않습니다.</b>"),
    ("가문(family)", "하나의 아이디어. 파라미터만 바꾼 것은 같은 가문이고, 새 "
                     "가문이 되려면 <b>돈을 내는 사람이 달라야</b> 합니다."),
    ("사망 조건", "결과를 보기 전에 적어두는 '이러면 이 가설은 죽는다'. 나중에 "
                  "기준을 옮기지 못하게 하는 장치입니다."),
    ("봉인(holdout)", "2024-03-01부터의 데이터는 잠겨 있습니다. 연구 코드가 "
                      "읽을 수 없고, 여는 것은 프로젝트 평생 <b>3번</b>뿐입니다."),
    ("SPIKE", "격자에서 딱 한 칸만 좋고 옆칸은 나쁜 모양. 발견이 아니라 "
              "<b>모서리</b>입니다."),
    ("PBO", "고른 설정이 정보를 담았는지. 0.5 이상이면 아무 정보도 없다는 뜻입니다."),
    ("MDD", "최대 낙폭. 고점에서 얼마나 떨어졌는지."),
]


def _read_json(name: str, default=None):
    try:
        return json.loads((config.REPORTS / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _count(path: Path, pattern: str = "*.json") -> int:
    try:
        return len(list(path.glob(pattern)))
    except OSError:
        return 0


def collect() -> dict:
    """이미 기록된 것만 읽는다. 아무것도 계산하지 않는다."""
    d: dict = {"now_kst": datetime.now(KST).strftime("%Y-%m-%d %H:%M")}

    try:
        d["supervisor"] = runstate.supervisor()
    except Exception:                                              # noqa: BLE001
        d["supervisor"] = {"alive": False}
    try:
        d["action"], d["why"] = runstate.next_action()
    except Exception as exc:                                       # noqa: BLE001
        d["action"], d["why"] = "?", str(exc)[:200]

    try:
        sys.path.insert(0, str(config.ORC_ROOT / "scripts"))
        import findings
        d["blocking"] = findings.blocking()
        d["open_findings"] = len(findings.open_findings())
    except Exception:                                              # noqa: BLE001
        d["blocking"], d["open_findings"] = [], 0

    try:
        from orc.ledger.trials import Ledger
        with Ledger() as led:
            d["N"] = led.total_trials()
    except Exception:                                              # noqa: BLE001
        d["N"] = None

    d["target"] = _read_json("TARGET.json", {})
    d["registry"] = _count(config.REGISTRY)
    d["closed"] = _count(config.CONFIGS / "closed")
    d["killed"] = _count(config.CONFIGS / "killed")
    d["queued"] = _count(config.QUEUE)
    try:
        d["scouted"] = sum(1 for ln in (config.REPORTS / "SCOUT.jsonl")
                           .read_text(encoding="utf-8").splitlines() if ln.strip())
    except OSError:
        d["scouted"] = None

    # 닫힌 가문 = 지도. 이 프로젝트의 실제 산출물이다.
    closed = []
    for p in sorted((config.CONFIGS / "closed").glob("*.json")):
        rec = _read_json(f"../configs/closed/{p.name}") or {}
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            rec = {}
        reason = (rec.get("reason") or "").strip()
        closed.append({
            "id": rec.get("hypothesis_id", p.stem),
            "family": rec.get("family", "?"),
            # 첫 문장만. 부검서 전문은 reports/ 에 있다.
            "gist": reason.split("\n")[0][:240] if reason else "부검서 참조",
        })
    d["closed_families"] = closed

    cyc = []
    try:
        for ln in (config.REPORTS / "CYCLE_LOG.jsonl").read_text(
                encoding="utf-8").splitlines()[-4:]:
            if ln.strip():
                cyc.append(json.loads(ln))
    except (OSError, ValueError):
        pass
    d["cycles"] = cyc

    # 검증 진척: 분봉 재현 백로그. 감독자가 고르는 것과 같은 함수로 읽는다 --
    # 화면이 자기만의 계산을 하면 실제로 할 일과 갈라진다.
    d["minute_left"] = d["minute_done"] = None
    try:
        import forever
        from orc.ledger.trials import code_hash
        pending = forever.track_b_backlog()
        every = (_read_json("EXECUTION_REALISM.json") or {}).get("results") or []
        d["minute_left"] = len(pending)
        d["minute_done"] = len({(x.get("hypothesis_id"), x.get("symbol"))
                                for x in every if x.get("code_hash") == code_hash()})
    except Exception:                                              # noqa: BLE001
        pass
    return d


def verdict(d: dict) -> tuple[str, str, str]:
    """(등급, 한 줄, 설명) — 화면 맨 위 한 줄."""
    if not d["supervisor"].get("alive"):
        return ("stop", "연구소가 꺼져 있습니다",
                "감독자 프로세스가 떠 있지 않습니다. 예약 작업 'ORC Forever'가 "
                "5분 안에 다시 띄웁니다.")
    if d["action"] == "blocked":
        n = len(d["blocking"])
        return ("warn", f"평가기 결함 {n}건 때문에 새 숫자를 계산하지 않습니다",
                "결함이 있는 코드로 계산한 숫자는 증거처럼 보이지만 증거가 "
                "아닙니다. 그동안에도 후보 찾기·감사·표본 확대는 계속 돕니다.")
    if d["action"] == "done":
        return ("ok", "종료 조건을 달성했습니다", "목표에 도달했고 검증도 끝났습니다.")
    label = ACTION_KO.get(d["action"], d["action"])
    return ("ok", f"정상 가동 중 — {label}",
            "감독자가 살아 있고 다음 할 일을 스스로 고르고 있습니다.")


def _bar(pct: float, width: int = 40) -> str:
    filled = max(0, min(width, round(pct * width)))
    return "▓" * filled + "░" * (width - filled)


def render(d: dict) -> str:
    e = html.escape
    grade, headline, sub = verdict(d)
    here = ACTION_STAGE.get(d["action"])

    t = d.get("target") or {}
    tgt = t.get("target") or {}
    within = t.get("best_cagr_within_drawdown") or {}
    goal = float(tgt.get("cagr") or 1.0)
    got = float(within.get("cagr") or 0.0)
    pct = max(0.0, min(1.0, got / goal if goal else 0.0))

    counts = [
        f"{d['scouted']:,}건 수집" if d["scouted"] is not None else "?",
        f"{d['killed'] + d['registry']:,}건 제안",
        f"기각 {d['killed']:,} · 통과 {d['registry']:,}",
        (f"{d['N']:,}회 실행" if d["N"] is not None else "?")
        + f" · 대기 {d['queued']}건",
        (f"분봉 {d['minute_done']}쌍 완료 · {d['minute_left']}쌍 남음"
         if d.get("minute_left") is not None else "진행 중"),
        f"{d['closed']:,}개 종결 · {max(d['registry'] - d['closed'], 0)}개 진행",
    ]

    stage_html = "".join(
        f'''<li class="stage{' is-here' if i == here else ''}">
          <div class="stage-n">{i + 1}</div>
          <div class="stage-body">
            <div class="stage-head">
              <h3>{e(name)}</h3>
              <span class="stage-count">{e(counts[i])}</span>
              {'<span class="chip chip-here">지금 여기</span>' if i == here else ''}
            </div>
            <p class="stage-what">{e(what)}</p>
            <p class="stage-why">{why}</p>
          </div>
        </li>'''
        for i, ((name, what, why)) in enumerate(STAGES))

    if d["blocking"]:
        blk = "".join(
            f'''<li><code>{e(str(f.get('file','?')))}:{e(str(f.get('line','?')))}</code>
                <p>{e(str(f.get('what',''))[:300])}</p></li>'''
            for f in d["blocking"])
        blocking_html = f'<ul class="findings">{blk}</ul>'
    else:
        blocking_html = ('<p class="empty">막고 있는 결함이 없습니다. '
                         '연구가 자유롭게 돕니다.</p>')

    closed_html = "".join(
        f'''<li>
          <div class="closed-head"><code>{e(c['id'])}</code>
            <span class="closed-fam">{e(c['family'])}</span></div>
          <p>{e(c['gist'])}</p>
        </li>''' for c in d["closed_families"]) or \
        '<li class="empty">아직 닫힌 가문이 없습니다.</li>'

    gloss_html = "".join(
        f"<dt>{e(term)}</dt><dd>{body}</dd>" for term, body in GLOSSARY)

    cyc_html = "".join(
        f'''<tr><td>{e(str(c.get('finished_utc',''))[:16].replace('T',' '))}</td>
        <td class="num">+{c.get('trials_added',0):,}</td>
        <td>{e(', '.join(c.get('hypotheses_run') or []))}</td></tr>'''
        for c in reversed(d.get("cycles") or [])) or \
        '<tr><td colspan="3" class="empty">기록 없음</td></tr>'

    return f"""<title>ORC 연구소 현황판</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+KR:wght@300;400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap">
<style>
:root {{
  --paper:#f6f7f9; --raised:#ffffff; --sunken:#eceef2;
  --ink:#151a21; --ink-2:#4a5361; --ink-3:#79828f;
  --line:#dde1e8; --line-2:#c8cfd9;
  --accent:#3a4f7a; --accent-soft:#e6eaf3;
  --ok:#2f7d5f; --ok-soft:#e2f0ea;
  --warn:#a8730f; --warn-soft:#f7eeda;
  --stop:#a93a2a; --stop-soft:#f7e4e0;
  --sans:"IBM Plex Sans KR","Malgun Gothic",-apple-system,system-ui,sans-serif;
  --mono:"IBM Plex Mono","Consolas",ui-monospace,monospace;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --paper:#101319; --raised:#181c24; --sunken:#0b0e13;
    --ink:#e8ebf0; --ink-2:#a3acba; --ink-3:#727c8b;
    --line:#252b35; --line-2:#333b48;
    --accent:#8fa8d8; --accent-soft:#1c2436;
    --ok:#63b995; --ok-soft:#14251f;
    --warn:#d6a542; --warn-soft:#2a2113;
    --stop:#e07a68; --stop-soft:#2c1714;
  }}
}}
:root[data-theme="dark"] {{
  --paper:#101319; --raised:#181c24; --sunken:#0b0e13;
  --ink:#e8ebf0; --ink-2:#a3acba; --ink-3:#727c8b;
  --line:#252b35; --line-2:#333b48;
  --accent:#8fa8d8; --accent-soft:#1c2436;
  --ok:#63b995; --ok-soft:#14251f;
  --warn:#d6a542; --warn-soft:#2a2113;
  --stop:#e07a68; --stop-soft:#2c1714;
}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--paper);color:var(--ink);
  font-family:var(--sans);font-weight:400;line-height:1.65;
  -webkit-font-smoothing:antialiased}}
.wrap{{max-width:1040px;margin:0 auto;padding:32px 24px 72px;
  display:flex;flex-direction:column;gap:36px}}
code,.num,.mono{{font-family:var(--mono);font-variant-numeric:tabular-nums}}
h1,h2,h3{{text-wrap:balance;margin:0}}

.masthead{{display:flex;justify-content:space-between;align-items:baseline;
  gap:16px;flex-wrap:wrap;border-bottom:1px solid var(--line);padding-bottom:14px}}
.masthead h1{{font-size:19px;font-weight:600;letter-spacing:-.01em}}
.masthead .stamp{{font-family:var(--mono);font-size:12px;color:var(--ink-3)}}

.verdict{{display:flex;gap:18px;align-items:flex-start;padding:22px 24px;
  border-radius:4px;border:1px solid var(--line-2);background:var(--raised)}}
.verdict.ok{{border-left:4px solid var(--ok);background:var(--ok-soft)}}
.verdict.warn{{border-left:4px solid var(--warn);background:var(--warn-soft)}}
.verdict.stop{{border-left:4px solid var(--stop);background:var(--stop-soft)}}
.verdict .dot{{width:11px;height:11px;border-radius:50%;margin-top:9px;flex:none}}
.verdict.ok .dot{{background:var(--ok)}}
.verdict.warn .dot{{background:var(--warn)}}
.verdict.stop .dot{{background:var(--stop)}}
.verdict h2{{font-size:22px;font-weight:600;letter-spacing:-.015em}}
.verdict p{{margin:6px 0 0;color:var(--ink-2);font-size:14.5px;max-width:62ch}}

section > h2{{font-size:13px;font-weight:600;letter-spacing:.09em;
  text-transform:uppercase;color:var(--ink-3);margin-bottom:14px}}

.stages{{list-style:none;margin:0;padding:0;
  border-top:1px solid var(--line)}}
.stage{{display:flex;gap:18px;padding:16px 12px;
  border-bottom:1px solid var(--line)}}
.stage.is-here{{background:var(--accent-soft);
  box-shadow:inset 3px 0 0 var(--accent)}}
.stage-n{{font-family:var(--mono);font-size:12px;font-weight:600;
  color:var(--ink-3);width:20px;flex:none;padding-top:3px}}
.stage.is-here .stage-n{{color:var(--accent)}}
.stage-body{{min-width:0;flex:1}}
.stage-head{{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}}
.stage-head h3{{font-size:15.5px;font-weight:600}}
.stage-count{{font-family:var(--mono);font-size:12.5px;color:var(--ink-2)}}
.chip{{font-size:11px;font-weight:600;letter-spacing:.05em;padding:2px 8px;
  border-radius:3px}}
.chip-here{{background:var(--accent);color:#fff}}
:root[data-theme="dark"] .chip-here{{color:#101319}}
@media (prefers-color-scheme:dark){{
  :root:not([data-theme="light"]) .chip-here{{color:#101319}}}}
.stage-what{{margin:3px 0 0;font-size:14px;color:var(--ink)}}
.stage-why{{margin:5px 0 0;font-size:13px;color:var(--ink-2);max-width:70ch}}

.goal{{border:1px solid var(--line-2);border-radius:4px;background:var(--raised);
  padding:22px 24px}}
.goal-line{{font-family:var(--mono);font-size:15px;letter-spacing:-.03em;
  color:var(--accent);overflow-x:auto;white-space:nowrap;margin:10px 0 2px}}
.goal dl{{display:grid;grid-template-columns:auto 1fr;gap:6px 16px;margin:14px 0 0;
  font-size:14px}}
.goal dt{{color:var(--ink-3);font-size:13px}}
.goal dd{{margin:0}}
.goal .note{{margin:14px 0 0;font-size:13px;color:var(--ink-2);max-width:66ch}}

.cols{{display:grid;grid-template-columns:1fr 1fr;gap:28px}}
@media (max-width:760px){{.cols{{grid-template-columns:1fr}}}}

.findings,.closed{{list-style:none;margin:0;padding:0;
  display:flex;flex-direction:column;gap:12px}}
.findings li,.closed li{{padding:13px 15px;border:1px solid var(--line);
  border-radius:4px;background:var(--raised)}}
.findings li{{border-left:3px solid var(--warn)}}
.findings code{{font-size:12px;color:var(--warn)}}
.findings p,.closed p{{margin:6px 0 0;font-size:13px;color:var(--ink-2)}}
.closed-head{{display:flex;gap:9px;align-items:baseline}}
.closed-head code{{font-size:12.5px;font-weight:600;color:var(--accent)}}
.closed-fam{{font-size:12px;color:var(--ink-3);font-family:var(--mono)}}
.empty{{color:var(--ink-3);font-size:13.5px;margin:0}}

table{{width:100%;border-collapse:collapse;font-size:13.5px}}
th{{text-align:left;font-size:11.5px;letter-spacing:.06em;text-transform:uppercase;
  color:var(--ink-3);font-weight:600;padding:0 10px 8px 0;
  border-bottom:1px solid var(--line)}}
td{{padding:9px 10px 9px 0;border-bottom:1px solid var(--line);color:var(--ink-2)}}
td.num{{font-family:var(--mono);color:var(--ink);text-align:right;
  font-variant-numeric:tabular-nums}}

.gloss{{display:grid;grid-template-columns:132px 1fr;gap:10px 20px;margin:0;
  font-size:13.5px}}
@media (max-width:600px){{.gloss{{grid-template-columns:1fr;gap:2px 0}}
  .gloss dd{{margin-bottom:12px}}}}
.gloss dt{{font-family:var(--mono);font-weight:600;color:var(--accent);
  font-size:13px}}
.gloss dd{{margin:0;color:var(--ink-2);max-width:64ch}}

footer{{border-top:1px solid var(--line);padding-top:16px;font-size:12.5px;
  color:var(--ink-3)}}
footer code{{font-size:12px}}
</style>

<div class="wrap">
  <header class="masthead">
    <h1>ORC 연구소 현황판</h1>
    <span class="stamp">{e(d['now_kst'])} KST</span>
  </header>

  <div class="verdict {grade}">
    <span class="dot"></span>
    <div>
      <h2>{e(headline)}</h2>
      <p>{e(sub)}</p>
      <p><b>지금 하는 일:</b> {e(ACTION_KO.get(d['action'], d['action']))}
         — {e(str(d['why'])[:180])}</p>
    </div>
  </div>

  <section>
    <h2>연구는 이 여섯 단계를 돕니다</h2>
    <ol class="stages">{stage_html}</ol>
  </section>

  <section class="cols">
    <div>
      <h2>목표까지</h2>
      <div class="goal">
        <div class="goal-line">{_bar(pct)}</div>
        <dl>
          <dt>목표</dt><dd>연 {goal:.0%} 수익을 최대낙폭
            {float(tgt.get('max_drawdown') or .25):.0%} 이내로</dd>
          <dt>현재</dt><dd>연 <b>{got:.1%}</b>
            (낙폭 {float(within.get('max_drawdown') or 0):.1%},
             {e(str(within.get('symbol','-')))})</dd>
          <dt>판정</dt><dd><code>{e(str(t.get('state','?')))}</code></dd>
        </dl>
        <p class="note">목표에 닿은 규칙이 아직 없다는 뜻입니다. 이 프로젝트에서
          그것은 실패가 아니라 <b>측정 결과</b>입니다 — 산출물은 "무엇이 잘 되는가"가
          아니라 <b>"어디서 깨지는가"의 지도</b>입니다.</p>
      </div>
    </div>
    <div>
      <h2>지금 막고 있는 것</h2>
      {blocking_html}
    </div>
  </section>

  <section>
    <h2>지금까지 알아낸 것 — 닫힌 가문이 곧 지도입니다</h2>
    <ul class="closed">{closed_html}</ul>
  </section>

  <section>
    <h2>최근 백테스트</h2>
    <div style="overflow-x:auto">
      <table>
        <thead><tr><th>끝난 시각 (UTC)</th><th style="text-align:right">추가된 행</th>
          <th>돌린 가설</th></tr></thead>
        <tbody>{cyc_html}</tbody>
      </table>
    </div>
  </section>

  <section>
    <h2>용어</h2>
    <dl class="gloss">{gloss_html}</dl>
  </section>

  <footer>
    <code>python scripts/dashboard.py</code> 로 다시 만듭니다.
    자세한 화면은 <code>scripts/watch.py</code>(지금 무엇이 도는가),
    <code>scripts/status.py</code>(가문별 숫자),
    <code>scripts/health.py</code>(고장 점검).
  </footer>
</div>
"""


def main(argv: list[str]) -> int:
    d = collect()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(d), encoding="utf-8")
    print(f"현황판: {OUT}")
    if "--open" in argv:
        webbrowser.open(OUT.as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
