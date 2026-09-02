# ORC — project constitution

ORC researches two questions on Binance USDⓈ-M perpetuals, deeply and honestly.

> **Track A — accumulation.** Is there a **DCA-shaped** rule whose worst
> realistic outcome is acceptable — and if not, exactly where and why does each
> variant break?
>
> **Track B — positions.** Is there a **signal-driven** rule, entering long or
> short and exiting on its own signal, whose worst realistic outcome is
> acceptable — and if not, where does it break?

Track B opens where KT-1 left off. Long-side perp accumulation was closed
because it pays a structural funding tax; the mirror of that tax — standing on
the side that *collects* funding — is the first family Track B asks about.

The deliverable is **a map of where these rules break**, not "the optimal
setting". `FAIL` is a publishable result. A cycle that closes a family has done
its job.

The two tracks share this document, the sealed holdout, the ledger and its `N`.
They differ only in what a position is, and therefore in which metrics are
defined — see section 4.

---

## 1. Clean room — absolute

Other research trees exist on this machine (`D:\Project\...`). **Do not read,
import, copy, or reference any of them.** ORC is built from scratch. Their
conclusions, thresholds, metric definitions and code are all out of scope.

`orc/clean_room.py` lists the forbidden names and `tests/test_kernel.py::
test_no_prior_lab_artifacts_referenced` enforces the boundary on every run.

## 2. The sealed holdout — enforced, not promised

Everything from **2024-03-01** onward is sealed (`config.HOLDOUT_START`).

- Research code calls `panel.load(...)` which truncates at the seal. There is no
  other supported way to read a panel.
- The cloud bundle is built from the truncated data, so a remote worker does not
  physically possess the sealed period.
- `holdout.open_final_test()` is the only door. It requires a hand-written token
  file, logs the candidate hash, deletes the token, and **stops permanently
  after 3 openings for the life of the project**.

Never propose opening the holdout to "check" something. There is no such thing
as checking; there are three measurements and then there are none.

## 3. Pre-registration — the claim comes before the number

A hypothesis is a JSON file dropped in `configs/queue/`. It carries a prose
claim, a kill condition, a universe, and an **exhaustive** parameter grid. On
intake it is hashed. After that the grid and the claim cannot be edited — a
changed hypothesis must get a new id.

```json
{
  "hypothesis_id": "H0007",
  "family": "dip_gated_dca",
  "claim": "Who is structurally paying, and why they keep doing it.",
  "kill_condition": "The result that would close this family, written now.",
  "universe": ["BTCUSDT", "ETHUSDT"],
  "grid": {"stride_days": [1, 7, 30], "n_contributions": [52, 104, 156]},
  "fixed": {"contribution": 100.0, "clock": "1h"}
}
```

## 4. Metrics — cash-flow aware, left-tail first

**Track A.** DCA takes external deposits, so fixed-capital metrics are simply
wrong:

| Never use | Because | Use instead |
|---|---|---|
| CAGR | no defined denominator once capital keeps arriving | **MWRR / IRR** |
| equity drawdown | later deposits refill the account at the worst moment | **drawdown on invested capital** |
| mean outcome | DCA outcomes are strongly right-skewed | **`tm_q05`**, the 5th-percentile terminal multiple |

`PRIMARY_METRIC = "tm_q05"`. The mean is reported and must not be argued from.

`tm_q05` is a multiple of contributed capital, so it grows with the horizon and
**may not be compared between cells that hold for different lengths of time.**
The annualised IRR is the comparison that survives a horizon change, and both
appear side by side in every report.

**Track B.** A signal strategy starts from one capital and takes no deposits,
so every objection above disappears and the familiar ratios are exactly right:
**CAGR, maximum drawdown on equity, Calmar, Sharpe.** Report all four.

What does *not* transfer is where independence comes from. Track A gets its
ensemble from start dates; a signal rule simply runs, giving one equity curve
per symbol. Its independent-path count therefore comes from the number of
symbols and the number of non-overlapping time blocks, never from bar count. A
Sharpe computed on one curve over one history is one experiment, and must be
reported as one.

The left tail still decides. A strategy is described by its worst realistic
outcome across that ensemble, never by its average.

## 5. Two evaluators that check each other

- `orc/eval/analytic.py` — closed-form, prefix sums, **every** start date in
  O(N). Exact only for unconditional, unlevered, no path exit.
- `orc/eval/simulate.py` — bar-by-bar, vectorised across start dates. Handles
  gates, leverage, liquidation, TP/SL. DCA-shaped: a schedule of contributions.
- `orc/eval/signal.py` — Track B. One position at a time, entered long or short
  on a signal and closed on a signal, stop or liquidation. Fixed capital, so it
  produces an equity curve rather than a terminal multiple.

`tests/test_kernel.py::test_analytic_matches_simulator` requires them to agree
to machine precision on the shape both can express. **If that test fails, every
result in the project is void.** Fix it before anything else.

## 6. Search discipline

The parameter space is enumerated exhaustively, never sampled. Consequently:

- **The grid handles parameters. The reasoning layer handles rule SHAPE.**
  Proposing a finer grid over an existing rule form is not a new hypothesis; it
  is noise mining. Propose a different mechanism.
- Every trial lands in the append-only ledger. The row count is `N` and feeds
  the multiple-testing correction. It cannot be reduced.
- Read the **shape** column before the value. A `SPIKE` is not a finding no
  matter how large. A `PLATEAU` is weak evidence. Neither is proof.
- `PBO >= 0.5` means the selection carries no information at all.
- Read `effective_independent_paths`. Millions of start offsets over six years
  of history is still only a handful of independent experiments. Say so.

## 7. Established results — do not re-litigate

| Test | Result | Consequence |
|---|---|---|
| KT-1 funding drag | median funding bill **36 % of contributed capital** over a 3-year weekly DCA; 87 % of BTC settlements positive | **perpetual LONG DCA is closed.** Long-side perp accumulation pays a structural tax. Its mirror — collecting funding on the short/carry side — is the open question. |
| KT-2 martingale | liquidation rate hits **100 % at 2× and above** on the current development window | leverage above 1× is closed for averaging-down |
| KT-3 survivorship | 986 symbols ever traded, 481 in the local archive, 266 delisted; usable delisted sample still too small | **inconclusive** — no alt-basket hypothesis until it is resolved with a larger sample |

## 8. Commands

```bash
python -m orc.facts.build_panel                 # vendor CSV -> panels
python -m orc.facts.fetch_vision BTCUSDT ...    # funding history
python -m orc.facts.fetch_vision lifecycle      # listing/delisting table
python scripts/kt1_funding_drag.py              # kill tests
python scripts/kt2_martingale.py
python scripts/kt3_survivorship.py 120
python scripts/daily_cycle.py                   # one research cycle
python scripts/deploy_panel.py                  # build the cloud bundle
python -m pytest tests -q                       # must be green before anything
```

## 9. What a reasoning cycle does

1. Read **only** `reports/CYCLE_REPORT.md`. Do not go trawling the ledger for a
   better-looking number; that is the search bias this whole design exists to
   contain.
2. For each family, decide: **continue, or close it** against its own
   pre-registered kill condition.
3. Propose 1–3 new hypotheses. Each must name **who is structurally paying**.
   "This pattern backtests well" is not a mechanism and will be rejected.
4. Write them to `configs/queue/*.json` and commit. The worker picks them up.
5. Never edit a registered hypothesis. Never touch `ledger/`. Never widen a
   threshold after seeing a result.

## 10. Style

Match the existing code: numpy-first, no backtesting framework, no ML stack,
no GPU. Comments explain *why* a rule exists, not what a line does. Every
threshold is a constant at the top of its module with a comment saying it was
frozen before results were seen.
