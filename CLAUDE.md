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
- **Breadth first, and depth is earned by a result.** A mechanism with no rows
  in the ledger gets a **probe**: at most `MAX_PROBE_CONFIGURATIONS` cells,
  spent only on the axes that decide whether the mechanism is there at all. If
  it survives its own kill condition, a second registration under a **new id**
  may enumerate it as wide as `MAX_CONFIGURATIONS_PER_HYPOTHESIS`. Enforced at
  intake, not advised.

  The ledger is why. H0002 registered 972 cells on the first and only test its
  mechanism ever got and now holds **73 % of N** while closed; H0006 answered
  its question with 72 cells and H0007 with 54, together costing 11 %. Width is
  not what buys an answer. Spending it before a mechanism has survived anything
  is how one guess ends up owning the multiple-testing denominator for the life
  of the project.
- **Count the mechanisms, not the hypotheses.** Six of the first eight families
  rested on the funding rate. A tree that re-arranges one idea is narrower than
  its hypothesis count suggests, and if that idea is dead the whole tree is. A
  proposal must say what makes its payer *different* from the payer of every
  family already tested.
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
python scripts/briefing.py                      # 한글 브리핑: 돌고 있나, 어디까지, 다음은
python scripts/health.py                        # is it running, producing, stuck?
python scripts/forever.py                       # the 24h supervisor (never exits)
python scripts/forever.py --dry-run             # what it would do right now
python scripts/scout.py                         # web + 2nd vendor -> SCOUT.jsonl
python scripts/scout.py --list                  # the mechanisms it collected
python scripts/schedule.py                      # do the local tasks point HERE?
python scripts/schedule.py --repair             # after the checkout moves
python scripts/schedule.py --install            # register all three tasks
python -m orc.runstate                          # the durable loop verdict
python -m orc.runstate --next                   # the most useful thing to do now
python -m orc.runstate --due                    # may a reasoning pass run now?
python scripts/status.py                        # where the research stands
python scripts/robustness.py                    # the gate: cost, walk, regime, execution
python scripts/execution_realism.py H0002 BTCUSDT   # one cell on minute bars
python scripts/notify.py                        # exit 0 when there is news
python scripts/deploy_panel.py                  # build the cloud bundle
python -m pytest tests -q                       # must be green before anything
```

## 9. The loop runs continuously, and only registration is rationed

`scripts/forever.py` is the supervisor. Every tick it asks
`runstate.next_action()` for the most useful thing to do, and the answer is
only sometimes a new hypothesis. The rest of the time it is work that costs
**zero ledger rows** and is still research:

| action | what it does | why it is not idling |
|---|---|---|
| `scout` | asks the web and a second vendor for a **payer**, into `reports/SCOUT.jsonl` | the proposer's tools are Read/Glob/Grep/Write, so left alone it can only re-arrange this registry — which is why six of the first eight families rested on the funding rate, and why H0009 was killed as a re-skin of closed H0007 |
| `kernel_review` | adversarial read of the evaluators | six silent defects in one day, one of them putting sealed funding data into the development window. A defect here voids **every** result |
| `robustness` | cost stress, walk forward, regime split over recorded cells | reads the ledger, never adds to it |
| `execution_realism` | one Track B cell re-run on minute bars | where "adverse first" and "one fill" get tested |
| `survivorship` | enlarges the delisted sample | KT-3 is inconclusive and blocks every alt-basket hypothesis until it is not |

**Proposing is free. Registering is not.** A killed proposal is a file in
`configs/killed/` and zero rows; a registration hashes a claim and a grid and
raises the multiple-testing bar for the life of the project. So:

- `MAX_REGISTRATIONS_PER_DAY = 4` is the rolling-24h ceiling, and
  `reasoning_due()` refuses past it before it looks at anything else.
- A pass may run again as soon as the evidence changes, **or** after a pass
  that registered nothing — the adversary's reasons are what the next proposal
  does not otherwise have. A 45-minute floor stops that becoming a loop.
- The queue must be empty. A registered question already costs N, and leaving
  it unanswered is the one kind of idling that has already been paid for.

`reports/ACTIVITY.jsonl` is one line per thing the supervisor did. "It never
rests" is a claim, and a gap in that file is what makes it false.

## 9b. What a reasoning cycle does

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

## 10. A claim is checked before it is written down

Six defects entered this project in one session and every one of them was the
same habit: saying a thing was done without checking it.

| claimed | actually |
|---|---|
| a provider was "verified" by a one-line probe | its real 2 KB prompt arrived empty, exit 0 |
| "a split vote is raised as news" | nothing read `CLOSE_VOTES.json` |
| "tm_q05 is still evaluated against its kill condition" | it had fallen out of the surface entirely |
| a concurrent-write risk, named out loud | never guarded; a run lost 39 minutes and 112 trials |
| an IRR fixed to use realised deposits | the first version used a bar COUNT as elapsed time |
| `git add -A` | committed 193 lines written by a tool, unread |

So:

- **A claim in a commit message, a docstring or a report must be backed by
  something in the same commit that would fail if it were false** — a test, a
  measurement printed into the message, or a re-run against the ledger. "It now
  does X" with nothing exercising X is the defect, not the documentation of one.
- **Verify with the payload the real caller sends.** A check that passes on a
  smaller, simpler input than production verifies nothing and reports success.
- **A risk you can articulate goes into the findings ledger, not into a
  sentence.** Prose in a conversation is not a record and does not survive the
  session that produced it.
- **Never stage by wildcard.** Name the paths. `scripts/precommit.py` enforces
  what it can: the suite must be green, the ledger may not shrink, no conflict
  markers, and a new file outside the expected tree has to be deliberate.
  Install it with `python scripts/precommit.py --install`.

## 11. Style

Match the existing code: numpy-first, no backtesting framework, no ML stack,
no GPU. Comments explain *why* a rule exists, not what a line does. Every
threshold is a constant at the top of its module with a comment saying it was
frozen before results were seen.
