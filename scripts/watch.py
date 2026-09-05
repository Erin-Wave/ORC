"""ORC | 지금 이 순간 무엇이 돌고 있는가.

`health.py`는 "고장났나"에 답하고 `briefing.py`는 "무엇을 알아냈나"에 답한다.
둘 다 답하지 않는 질문이 남는다 — **지금 이 초에 기계가 무엇을 하고 있나.**

그리고 셋 다 답하지 않는 질문이 하나 더 있었다 — **그게 연구의 어디쯤인가.**
`duty_cycle`은 "쉬지 않는가"에 답하지만 "나아가는가"에는 답하지 못한다.
2026-09-05 아침이 정확히 그 차이였다: 듀티 사이클 12.4 %가 전부 이미 답이 나온
셀의 재측정이었고 새 질문은 하나도 등록되지 않았다. 바쁜 화면과 나아가는 연구는
같은 것이 아니고, 앞의 것만 보이는 화면은 뒤의 것을 감춘다.

  연구 단계    헌법 9절이 서술하는 여섯 단계, 각 단계까지 실제로 온 거리,
               그리고 next_action()이 지금 어느 단계에 서 있는지.
  앞으로        대기 중인 백테스트, 다음 정기 사이클, 다음 가설 심사.
  목표까지      reports/TARGET.json이 말하는 종료 조건과의 거리.
  실행 중      ORC 트리 안의 파이썬 프로세스를 실제 명령줄까지 보여준다.
               "supervisor가 살아 있다"와 "지금 뭔가를 계산하고 있다"는
               다른 사실이고, 감독자는 낮잠(IDLE_SLEEP_S) 중에도 살아 있다.
  다음          runstate.next_action()이 지금 답하는 것과 그 이유.
  듀티 사이클   최근 H시간 중 실제로 작업이 돌아간 비율과 가장 긴 공백.
               ACTIVITY.jsonl은 두 기계가 union으로 쓰므로 구간을 합집합으로
               병합한다 -- 단순히 더하면 겹치는 만큼 100%를 넘는다.
  원격          GitHub Actions에서 지금 돌고 있는 런.

아무것도 쓰지 않는다. `python scripts/watch.py`는 언제 몇 번 실행해도
연구 상태를 바꾸지 않는다.

  python scripts/watch.py                 한 번 출력
  python scripts/watch.py --interval 10   10초마다 갱신 (Ctrl+C로 종료)
  python scripts/watch.py --hours 24      듀티 사이클 구간을 바꾼다
  python scripts/watch.py --json          스크립트용
"""
from __future__ import annotations

import json
import unicodedata
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path, PureWindowsPath

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    sys.stdout.reconfigure(errors="replace")
except (AttributeError, OSError):                                  # pragma: no cover
    pass

from orc import config, runstate                                  # noqa: E402

KST = timezone(timedelta(hours=9))
DEFAULT_HOURS = 12

# 프로세스 목록을 얻는 데 이 이상 기다리지 않는다.  화면 하나가 WMI 응답을
# 기다리며 멈추면 "지금 무엇이 도는가"에 답하지 못하는 것과 같다.
PS_TIMEOUT_S = 20

# The PARENT id is not a nicety. On this machine the scheduled task launches
# `python.exe` from the WindowsApps execution alias, which is a STUB that
# spawns the real interpreter and waits for it -- so one supervisor is always
# two processes with `forever.py` on both command lines. Without the parent,
# every healthy supervisor looks like two of them.
# CreationDate rides along because "무엇이 도는가"와 "몇 분째 도는가"는 다른
# 질문이고, 두 번째 것이 없어서 소유자가 23분째 돌고 있는 kernel_review를
# 보고 "지금 멈춰있다"고 읽었다.  ACTIVITY.jsonl은 끝난 작업만 적으므로 긴
# 작업 하나는 끝날 때까지 화면에서 완전히 침묵한다.
_PS = (
    "Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR "
    "Name='claude.exe' OR Name='codex.exe'\" | "
    "ForEach-Object { '{0}|{1}|{2}|{3}' -f $_.ProcessId, $_.ParentProcessId, "
    "$_.CreationDate.ToUniversalTime().ToString('o'), $_.CommandLine }"
)


def running_scripts(root: Path | None = None) -> list[dict] | None:
    """ORC 트리 안에서 돌고 있는 파이썬 프로세스.  None이면 물어볼 수 없었다.

    빈 리스트와 None은 다르다: 빈 리스트는 "아무것도 안 돌고 있다"이고
    None은 "알 수 없다"이며, 후자를 전자로 보고하는 화면은 거짓말을 한다.
    """
    root = Path(root or config.ORC_ROOT)
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                            "-Command", _PS],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=PS_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None

    out = []
    marker = str(root).replace("/", "\\").lower()
    now = datetime.now(timezone.utc)
    for line in (r.stdout or "").splitlines():
        parts = line.split("|", 3)
        if len(parts) != 4:
            continue
        pid, ppid, started, cmd = (x.strip() for x in parts)
        # 모델 CLI는 트리 밖의 실행 파일이라 marker로 걸러지지 않는다.  그것이
        # 바로 감독자가 대부분의 시간을 기다리는 대상이므로, 부모가 ORC
        # 프로세스이면 남긴다 -- 사슬은 아래에서 붙인다.
        # PureWindowsPath, not Path. The line always comes from
        # Get-CimInstance and is therefore always a Windows command line, but
        # the SUITE runs on Linux, where Path treats a backslash as an ordinary
        # character and `.stem` returns the whole path -- so the model CLI was
        # dropped on the runner and kept here, which is a screen that behaves
        # differently depending on who is looking at it.
        exe = PureWindowsPath(cmd.split()[0].strip('"')).stem.lower()
        is_model = exe in ("claude", "codex")
        if not cmd or (marker not in cmd.lower() and not is_model):
            continue
        # 스크립트 이름만 남긴다: 전체 명령줄은 인터프리터 경로가 대부분이다.
        script = next((tok.strip('"').split("\\")[-1]
                       for tok in cmd.split()
                       if tok.strip('"').lower().endswith(".py")), None)
        if script is None:
            script = exe if is_model else "?"
            args = ""
        else:
            args = cmd.split(script, 1)[1].strip().strip('"') if script in cmd else ""
        began = runstate._utc(started)
        out.append({"pid": pid, "ppid": ppid, "script": script,
                    "args": args[:60], "started_utc": started,
                    "elapsed_min": ((now - began).total_seconds() / 60.0)
                    if began else None,
                    "is_model": is_model})
    # 모델 CLI는 ORC 프로세스의 자손일 때만 우리 것이다.  소유자가 따로 띄운
    # claude를 연구소가 일하는 증거로 세면 화면이 거짓말을 한다.
    ours = {p["pid"] for p in out if not p["is_model"]}
    grew = True
    while grew:
        grew = False
        for p in out:
            if p["ppid"] in ours and p["pid"] not in ours:
                ours.add(p["pid"])
                grew = True
    return [p for p in out if p["pid"] in ours]


def _intervals(hours: int) -> list[tuple[datetime, datetime, str]]:
    """(시작, 끝, 액션) — ACTIVITY.jsonl에 기록된 실제 작업 구간."""
    now = datetime.now(timezone.utc)
    cut = now - timedelta(hours=hours)
    out = []
    for a in runstate.activities(limit=4000):
        t = runstate._utc(a.get("utc"))
        if t is None or t < cut:
            continue
        secs = float(a.get("seconds") or 0.0)
        # 기록된 시각은 작업이 끝난 시각이므로 구간은 그 앞이다.
        out.append((t - timedelta(seconds=secs), t, str(a.get("action"))))
    return sorted(out)


def duty_cycle(hours: int = DEFAULT_HOURS) -> dict:
    """작업이 돌아간 비율과 가장 긴 공백.

    두 감독자(워크스테이션과 러너)가 같은 파일에 쓰고 구간이 겹치므로
    합집합으로 병합한다.  더하면 38.9 %가 60 %로 보일 수 있고, 그 숫자는
    "쉬지 않는다"는 주장을 검사하는 데 쓰이는 숫자다.
    """
    now = datetime.now(timezone.utc)
    spans = _intervals(hours)
    if not spans:
        return {"hours": hours, "busy_min": 0.0, "span_min": 0.0,
                "fraction": 0.0, "largest_gap_min": None, "since_last_min": None,
                "n": 0}

    merged: list[list[datetime]] = []
    for start, end, _ in spans:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    busy = sum((e - s).total_seconds() for s, e in merged)
    window_start = max(merged[0][0], now - timedelta(hours=hours))
    span = (now - window_start).total_seconds()
    gaps = [(merged[i + 1][0] - merged[i][1]).total_seconds()
            for i in range(len(merged) - 1)]
    since = (now - merged[-1][1]).total_seconds()
    return {
        "hours": hours,
        "busy_min": busy / 60.0,
        "span_min": span / 60.0,
        "fraction": busy / max(span, 1.0),
        "largest_gap_min": (max(gaps) / 60.0) if gaps else None,
        "since_last_min": since / 60.0,
        "n": len(spans),
    }


def live_runs() -> list[dict] | None:
    try:
        r = subprocess.run(["gh", "run", "list", "--limit", "20", "--json",
                            "databaseId,status,createdAt,workflowName"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=45, cwd=config.ORC_ROOT)
        runs = json.loads(r.stdout) if r.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    if runs is None:
        return None
    return [x for x in runs if x["status"] != "completed"]


def _lock_holder_chain(procs: list[dict], holder: str) -> set[str]:
    """잠금 보유자와 그 조상·자손 pid 집합.

    조상이 필요한 이유가 이 함수의 존재 이유다: 예약 작업은 WindowsApps 실행
    별칭의 `python.exe`를 띄우고, 그것은 실제 인터프리터를 자식으로 낳고
    기다리는 **런처 껍데기**다. 둘 다 명령줄에 `forever.py`를 갖는다. 그래서
    정상 감독자는 언제나 프로세스 두 개이고, 부모를 보지 않으면 전부 중복으로
    읽힌다.
    """
    by_pid = {p["pid"]: p for p in procs}
    chain: set[str] = set()
    if holder not in by_pid:
        return chain
    chain.add(holder)
    cur = by_pid[holder].get("ppid")
    while cur in by_pid and cur not in chain:
        chain.add(cur)
        cur = by_pid[cur].get("ppid")
    grew = True
    while grew:
        grew = False
        for p in procs:
            if p.get("ppid") in chain and p["pid"] not in chain:
                chain.add(p["pid"])
                grew = True
    return chain


def strays(procs: list[dict] | None, sup: dict) -> list[dict]:
    """잠금 보유자의 프로세스 사슬 밖에서 돌고 있는 forever.py.

    **정정 (2026-09-04).** 이 함수의 첫 버전은 "잠금을 들고 있지 않은
    forever.py"를 좀비로 지목했고, 그 근거로 pid 30784가 19시간 동안 멈춰
    있었다고 적었다. **둘 다 틀렸다.**

    부모-자식을 확인하니 30784는 27212의 **런처 껍데기**였다(위 참조). 그리고
    로그가 09-03 23:49에 끊긴 이유는 감독자가 멈춘 것이 아니라 Windows 이벤트
    로그 Id 42가 말하는 그대로 **기계가 00:24에 잠든 것**이고, 06:55의 wake
    source와 함께 예약 작업이 깨어나 7시간 된 stale lock을 깼다 -- 즉 설계가
    의도대로 동작한 기록이었다. 나는 그 위에서 건강한 감독자와 그 런처를
    죽였다. 결과는 무해했지만(어차피 새 코드를 실어야 했다) 진단은 사실이
    아니었다.

    그래서 이 함수는 사슬을 계산한다. 남은 진짜 위험은 여전히 실재한다:
    사슬 밖의 두 번째 감독자는 등록 예산을 독립적으로 읽고, `cycle` 액션이
    있는 지금은 두 기계가 daily_cycle.py를 동시에 돌릴 수 있다 -- run #19이
    112 trial을 잃은 동시 원장 쓰기가 그것이다. 다만 런처를 그것으로 오인하는
    화면은 아무도 읽지 않게 되고, 그것은 검사가 없는 것보다 나쁘다.
    """
    if not procs:
        return []
    holder = str(sup.get("pid") or "")
    chain = _lock_holder_chain(procs, holder)
    return [p for p in procs
            if p["script"] == "forever.py" and p["pid"] not in chain
            and p["pid"] != holder]


# 연구가 실제로 지나는 여섯 단계
# --------------------------------------------------------------------------
# 헌법 9절과 9b절이 서술하는 순서를 그대로 옮긴 것이고, 새로 만든 분류가
# 아니다.  각 단계에 붙은 문장은 그 단계가 무엇을 하는지를 이 저장소를 처음
# 보는 사람이 읽을 수 있게 쓴 것이며, 옆의 숫자는 전부 파일에서 세어온다.
#
# next_action()이 답하는 액션을 단계로 되짚는 표가 함께 있는 이유는, "지금
# 무엇을 하고 있나"와 "그게 연구의 어디쯤인가"가 다른 질문이기 때문이다.
# 앞의 것에는 이미 답이 있었고 뒤의 것에는 없었다.
STAGES = (
    ("①", "후보 찾기",
     "누가 구조적으로 계속 돈을 내는지 밖에서 찾아옵니다"),
    ("②", "가설 제안",
     "그 후보를 반증 가능한 규칙과 사망 조건으로 바꿉니다"),
    ("③", "반론 심사",
     "등록 전에 모델 둘이 그 가설을 죽여봅니다"),
    ("④", "백테스트",
     "심사를 통과한 규칙만 과거 데이터에 전부 돌립니다"),
    ("⑤", "검증",
     "우연인지 진짜인지 거릅니다 (PBO·서치테스트·분봉 재현)"),
    ("⑥", "판정·종결",
     "미리 써둔 사망 조건과 대조하고 부검서를 남깁니다"),
)

# 액션 이름 -> 그 액션이 속한 단계 번호(0-based).  여기 없는 액션은 연구의
# 한 단계가 아니라 도구를 점검하는 일이므로 단계를 차지하지 않는다.
ACTION_STAGE = {
    "scout": 0,
    "reason": 2,          # 제안과 심사가 한 패스 안에서 함께 일어난다
    "cycle": 3,
    "robustness": 4,
    "execution_realism": 4,
    "survivorship": 4,
}


def _count(path: Path, pattern: str = "*.json") -> int:
    try:
        return len(list(path.glob(pattern)))
    except OSError:                                                # pragma: no cover
        return 0


def progress() -> dict:
    """연구가 지금까지 어디까지 왔고 다음에 무엇을 할 것인가.

    duty_cycle이 "쉬지 않는가"에 답하는 것과 달리 이쪽은 "진도가 나갔는가"에
    답한다. 둘은 다른 질문이고, 2026-09-05 아침이 그 차이였다: 듀티 사이클
    12.4 %가 전부 execution_realism 재측정이었고 새 질문은 하나도 등록되지
    않았다. 바쁜 화면과 나아가는 연구는 같은 것이 아니다.

    아무것도 계산하지 않는다.  세는 것뿐이고, 읽을 수 없는 값은 None으로 두어
    "0건"과 "모른다"가 같은 모양으로 인쇄되지 않게 한다.
    """
    reports = config.REPORTS
    killed = _count(config.CONFIGS / "killed")
    registered = _count(config.REGISTRY)
    closed = _count(config.CONFIGS / "closed")
    queued = _count(config.QUEUE)

    try:
        scouted = sum(1 for line in
                      (reports / "SCOUT.jsonl").read_text(encoding="utf-8")
                      .splitlines() if line.strip())
    except OSError:
        scouted = None

    try:
        from orc.ledger.trials import Ledger
        with Ledger() as led:
            trials = led.total_trials()
    except Exception:                                              # noqa: BLE001
        trials = None

    # 분봉 재현 백로그.  forever.py가 고르는 것과 같은 목록을 같은 함수로
    # 읽는다 -- 화면이 자기만의 계산을 하면 감독자가 실제로 할 일과 갈라진다.
    backlog = done_pairs = None
    try:
        sys.path.insert(0, str(config.ORC_ROOT / "scripts"))
        import forever
        pending = forever.track_b_backlog()
        backlog = len(pending)
        every = json.loads((reports / "EXECUTION_REALISM.json")
                           .read_text(encoding="utf-8")).get("results") or []
        from orc.ledger.trials import code_hash
        done_pairs = len({(x.get("hypothesis_id"), x.get("symbol")) for x in every
                          if x.get("code_hash") == code_hash()})
    except Exception:                                              # noqa: BLE001
        pass

    try:
        target = json.loads((reports / "TARGET.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        target = None

    return {
        "scouted": scouted,
        "proposed": killed + registered,
        "killed": killed,
        "registered": registered,
        "trials": trials,
        "queued": queued,
        "closed": closed,
        "open_families": max(registered - closed, 0),
        "minute_backlog": backlog,
        "minute_done": done_pairs,
        "target": target,
        "next_cycle_utc": runstate.next_worker_slot().isoformat(),
        "next_reasoning_utc": runstate.next_reasoning_slot().isoformat(),
    }


def snapshot(hours: int = DEFAULT_HOURS) -> dict:
    procs = running_scripts()
    sup = runstate.supervisor()
    try:
        action, why = runstate.next_action()
    except Exception as exc:                                       # noqa: BLE001
        action, why = "?", f"{type(exc).__name__}: {exc}"
    recent = runstate.activities(limit=8)
    return {
        "utc": datetime.now(timezone.utc).isoformat(),
        "supervisor": sup,
        "processes": procs,
        "strays": strays(procs, sup),
        "next": {"action": action, "why": why},
        "progress": progress(),
        "duty": duty_cycle(hours),
        "recent": recent,
        "live_runs": live_runs(),
    }


def _n(v, unit: str = "") -> str:
    """읽을 수 없었던 값을 0으로 인쇄하지 않는다."""
    return "?" if v is None else f"{v:,}{unit}"


def _pad(text: str, width: int) -> str:
    """표시 폭 기준으로 채운다.

    `f"{name:9s}"`는 글자를 세고 터미널은 칸을 센다. 한글과 ①은 두 칸을
    차지하므로 파이썬의 패딩은 한글이 섞인 표를 반드시 어긋나게 만든다 --
    이 화면의 첫 판이 정확히 그렇게 나왔다.
    """
    w = sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1
            for c in text)
    return text + " " * max(0, width - w)


def render_progress(snap: dict) -> list[str]:
    """연구의 어느 단계이고, 지금까지 얼마나 왔고, 다음에 무엇을 하는가.

    진행 상황을 읽지 못했으면 그렇게 말한다. 이 파일의 나머지가 빈 목록과
    None을 구분하는 것과 같은 이유이고, 여기서는 한 가지가 더 걸려 있다:
    화면이 통째로 죽으면 감독자가 살아 있는지도 못 본다.
    """
    p = snap.get("progress")
    if not p:
        return ["연구 진행", "  알 수 없음 — 진행 상황을 읽지 못했습니다"]
    here = ACTION_STAGE.get(snap["next"]["action"])

    L = ["연구는 이 여섯 단계를 돕니다"]
    counts = (
        f"{_n(p['scouted'])}건 수집",
        f"{_n(p['proposed'])}건 제안",
        f"기각 {_n(p['killed'])} · 통과 {_n(p['registered'])}",
        f"{_n(p['trials'])}회 실행 · 대기 {_n(p['queued'])}건",
        (f"분봉 {_n(p['minute_done'])}쌍 완료 · {_n(p['minute_backlog'])}쌍 남음"
         if p["minute_backlog"] is not None else "분봉 재현 ?"),
        f"{_n(p['closed'])}개 종결 · {_n(p['open_families'])}개 진행 중",
    )
    for i, ((num, name, what), tally) in enumerate(zip(STAGES, counts)):
        mark = "   ◀ 지금 여기" if i == here else ""
        L.append(f"  {num} {_pad(name, 12)}{_pad(tally, 30)}{mark}".rstrip())
        L.append(f"       {what}")
    if here is None:
        L.append(f"     지금은 여섯 단계 밖의 일을 합니다 — {snap['next']['action']}")

    L.append("")
    L.append("앞으로")
    if p["queued"]:
        L.append(f"  대기 중 백테스트  {p['queued']}건 — 심사를 통과한 질문이 "
                 "차례를 기다립니다")
    else:
        L.append("  대기 중 백테스트  없음 — 심사를 통과한 새 질문이 아직 "
                 "없다는 뜻이고, 지금 속도를 정하는 것은 계산이 아니라 이쪽입니다")
    L.append(f"  다음 정기 사이클  {runstate.kst(p['next_cycle_utc'])} "
             f"({runstate.until(p['next_cycle_utc'])})")
    L.append(f"  다음 가설 심사    {runstate.kst(p['next_reasoning_utc'])} "
             f"({runstate.until(p['next_reasoning_utc'])})")

    t = p.get("target")
    if t:
        tgt = t.get("target") or {}
        within = t.get("best_cagr_within_drawdown") or {}
        best = t.get("best_cagr") or {}
        goal = float(tgt.get("cagr") or 1.0)
        L.append("")
        L.append("목표까지")
        L.append(f"  목표   연 {goal:.0%} 수익을 최대손실 "
                 f"{float(tgt.get('max_drawdown') or 0.25):.0%} 이내로")
        if within:
            got = float(within.get("cagr") or 0.0)
            width = 40
            filled = max(0, min(width, int(round(got / goal * width))))
            L.append(f"  현재   {'▓' * filled}{'░' * (width - filled)}  "
                     f"{got:.1%}")
            L.append(f"         손실 {float(within.get('max_drawdown') or 0):.1%} "
                     f"이내에서 가장 좋은 것: {within.get('symbol')} "
                     f"({within.get('hypothesis_id')})")
        if best:
            L.append(f"  참고   손실을 무시하면 연 "
                     f"{float(best.get('cagr') or 0):.1%}까지 있지만 그때 "
                     f"최대손실이 {float(best.get('max_drawdown') or 0):.1%}입니다")
        L.append(f"  판정   {t.get('state')} — {t.get('headline', '')}")
    return L


def render(snap: dict) -> list[str]:
    now = datetime.now(KST)
    L = [f"ORC watch   {now:%Y-%m-%d %H:%M:%S} KST   ({snap['utc'][11:19]}Z)", ""]

    L += render_progress(snap)
    L.append("")

    L.append("지금")
    sup = snap["supervisor"]
    if sup.get("alive"):
        L.append(f"  감독자     살아 있음 pid {sup['pid']}, "
                 f"박동 {runstate.ago(sup.get('heartbeat_utc'))}")
    else:
        L.append("  감독자     떠 있지 않음 — "
                 "Start-ScheduledTask -TaskName 'ORC Forever'")

    procs = snap["processes"]
    if procs is None:
        L.append("  실행 중     알 수 없음 (PowerShell에 물어볼 수 없었음)")
    elif not procs:
        L.append("  실행 중     없음 — 감독자는 낮잠 중이거나 다음 액션을 기다립니다")
    else:
        # 감독자 자신은 언제나 떠 있으므로 "돌고 있다"의 증거가 아니다. 지금
        # 실제로 무언가를 하고 있다는 증거는 그 자식이고, 그것이 없는 화면을
        # 보고 소유자는 23분째 돌던 kernel_review를 "멈춰있다"고 읽었다.
        work = [p for p in procs if p["script"] != "forever.py"]
        for p in work:
            tag = "  ▶ 지금    " if p is work[0] else "             "
            mins = p.get("elapsed_min")
            since = f"{mins:.0f}분째" if mins is not None else "?"
            what = "모델 응답 대기" if p.get("is_model") else p.get("args", "")
            L.append(f"{tag} {p['script']:18s} {since:>7s}  {what}".rstrip())
        if not work:
            L.append("  ▶ 지금     아무 작업도 실행 중이 아닙니다 — "
                     "감독자는 다음 액션까지 쉽니다")
        L.append(f"  감독자 프로세스  {len(procs) - len(work)}개")

    for st in snap.get("strays", []):
        L.append(f"  ! 좀비      {st['script']} pid {st['pid']} 이 잠금을 들고 "
                 "있지 않습니다 — 멈춘 감독자입니다. 깨어나면 감독자가 둘이 "
                 "되고 등록 예산과 원장 쓰기가 둘로 갈립니다.")
        L.append(f"             확인 후 종료: Stop-Process -Id {st['pid']}")

    nxt = snap["next"]
    L.append(f"  다음        {nxt['action']} — {nxt['why'][:120]}")

    live = snap["live_runs"]
    if live is None:
        L.append("  원격        알 수 없음 (gh를 쓸 수 없었음)")
    elif not live:
        L.append("  원격        지금 돌고 있는 런 없음")
    else:
        for x in live:
            L.append(f"  원격        {x['workflowName']} #{x['databaseId']} "
                     f"{x['status']}, {runstate.ago(x['createdAt'])} 시작")

    d = snap["duty"]
    L.append("")
    L.append(f"듀티 사이클 (최근 {d['hours']}시간)")
    width = 40
    filled = int(round(d["fraction"] * width))
    L.append(f"  {'█' * filled}{'·' * (width - filled)}  {d['fraction']:.1%}")
    L.append(f"  작업 {d['busy_min']:.0f}분 / 구간 {d['span_min']:.0f}분, "
             f"활동 {d['n']}건")
    if d["largest_gap_min"] is not None:
        L.append(f"  가장 긴 공백 {d['largest_gap_min']:.0f}분, "
                 f"마지막 작업 종료 후 {d['since_last_min']:.0f}분")

    L.append("")
    L.append("최근")
    for a in snap["recent"]:
        mark = "ok  " if a.get("ok", True) else "FAIL"
        secs = float(a.get("seconds") or 0.0)
        L.append(f"  {str(a.get('utc'))[11:16]}  {mark} {str(a.get('action')):18s}"
                 f" {secs / 60:5.1f}분  {' '.join(str(a.get('detail', '')).split())[:70]}")
    return L


def main(argv: list[str]) -> int:
    hours = DEFAULT_HOURS
    if "--hours" in argv:
        hours = int(argv[argv.index("--hours") + 1])
    if "--json" in argv:
        print(json.dumps(snapshot(hours), ensure_ascii=False, indent=2, default=str))
        return 0

    interval = None
    if "--interval" in argv:
        interval = max(2, int(argv[argv.index("--interval") + 1]))

    while True:
        snap = snapshot(hours)
        if interval:
            print("\033[2J\033[H", end="")
        print("\n".join(render(snap)))
        if not interval:
            print("\n다음: python scripts/watch.py --interval 10   (10초마다 갱신)")
            return 0
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
