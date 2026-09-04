"""ORC | The question N exists to answer, finally asked.

The ledger counts every trial and calls that count N, and the constitution says
N feeds the multiple-testing correction applied to every result. The counting
worked. The correction was never implemented: `best_of_g_pvalue`,
`circular_block_bootstrap` and `synthetic_prices` sat in the kernel unreferenced
by anything, tests included, while N was printed at the end of each cycle and
consumed by nothing.

So every verdict up to now asked whether a cell was a spike, whether it rested
on enough independent paths, whether the selection carried information, and
whether it cleared break-even -- and never once asked the question underneath
all of them: given that this many configurations were tried, how surprising is
the best of them?

The answer needs a null with the same search in it. The grid is re-run on
synthetic histories bootstrapped from the symbol's own returns in wrap-around
blocks, so each synthetic keeps the volatility clustering and drawdown shape of
the real series but none of its structure. Taking the best cell on each
synthetic builds the distribution of "best of G by luck alone", and the real
best is compared against it.

Running fewer configurations against the null than were tried for real
understates it and manufactures significance, so the same grid runs both times.
That is what makes this expensive and what makes it worth anything.
"""
from __future__ import annotations

import multiprocessing
import os
import pickle
import sys
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from functools import partial

import numpy as np

from orc.kernel.inference import best_of_g_pvalue, synthetic_prices

# Frozen before any family cleared. A day of hourly bars keeps the local
# dependence a DCA or a hold-for-days rule actually experiences; shorter blocks
# resample away the drawdowns that decide the left tail.
BOOTSTRAP_BLOCK_BARS = 24

# Enough for a 5% threshold to mean something without the run costing an hour:
# with 199 synthetics the smallest reportable p-value is 1/200.
N_SYNTHETIC_PATHS = 199

# A best that a random search would beat one time in twenty is not a finding.
ALPHA = 0.05


# The workstation is a machine the owner is sitting at
# --------------------------------------------------------------------------
# This pool used os.cpu_count() directly: 24 workers on 24 cores, zero
# headroom. It survived that way only because the search test ran on two
# symbols; widening it to nine on 2026-09-05 pegged the machine and the owner
# said "다른 작업을 못하겠음". That is not a performance complaint, it is the
# research stopping: a loop that makes the workstation unusable gets switched
# off, and a switched-off loop runs at zero.
#
# A FRACTION rather than a count, because the runner has four cores and
# reserving a fixed number there would leave nothing -- and nobody is sitting
# at the runner. ORC_WORKERS still overrides both, which is how the workflow
# pins 4.
#
# Neither number can change an answer. The synthetic paths are drawn up front
# from one seeded generator and consumed in order, so the pool decides how long
# the null takes and nothing about what it says.
CPU_HEADROOM_FRACTION = 0.25    # the owner's share, frozen the day the screen froze
MIN_CORES_BEFORE_SHARING = 8    # below this the machine is a worker, not a desk


def n_workers(n_tasks: int) -> int:
    """How many processes to spread the null over.

    The synthetic paths are independent by construction -- that is what makes
    the null a null -- so this is the one genuinely embarrassing parallelism in
    the project, and it sits on the single most expensive thing it does.
    Measured on H0001/BTCUSDT: 4.77s for one path over the grid, 15.8 minutes
    for 199, 31.7 for the two symbols a report covers.  That was the research
    cycle: a 24-core workstation running one core.

    ORC_WORKERS overrides, because the GitHub runner has far fewer cores than
    the workstation and a pool wider than the machine is slower, not faster.
    """
    env = os.environ.get("ORC_WORKERS", "").strip()
    if env:
        try:
            n = int(env)
        except ValueError:
            n = 0
        if n > 0:
            return max(1, min(n, n_tasks))

    total = os.cpu_count() or 1
    if total >= MIN_CORES_BEFORE_SHARING:
        total -= max(1, int(total * CPU_HEADROOM_FRACTION))
    return max(1, min(total, n_tasks))


# Windows has no os.nice, and this needs no new dependency.
_BELOW_NORMAL_PRIORITY_CLASS = 0x00004000


def _yield_to_the_owner() -> None:
    """Run each worker below normal priority.

    Headroom alone does not make a machine usable: eighteen workers spinning at
    normal priority still make a foreground window stutter, because the
    scheduler has no reason to prefer it. Below-normal says the owner's editor
    wins every time they touch it and the null gets the rest -- which costs
    nothing at all on an idle machine, and is exactly the trade wanted on a
    busy one.

    Best effort by design. A platform where this fails is a platform where the
    null still has to run, so a failure here is silent -- which is exactly why
    it is checked rather than assumed. The first version of this function
    called SetPriorityClass without declaring argtypes, so ctypes marshalled
    the 64-bit pseudo-handle (-1) as a 32-bit int, the call failed, and every
    worker went on running at Normal while the code claimed otherwise.
    GetPriorityClass returning 0 is what caught it.
    """
    try:
        if sys.platform == "win32":
            import ctypes
            k = ctypes.windll.kernel32                             # type: ignore[attr-defined]
            k.GetCurrentProcess.restype = ctypes.c_void_p
            k.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
            k.SetPriorityClass.restype = ctypes.c_int
            k.SetPriorityClass(k.GetCurrentProcess(),
                               _BELOW_NORMAL_PRIORITY_CLASS)
        else:
            os.nice(10)
    except Exception:                                              # noqa: BLE001
        pass


def _restore_priority(value: int | None) -> None:
    """Undo _yield_to_the_owner.  A no-op where there was nothing to read."""
    if value is None or sys.platform != "win32":
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32                                 # type: ignore[attr-defined]
        k.GetCurrentProcess.restype = ctypes.c_void_p
        k.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        k.SetPriorityClass(k.GetCurrentProcess(), value)
    except Exception:                                              # noqa: BLE001
        pass


def owner_priority() -> int | None:
    """This process's Windows priority class, or None where there is no such
    thing.  Exists so that a test can assert _yield_to_the_owner WORKED rather
    than that it ran without raising."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        k = ctypes.windll.kernel32                                 # type: ignore[attr-defined]
        k.GetCurrentProcess.restype = ctypes.c_void_p
        k.GetPriorityClass.argtypes = [ctypes.c_void_p]
        k.GetPriorityClass.restype = ctypes.c_uint32
        return int(k.GetPriorityClass(k.GetCurrentProcess()))
    except Exception:                                              # noqa: BLE001
        return None


def _safe_score(score_grid, close) -> float:
    """One synthetic path, scored, with a failure reported as nan.

    A path the grid cannot express is information about the grid and must not
    take the run down -- the serial loop caught this inline, and a pool has to
    catch it INSIDE the worker or the exception surfaces when the result is
    consumed and kills the whole null.
    """
    try:
        v = float(score_grid(close))
    except Exception:                                              # noqa: BLE001
        return float("nan")
    return v if np.isfinite(v) else float("nan")


def pool_context():
    """Always spawn, never fork.

    Linux defaults to fork and Windows has only spawn, and that difference cost
    this project a job: the workstation ran the pooled null in 3.1 minutes and
    the Linux runner sat in the same step past 50 minutes, having taken 35 when
    it was serial.

    Forking is the reason.  polars runs a Rayon thread pool -- 24 threads on
    this machine -- and `fork` copies the memory of those threads without the
    threads themselves, so any lock one of them held at the instant of the fork
    is held forever in the child.  Every worker here calls panel.load, which is
    `pl.read_parquet`, so every worker reached for a lock that could never be
    released.  Not slow: stopped.

    Spawn starts each worker from a clean interpreter.  It costs a second or so
    per worker to re-import, once, against workers that then live for the whole
    batch -- and it makes the two platforms behave the same way, which for a
    project whose results have to match across machines is worth more than the
    second.
    """
    return multiprocessing.get_context("spawn")


def _is_picklable(obj) -> bool:
    """Can this scorer cross a process boundary?

    The scorers in surface.py are objects precisely so that they can.  A plain
    closure -- what a test or a one-off analysis naturally writes -- cannot, and
    must quietly fall back to the serial path rather than raising.
    """
    try:
        pickle.dumps(obj)
        return True
    except Exception:                                              # noqa: BLE001
        return False


def best_of_g(observed_best: float, score_grid, panel, n_configs: int,
              seed: int = 20260902,
              n_paths: int = N_SYNTHETIC_PATHS,
              block: int = BOOTSTRAP_BLOCK_BARS) -> dict:
    """Compare the observed best against the best a search finds in noise.

    `score_grid(close)` runs the whole grid on one price series and returns the
    best value it finds. It is called once per synthetic path, so it carries
    the cost of the entire search -- which is the point.
    """
    rng = np.random.default_rng(seed)
    synth = synthetic_prices(panel.close, block, n_paths, rng)

    # Every path is drawn up front from one seeded generator and the results are
    # consumed IN ORDER, so the pool changes how long this takes and nothing
    # about what it answers: the same seed gives the same nulls, serial or not.
    paths = [synth[i] for i in range(n_paths)]
    workers = n_workers(len(paths))
    scored: list[float] = []
    if workers > 1 and _is_picklable(score_grid):
        chunk = max(1, len(paths) // (workers * 4))
        # Lower THIS process first, because a spawned child inherits its
        # parent's priority class: the initializer cannot run until the worker
        # has re-imported numpy and polars, and eighteen workers doing that at
        # Normal is a second or two of exactly the stutter this avoids. The
        # initializer stays as the belt to this pair of braces -- it is what
        # covers a platform where the parent call failed.
        was = owner_priority()
        _yield_to_the_owner()
        try:
            with ProcessPoolExecutor(max_workers=workers,
                                     mp_context=pool_context(),
                                     initializer=_yield_to_the_owner) as pool:
                scored = list(pool.map(partial(_safe_score, score_grid), paths,
                                       chunksize=chunk))
        except (BrokenProcessPool, OSError) as exc:
            # A pool that dies takes every result with it, including the ones
            # already computed, so the p-value would be lost to an accident of
            # scheduling -- a worker killed for memory, a fork that failed, a
            # runner reclaiming the machine. The whole point of the null is
            # that it is expensive and worth having, so pay for it serially
            # rather than report no answer.
            print(f"  the worker pool broke ({type(exc).__name__}: "
                  f"{str(exc)[:120]}); re-running the null on one core",
                  flush=True)
            scored = []
        finally:
            # Put this process back where it was found. best_of_g is called
            # from inside a cycle that goes on to do other things, and silently
            # leaving the caller de-prioritised is a side effect nobody asked
            # for -- the serial fallback below runs at the restored priority
            # for the same reason.
            _restore_priority(was)
    if not scored:
        scored = [_safe_score(score_grid, close) for close in paths]

    nulls = [v for v in scored if np.isfinite(v)]

    if len(nulls) < n_paths // 2:
        return {"status": f"only {len(nulls)} of {n_paths} synthetic searches scored; "
                          f"the null is too thin to compare against"}

    r = best_of_g_pvalue(observed_best, np.array(nulls), n_configs)
    return {
        "status": "ok",
        "observed_best": r.observed_best,
        "null_mean": r.null_mean,
        "null_q95": r.null_q95,
        "p_value": r.p_value,
        "n_null": r.n_null,
        "n_configs": r.n_configs,
        "block_bars": block,
        "verdict": r.verdict(),
        # The null was built by running the same grid, so a p-value at or above
        # alpha says a search this wide finds this good a cell in pure noise
        # about that often.
        "survives_search": bool(r.p_value < ALPHA),
    }
