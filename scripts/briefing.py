"""ORC | 연구 브리핑: 어디까지 왔고, 지금 가장 좋은 것은 무엇이며, 왜 아직 전략이 아닌가.

health.py는 "기계가 살아 있나"에 답한다. status.py는 표와 숫자를 보여준다.
둘 다 답하지 않는 질문이 남는다 — **그래서 무엇을 알아냈고, 다음은 무엇인가.**

이 파일은 새로 탐색하지 않는다.  status.py의 주석이 말하는 그대로,
원장에서 최댓값을 사냥하는 것은 이 프로토콜 전체가 억제하려는 선택 편향이고
편의 명령이 바로 그것이 스며드는 경로다.  그래서 여기서 하는 일은
**각 가족이 자기 사전등록된 리포트에서 이미 지목한 최고 셀**을 읽어
한글로 옮기고, 실격 사유를 빠짐없이 붙이는 것뿐이다.
가족 간 순위표는 만들지 않는다 — 그것이 곧 "골라잡기"이기 때문이다.

  python scripts/briefing.py              화면에 출력
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

from orc import config                                             # noqa: E402
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
                 "(08:25 KST, 실패 시 20:25 재시도).")
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
    text = build()
    print(text)
    if "--write" in argv:
        out = config.REPORTS / "BRIEFING.md"
        out.write_text(text, encoding="utf-8")
        print(f"\n[written: {out}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
