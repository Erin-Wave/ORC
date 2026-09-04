"""ORC | 지금 이 순간 무엇이 돌고 있는가.

`health.py`는 "고장났나"에 답하고 `briefing.py`는 "무엇을 알아냈나"에 답한다.
둘 다 답하지 않는 질문이 남는다 — **지금 이 초에 기계가 무엇을 하고 있나.**

그래서 이 파일은 다른 어떤 화면보다 좁고 구체적이다:

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
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
_PS = (
    "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
    "ForEach-Object { '{0}|{1}|{2}' -f $_.ProcessId, $_.ParentProcessId, "
    "$_.CommandLine }"
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
    for line in (r.stdout or "").splitlines():
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        pid, ppid, cmd = (x.strip() for x in parts)
        if not cmd or marker not in cmd.lower():
            continue
        # 스크립트 이름만 남긴다: 전체 명령줄은 인터프리터 경로가 대부분이다.
        script = next((tok.strip('"').split("\\")[-1]
                       for tok in cmd.split()
                       if tok.strip('"').lower().endswith(".py")), "?")
        args = cmd.split(script, 1)[1].strip().strip('"') if script in cmd else ""
        out.append({"pid": pid, "ppid": ppid, "script": script,
                    "args": args[:60]})
    return out


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
        "duty": duty_cycle(hours),
        "recent": recent,
        "live_runs": live_runs(),
    }


def render(snap: dict) -> list[str]:
    now = datetime.now(KST)
    L = [f"ORC watch   {now:%Y-%m-%d %H:%M:%S} KST   ({snap['utc'][11:19]}Z)", ""]

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
        for p in procs:
            tag = "  실행 중    " if p is procs[0] else "             "
            L.append(f"{tag} {p['script']} {p['args']}  (pid {p['pid']})")

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
