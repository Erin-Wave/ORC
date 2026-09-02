"""ORC | The gate a cell has to pass before it is a candidate for anything.

A backtest answers one question: what would this rule have returned on this
history, at these costs, over this window.  Every part of that sentence is a
condition, and a rule that only survives its own conditions has not been tested
-- it has been described.  These checks vary each condition in turn and ask
whether the answer holds.

  cost      Fees and slippage are estimates.  A rule whose sign depends on them
            being right is a rule about the estimate, not about the market, so
            the same cell is re-run at twice the assumed cost.

  walk      A cell chosen on the whole window was chosen with knowledge of the
            whole window.  The development period is split into blocks, the
            best cell is picked on the earlier ones, and it is then judged only
            on the later ones -- which is the only part of the answer that was
            not used to ask the question.

  regime    Six years of crypto is roughly one enormous bull run with two
            crashes in it.  A rule that makes all its money in one of those and
            gives it back in the other has found a regime, not an edge, and
            splitting the window by direction says which it is.

None of these opens the sealed holdout.  They partition the development period,
which research may already see in full; the holdout stays for the three final
measurements and nothing here brings them forward.

A cell that fails any of these is not a candidate.  Passing all three does not
make it one either -- it makes it worth spending one of three openings on.
"""
from __future__ import annotations

import numpy as np

# Frozen before any Track B result was seen.
COST_STRESS_MULTIPLIER = 2.0    # what "twice the assumed cost" means
N_WALK_BLOCKS = 4               # split the development window into quarters
TRAIN_BLOCKS = 2                # choose on the first half, judge on the rest
MIN_BLOCK_BARS = 24 * 30        # a block under a month cannot judge anything

# How much of the in-sample result the out-of-sample blocks must retain. Sign
# alone is not a test: H0002's best BTCUSDT cell went 1.790 in-sample to 0.159
# out, lost 91 percent of its edge, and was recorded as passing because both
# numbers were positive. Frozen at half before any family cleared the gate.
MIN_OOS_RETENTION = 0.5


def _sign_survives(base: float, stressed: float) -> bool:
    """The stressed result must keep the sign and not collapse to noise."""
    if not (np.isfinite(base) and np.isfinite(stressed)):
        return False
    return base > 0 and stressed > 0


def cost_stress(evaluate, cfg, panel) -> dict:
    """Re-run one cell at COST_STRESS_MULTIPLIER times the assumed cost."""
    base = evaluate(cfg, panel)
    stressed = evaluate(cfg.with_costs(COST_STRESS_MULTIPLIER), panel)
    return {
        "check": "cost",
        "multiplier": COST_STRESS_MULTIPLIER,
        "base": base,
        "stressed": stressed,
        "passed": _sign_survives(base, stressed),
    }


def walk_forward_blocks(n_bars: int, n_blocks: int = N_WALK_BLOCKS) -> list[tuple[int, int]]:
    """Contiguous, equal, non-overlapping [start, end) blocks of the window."""
    if n_bars // n_blocks < MIN_BLOCK_BARS:
        raise ValueError(
            f"{n_bars} bars split {n_blocks} ways gives blocks under "
            f"{MIN_BLOCK_BARS} bars; the split would not be evidence")
    edges = np.linspace(0, n_bars, n_blocks + 1).astype(int)
    return [(int(edges[i]), int(edges[i + 1])) for i in range(n_blocks)]


def walk_forward(evaluate_on, cells, panel,
                 n_blocks: int = N_WALK_BLOCKS,
                 train_blocks: int = TRAIN_BLOCKS) -> dict:
    """Choose on the early blocks, report only what the late blocks say.

    `evaluate_on(cell, panel, lo, hi)` scores one cell on one slice.  The
    selection sees the training blocks and nothing else, so the reported number
    is the first thing about this cell that was not used to pick it.
    """
    blocks = walk_forward_blocks(len(panel), n_blocks)
    train, test = blocks[:train_blocks], blocks[train_blocks:]
    if not test:
        raise ValueError("no blocks left to judge on after training")

    scored = []
    for c in cells:
        vals = [evaluate_on(c, panel, lo, hi) for lo, hi in train]
        vals = [v for v in vals if np.isfinite(v)]
        if vals:
            scored.append((float(np.mean(vals)), c))
    if not scored:
        return {"check": "walk_forward", "passed": False,
                "reason": "no cell could be scored in-sample"}

    in_sample, chosen = max(scored, key=lambda kv: kv[0])
    out = [evaluate_on(chosen, panel, lo, hi) for lo, hi in test]
    out = [v for v in out if np.isfinite(v)]
    oos = float(np.mean(out)) if out else float("nan")
    return {
        "check": "walk_forward",
        "n_blocks": n_blocks,
        "train_blocks": train_blocks,
        "chosen": chosen.to_dict() if hasattr(chosen, "to_dict") else str(chosen),
        "in_sample": in_sample,
        "out_of_sample": oos,
        "retention": (oos / in_sample) if in_sample > 0 and np.isfinite(oos) else float("nan"),
        # Chosen blind to these blocks, so this is the honest number -- and it
        # has to survive as a quantity, not merely as a sign.
        "passed": bool(_sign_survives(in_sample, oos)
                       and oos >= MIN_OOS_RETENTION * in_sample),
    }


def regime_split(close: np.ndarray, window_bars: int) -> np.ndarray:
    """+1 where the trailing window rose, -1 where it fell, 0 until it is full.

    Trailing, never centred: a centred label would tell the rule which way the
    market was about to go, which is the whole thing being tested against.
    """
    close = np.asarray(close, dtype=np.float64)
    out = np.zeros(close.size, dtype=np.int8)
    if close.size <= window_bars:
        return out
    past = close[:-window_bars]
    now = close[window_bars:]
    out[window_bars:] = np.where(now > past, 1, -1)
    return out


def regime_consistency(evaluate_masked, cfg, panel, window_bars: int) -> dict:
    """Score the same cell separately on the rising and falling regimes."""
    reg = regime_split(panel.close, window_bars)
    up, down = reg == 1, reg == -1
    if up.sum() < MIN_BLOCK_BARS or down.sum() < MIN_BLOCK_BARS:
        return {"check": "regime", "passed": False,
                "reason": f"one regime has under {MIN_BLOCK_BARS} bars "
                          f"(up {int(up.sum())}, down {int(down.sum())})"}
    rising = evaluate_masked(cfg, panel, up)
    falling = evaluate_masked(cfg, panel, down)
    measured = np.isfinite(rising) and np.isfinite(falling)
    out = {
        "check": "regime",
        "window_bars": window_bars,
        "rising": rising,
        "falling": falling,
        # Both, not either.  A rule that only works while price rises is a
        # long position wearing a rule's clothes.
        "passed": (rising > 0 and falling > 0) if measured else None,
    }
    if not measured:
        # Say which side could not be scored.  A cell whose horizon eats the
        # whole archive has every start date inside the label's warm-up window,
        # which is worth reading as a fact about the cell rather than as a
        # missing number.
        out["reason"] = ("the cell could not be scored in "
                         + " and ".join(n for n, v in (("rising", rising),
                                                       ("falling", falling))
                                        if not np.isfinite(v)))
    return out


def verdict(checks: list[dict]) -> dict:
    """One line for the report: did every check hold, and if not, which did not.

    A check that could not run is reported as unmeasured, never as a failure.
    Calling it a failure is a lie in the safe direction, which is still a lie
    and hides the fact that the gate has a hole in it -- and a hole reported as
    a failure never gets fixed, because the gate looks like it is working.

    An unmeasured check still stops a cell from passing.  Not knowing is not
    the same as knowing it is fine.
    """
    failed = [c["check"] for c in checks if c.get("passed") is False]
    unmeasured = [c["check"] for c in checks if c.get("passed") is None]
    return {
        "passed": not failed and not unmeasured,
        "failed": failed,
        "unmeasured": unmeasured,
        "checks": checks,
    }
