# ORC

Autonomous research into **DCA-shaped strategies** on Binance USDⓈ-M perpetuals.

Built clean-room. Runs unattended, for free, with the workstation switched off.
`FAIL` is a publishable result — the deliverable is a map of where DCA breaks,
not an optimal setting.

**Setup:** [`MANUAL_SETUP.md`](MANUAL_SETUP.md) (Korean) — the four things only a
human can do. **Rules:** [`CLAUDE.md`](CLAUDE.md).

---

## Why DCA is not an ordinary backtest

Three structural differences drive the whole design.

**Enumeration, not search.** DCA has about eight real knobs. The grid is
enumerated exhaustively, so the *response surface* is the evidence — an isolated
spike is an artefact, a plateau is weak evidence. Stochastic search would only
ever hand back the spike.

**Start-date dependence dominates.** The result is mostly a function of *when you
began*. So the primary object is the distribution over every possible start
date, and the primary metric is its **5th percentile**, not its mean.

**Cash-flow accounting is the substance.** External deposits keep arriving, so
CAGR has no denominator and equity drawdown is flattered by later deposits
arriving exactly when the account is deepest under.

## The trick that makes it cheap

For unconditional fixed-interval DCA the terminal outcome is a linear functional
of the price path:

```
units(s) = C' * SUM_{j<n} 1/P[s + jk]
```

Split `1/P` into its `k` residue classes, take one cumulative sum per class, and
one lagged difference gives the answer for **every** start offset at once —
`O(N)`, not `O(N × starts)`. Perpetual funding reduces to the same form via a
suffix sum, so it is free too.

Measured on real BTCUSDT 1-minute data: **3,038,013 start dates in 0.30 s**,
matching a brute-force reference to 1e-13.

That is why the cloud tier is small. Only conditional deployment, leverage and
path-dependent exits need an actual simulator.

## Architecture

```
facts/      immutable panels. 1m local, 1h shipped to the worker,
            both truncated at the holdout seal
kernel/     liquidation (Binance MMR tiers, tested at the bar low),
            cash-flow metrics, PBO / bootstrap inference
eval/       analytic.py   closed form, every start date, O(N)
            simulate.py   bar-by-bar, vectorised across starts
ledger/     append-only SQLite. The row count is N and feeds the statistics
orchestrator/ pre-registered hypotheses, exhaustive expansion, response surfaces
```

### Two evaluators that check each other

`test_analytic_matches_simulator` requires the closed-form evaluator and the
path simulator to agree to machine precision on the shape both can express.
Two independent implementations of the same accounting, cross-checked. If that
test fails, every result in the project is void.

### Three things that say no

- **Append-only ledger** — SQL triggers block UPDATE and DELETE. A later cycle
  cannot retire the trials that make its own discovery look lucky.
- **Pre-registration hash** — the claim and the grid are hashed on intake.
  Editing either afterwards is refused; it needs a new hypothesis id.
- **Sealed holdout** — the worker bundle physically excludes everything from
  2024-03-01. Opening it needs a hand-written token, is logged with the
  candidate hash, and stops permanently after three openings.

## Free 24/7, with the PC off

| Tier | Where | Cost |
|---|---|---|
| Search | GitHub Actions, public repo (unmetered minutes, 6 h/job, re-fires 6-hourly) | ₩0 |
| Data | GitHub Release asset (2 GB limit; the 1h bundle is ~500 MB) | ₩0 |
| Reasoning | Claude Code routine, Anthropic cloud, 15 runs/day on Max | ₩0 |

The grid handles parameters. The reasoning layer handles rule *shape*, and must
name who is structurally paying. Letting an LLM tune parameters would only
inflate `N`.

## Results so far

| Kill test | Result | Consequence |
|---|---|---|
| **KT-1** funding drag | median funding bill **36 % of contributed capital** over a 3-year weekly DCA; 87 % of BTC settlements positive; BTC spot-style ×1.177 → perp long ×0.780 | perpetual **long** DCA closed |
| **KT-2** martingale | liquidation **100 % at 2× and above** on the current window | leverage > 1× closed for averaging-down |
| **KT-3** survivorship | 986 symbols ever traded, 481 archived locally, 266 delisted | **inconclusive**, sample too small |

KT-1's corollary is the open question: if longs pay this reliably, the short and
carry side is collecting it.

### One number to keep in view

Six years of history and a three-year horizon leaves start dates spanning three
years, and those paths overlap almost entirely. Every trial reports
`effective_independent_paths` — for a 3-year BTC horizon it is **about 1.5**.
Millions of start offsets do not change that, and no amount of compute will.

## Quick start

```bash
pip install -r requirements.txt
python -m pytest tests -q                # 38 tests, must be green
python -m orc.facts.build_panel BTCUSDT  # one symbol
python scripts/kt1_funding_drag.py
python scripts/daily_cycle.py
```
