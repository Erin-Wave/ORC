"""ORC | The supervisor. There is always something to do, so it never idles.

Until 2026-09-03 the loop had one way to make progress: fire the reasoning
layer, once a day, and ask a new question. Everything else waited. That design
has two idle states built into it, and the project spent a day in both:

  the adversary does its job.  Both proposals on 2026-09-03 were killed --
  H0009 as a finer grid over closed H0007, H0010 for misreading a metric --
  which is the veto working exactly as intended.  The day's one registration
  slot was then spent and the machine sat still until the next morning.

  the worker fires on a six-hour cron whether or not anything was proposed.
  Trials dedupe on (config, symbol, evaluator, panel, code), so a cycle over an
  unchanged registry inserts zero rows and still writes a fresh report and a
  green run.  Four of those in a row looks identical to research.

So this asks a different question every tick: not "is it time to propose" but
"what is the most useful thing that can be done right now". runstate.next_action
answers it, and the answer is only sometimes a new hypothesis. The rest of the
time it is work that costs ZERO ledger rows and is genuinely research:

  scout              the web, for a payer this repository has no way to hear
                     about.  The proposer's tools are Read/Glob/Grep/Write,
                     which is why it kept re-deriving its own registry.
  kernel_review      an adversarial read of the evaluators.  Six silent
                     defects in one day, one of them putting sealed funding
                     data into the development window.  A defect here voids
                     every result in the project.
  robustness         does a recorded number survive cost stress, a walk
                     forward, a regime split.
  execution_realism  one cell re-run on minute bars, where the hourly panel's
                     "adverse first" and "one fill" assumptions get tested.
  survivorship       KT-3 is INCONCLUSIVE and blocks every alt-basket
                     hypothesis until the delisted sample is large enough.

What stays scarce is REGISTRATION, and only registration:
config.MAX_REGISTRATIONS_PER_DAY. Proposing is free -- a killed proposal is a
file in configs/killed/ and zero rows -- so a machine that proposes around the
clock spends compute, which costs nothing here, on the step whose job is to
widen the search. A machine that REGISTERS around the clock would put more rows
into N in a week than the project has accumulated in its life.

Every tick is written to reports/ACTIVITY.jsonl, because "it never rests" is a
claim and a gap in that file is what would make it false.

  python scripts/forever.py            run until stopped
  python scripts/forever.py --once     one tick, then exit
  python scripts/forever.py --dry-run  say what it would do, do nothing
"""
from __future__ import annotations

import json
import os
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
sys.path.insert(0, str(Path(__file__).resolve().parent))

from orc import config, runstate                                   # noqa: E402

KST = timezone(timedelta(hours=9))
LOG_DIR = config.ORC_ROOT / "logs"

# One supervisor per machine.  Task Scheduler's IgnoreNew stops a second
# trigger from starting one, but a human running this in a terminal while the
# scheduled copy is alive would have two processes proposing at once -- and the
# registration budget is read per tick, so two of them could each see three
# registrations booked and make the fifth and sixth.
LOCK = LOG_DIR / "forever.lock"
LOCK_STALE_MIN = 30

# How long a tick that did nothing waits before asking again.  Short enough to
# pick up a worker's results promptly, long enough that the log is readable.
IDLE_SLEEP_S = 300
# After a blocking finding, which only a human can clear.
BLOCKED_SLEEP_S = 900
# After real work, so two long actions do not run back to back with no pause.
WORKED_SLEEP_S = 30

# A single action may not run forever.  The reasoning pass is the long one --
# eight to ten model calls -- and the rest are minutes.  A hung call must not
# take the supervisor with it.
TIMEOUTS_S = {
    "reason": 3 * 3600,
    "scout": 1800,
    "kernel_review": 3 * 3600,
    "robustness": 1800,
    "execution_realism": 3600,
    "survivorship": 3600,
}

# Exit codes that mean THE WORK HAPPENED, per action.
#
# "Non-zero means it failed" is wrong here, and wrong in the direction that
# matters. In this project FAIL is the product -- the deliverable is a map of
# where rules break -- so several of these scripts return non-zero to report a
# VERDICT and not an error:
#
#   execution_realism  1 = the cell did not survive minute bars. That is the
#                      answer, and it is the answer we ran it for. H0002 on
#                      BTCUSDT drifts 53.9% between clocks and returns 1.
#   kernel_review      1 = it found a HIGH finding. The review worked; the
#                      code is what is wrong.
#   scout              1 = every provider skipped, so nothing was collected.
#                      Here non-zero really is "the work did not happen".
#   reason             1 blocked by a finding, 3 judgement unavailable,
#                      4 commit refused -- none of them a pass that ran.
#
# Getting this wrong is not cosmetic: a verdict read as a failure sits in the
# 12-minute cooldown and is retried forever, so the one action whose answer is
# already known becomes the only thing the supervisor ever does.
DONE_EXIT_CODES = {
    "reason": (0,),
    "scout": (0,),
    "kernel_review": (0, 1),
    "robustness": (0,),
    "execution_realism": (0, 1),
    "survivorship": (0,),
}

# What each action changes, so the commit names its paths.  Section 10: never
# stage by wildcard.  `reason` is absent because reasoning.py commits and
# pushes its own registration -- the one commit in this project that must land
# before anything else touches the tree.
COMMIT_PATHS = {
    "scout": ("reports/SCOUT.jsonl",),
    "kernel_review": ("reports/KERNEL_REVIEW.json", "reports/KERNEL_REVIEW.md",
                      "reports/FINDINGS.json"),
    "robustness": ("reports/ROBUSTNESS.json",),
    "execution_realism": ("reports/EXECUTION_REALISM.json",),
    "survivorship": ("reports/KT3_SURVIVORSHIP.json",),
}

# Committed with every action, whatever the action was.  ACTIVITY.jsonl is the
# evidence for the only claim this file makes -- that the machine does not rest
# -- and a record of the work that stays on one workstation is not a record.
# It was untracked for the supervisor's first hour: robustness landed its own
# report and the log of having run it did not.
ALWAYS_COMMIT = ("reports/ACTIVITY.jsonl",)


def _log_path() -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return LOG_DIR / f"forever_{datetime.now(KST):%Y-%m-%d}.log"


def log(msg: str) -> None:
    line = f"[{datetime.now(KST):%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    try:
        with _log_path().open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:                                                # pragma: no cover
        pass


# ---------------------------------------------------------------------------
# one supervisor at a time
# ---------------------------------------------------------------------------
def claim_lock() -> bool:
    """True if this process now owns the supervisor slot.

    The lock carries a heartbeat rather than only a pid, because a pid on
    Windows is reused and a stale lock that can never be broken would leave the
    loop permanently unable to start -- the exact failure this whole session was
    spent on.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    if LOCK.exists():
        try:
            rec = json.loads(LOCK.read_text(encoding="utf-8"))
            beat = runstate._utc(rec.get("heartbeat_utc"))
        except (OSError, ValueError):
            beat, rec = None, {}
        if beat is not None and (now - beat) < timedelta(minutes=LOCK_STALE_MIN):
            log(f"another supervisor holds the lock (pid {rec.get('pid')}, "
                f"heartbeat {runstate.ago(beat, now)}); exiting")
            return False
        log(f"breaking a stale lock (heartbeat {runstate.ago(beat, now)})")
    beat_lock()
    return True


def beat_lock() -> None:
    try:
        # Self-sufficient on purpose.  claim_lock() makes the directory today,
        # so relying on it would work -- until the heartbeat thread is the
        # first writer, and then every beat fails silently into the OSError
        # below and the lock the supervisor is holding looks like a corpse.
        LOCK.parent.mkdir(parents=True, exist_ok=True)
        # Written to a side name and RENAMED, never truncated in place.  The
        # heartbeat thread rewrites this file every minute, and everything that
        # asks whether the loop is alive reads it: claim_lock, runstate.
        # supervisor, the briefing, health.py, both watchdogs.  write_text
        # truncates before it writes, so a reader landing in that window got a
        # ZERO-LENGTH file, json.loads raised, and the supervisor read as dead
        # while it was working -- the briefing reports nobody home mid-pass and
        # the watchdog starts a second supervisor on top of the first, which is
        # the exact failure HEARTBEAT_S below exists to prevent.  os.replace
        # swaps the name in one step, so a reader sees the previous beat or the
        # new one and never half of either.  The runner caught it as an empty
        # read; the workstation had only been winning the race by luck.
        tmp = LOCK.with_name(f"{LOCK.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(
            {"pid": os.getpid(),
             "heartbeat_utc": datetime.now(timezone.utc).isoformat()}),
            encoding="utf-8")
        os.replace(tmp, LOCK)
    except OSError:                                                # pragma: no cover
        # A rename that did not happen leaves the side file behind, and a
        # process that beats every minute would fill logs/ with them.
        try:
            tmp.unlink(missing_ok=True)
        except (OSError, UnboundLocalError):
            pass


# Beating only between ticks was not enough.  A reasoning pass runs for tens of
# minutes and is allowed three hours, so the heartbeat would go stale WHILE THE
# SUPERVISOR WAS WORKING -- runstate.supervisor() would report it dead, the
# briefing would say nobody is home mid-pass, and claim_lock() would treat the
# lock as a corpse and let a second supervisor start on top of the first.  Two
# of them read the registration budget independently, so both could see three
# booked and make the fifth and sixth.
HEARTBEAT_S = 60


def start_heartbeat() -> "threading.Event":
    """Beat the lock on its own thread for the life of the process."""
    import threading
    stop = threading.Event()

    def _beat() -> None:
        while not stop.wait(HEARTBEAT_S):
            beat_lock()

    t = threading.Thread(target=_beat, name="orc-heartbeat", daemon=True)
    t.start()
    return stop


def release_lock() -> None:
    try:
        LOCK.unlink()
    except OSError:
        pass


# ---------------------------------------------------------------------------
# turning an action into a command
# ---------------------------------------------------------------------------
def track_b_cell() -> tuple[str, str] | None:
    """A (hypothesis, symbol) pair execution_realism can actually run.

    It is a Track B tool, and the symbol is not a free choice: taking the best
    cell across the ledger would be the maximum-hunting the protocol exists to
    contain.  So this takes the cell each family's OWN pre-registered surface
    report already names, which is the same rule briefing.py follows.
    """
    from orc.orchestrator.spec import load_registry
    import contextlib
    import io
    with contextlib.redirect_stdout(io.StringIO()):
        every = load_registry(include_closed=True)
    for h in every:
        if h.track != "B":
            continue
        rep = config.REPORTS / f"{h.hypothesis_id}_SURFACE.json"
        if not rep.exists():
            continue
        try:
            surfaces = json.loads(rep.read_text(encoding="utf-8")).get("surfaces") or {}
        except ValueError:
            continue
        if not surfaces:
            continue
        sym = max(surfaces.items(),
                  key=lambda kv: kv[1].get("best_value") or -9e9)[0]
        return h.hypothesis_id, sym
    return None


def plan(action: str) -> list[str] | None:
    """The command for an action, or None when it does not apply right now.

    None is not a failure and is recorded as work done: the staleness clock has
    to reset either way, or an inapplicable action would be selected on every
    tick forever and the supervisor would never get to anything else.
    """
    py = sys.executable
    if action == "reason":
        return [py, str(config.ORC_ROOT / "scripts" / "reasoning.py")]
    if action == "scout":
        return [py, str(config.ORC_ROOT / "scripts" / "scout.py")]
    if action == "kernel_review":
        return [py, str(config.ORC_ROOT / "scripts" / "kernel_review.py")]
    if action == "robustness":
        return [py, str(config.ORC_ROOT / "scripts" / "robustness.py")]
    if action == "survivorship":
        return [py, str(config.ORC_ROOT / "scripts" / "kt3_survivorship.py"), "120"]
    if action == "execution_realism":
        cell = track_b_cell()
        if cell is None:
            return None
        return [py, str(config.ORC_ROOT / "scripts" / "execution_realism.py"),
                cell[0], cell[1]]
    return None


def run(cmd: list[str], timeout_s: int) -> tuple[int, str]:
    """Run one action.  Its output is the detail line; it never raises."""
    env = dict(os.environ)
    # The gate and the notifier answer in Korean and this console is cp949; a
    # print that raises would take an action down over a dash, which is how the
    # first full panel build died at symbol 807 of 810.
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        r = subprocess.run(cmd, cwd=config.ORC_ROOT, capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=timeout_s, env=env, check=False)
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout_s}s"
    except OSError as exc:
        return 125, f"{type(exc).__name__}: {exc}"
    tail = [l for l in (r.stdout or "").splitlines() if l.strip()][-6:]
    if r.returncode != 0 and (r.stderr or "").strip():
        tail += [l for l in r.stderr.splitlines() if l.strip()][-3:]
    return r.returncode, " | ".join(tail)


def land(action: str) -> str:
    """Commit and push what an action produced, by name.

    Without this the scout notebook and the review findings live only on this
    workstation, and the whole point of committing them is that the worker's
    proposer and a phone can both read them.  A push failure is reported and
    not retried: the next action's commit carries it, and reasoning.py already
    pushes anything outstanding before it reasons.
    """
    paths = [p for p in COMMIT_PATHS.get(action, ()) + ALWAYS_COMMIT
             if (config.ORC_ROOT / p).exists()]
    if not paths:
        return "nothing to commit"
    subprocess.run(["git", "add", *paths], cwd=config.ORC_ROOT, check=False,
                   capture_output=True)
    staged = subprocess.run(["git", "diff", "--cached", "--quiet", "--", *paths],
                            cwd=config.ORC_ROOT, check=False)
    if staged.returncode == 0:
        subprocess.run(["git", "reset", "-q", "--", *paths],
                       cwd=config.ORC_ROOT, check=False, capture_output=True)
        return "no change to commit"
    subprocess.run(["git", "commit", "-q", "-m",
                    f"forever: {action}", "--", *paths],
                   cwd=config.ORC_ROOT, check=False, capture_output=True)
    pushed = subprocess.run(["git", "push", "-q"], cwd=config.ORC_ROOT,
                            check=False, capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    if pushed.returncode != 0:
        return f"committed, push failed: {(pushed.stderr or '').strip()[:120]}"
    return "committed and pushed"


# ---------------------------------------------------------------------------
def tick(dry_run: bool = False) -> tuple[str, int]:
    """One decision and, unless dry, one action.  Returns (action, sleep_s)."""
    action, why = runstate.next_action()
    log(f"next: {action} -- {why}")
    if dry_run:
        return action, 0
    if action == "blocked":
        runstate.record_activity(action, why)
        return action, BLOCKED_SLEEP_S
    if action == "rest":
        # Deliberately NOT recorded as an activity: a rest tick would reset no
        # clock and writing it would bury the log in lines saying nothing
        # happened.  The gate's own reason is already in the wake-up log.
        return action, IDLE_SLEEP_S

    cmd = plan(action)
    if cmd is None:
        runstate.record_activity(action, "not applicable right now", 0.0)
        log(f"{action}: not applicable right now; clock reset so the next "
            f"action gets a turn")
        return action, WORKED_SLEEP_S

    started = time.monotonic()
    rc, detail = run(cmd, TIMEOUTS_S.get(action, 3600))
    took = time.monotonic() - started
    landed = land(action)
    done = rc in DONE_EXIT_CODES.get(action, (0,))
    runstate.record_activity(action, f"exit {rc}: {detail} [{landed}]", took,
                             ok=done)
    log(f"{action}: exit {rc} ({'done' if done else 'did not run'}) "
        f"in {took / 60:.1f}m -- {detail[:220]}")
    log(f"{action}: {landed}")
    return action, WORKED_SLEEP_S


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    once = "--once" in argv or dry
    if not dry and not claim_lock():
        return 3
    log(f"=== supervisor start (pid {os.getpid()}, "
        f"budget {config.MAX_REGISTRATIONS_PER_DAY} registrations/24h) ===")
    stop_beat = None if dry else start_heartbeat()
    try:
        while True:
            try:
                _, nap = tick(dry_run=dry)
            except KeyboardInterrupt:
                raise
            except Exception as exc:                               # noqa: BLE001
                # A supervisor that dies on an unexpected error is the thing
                # this file exists to stop.  Report it and keep going: the next
                # tick re-derives everything from the tree.
                import traceback
                log(f"TICK FAILED: {type(exc).__name__}: {exc}")
                log(traceback.format_exc(limit=4))
                runstate.record_activity(
                    "tick_failed", f"{type(exc).__name__}: {exc}")
                nap = IDLE_SLEEP_S
            if once:
                return 0
            time.sleep(nap)
    except KeyboardInterrupt:
        log("=== supervisor stopped by hand ===")
        return 0
    finally:
        if stop_beat is not None:
            stop_beat.set()
        if not dry:
            release_lock()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
