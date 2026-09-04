"""ORC | The condition under which this research stops, and how far it is away.

The constitution says the deliverable is a map of where rules break and that a
FAIL is publishable.  That is still true and nothing here changes it.  What was
missing was the other end: a written answer to "when is this finished", which
until now existed only as an intention and therefore could be met, or moved,
without either being visible.

The owner set it on 2026-09-04.  A rule stops the project when it reaches a
**CAGR of 100 % at a maximum drawdown of 25 % or less** and has survived
verification several times over -- and "several times over" is the list in
`CHECKS` below rather than a feeling, because the whole reason for writing a
stop condition down is that the day a number finally looks good is the worst
possible day to decide what counts as good enough.

Every check here is one this project already runs on every candidate.  Nothing
in this module lowers a bar, adds a metric, or changes what is measured; it
reads what the ledger and the reports already say and answers one question with
it.  The bar it applies is `config.TARGET_CAGR` and `config.TARGET_MAX_DRAWDOWN`,
which were frozen with the measurement showing nothing in 6,848 trials had come
near them -- see the comment beside those constants.

    python -m orc.target            where the project stands against the finish
    python -m orc.target --json     the same, for a script

`status.py` will not scan the ledger for a maximum, and it is right not to:
hunting the best row across every trial ever recorded is the selection bias
this protocol exists to contain.  This module does read the ledger, and the
difference is what the number is FOR.  A search bias is choosing which result
to believe after seeing them all.  This applies one bar, fixed in advance, to
every row equally, and its answer is a yes or a no rather than a winner -- the
distance figures it prints exist so that "nothing is close" is checkable and
are not admissible in any argument that a cell is a finding.  Nothing here
feeds a verdict, a report or a ranking: it decides only whether there is
something left to ask.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from orc import config
from orc.facts.panel import DEVELOPMENT
from orc.ledger.trials import Ledger

# A single equity curve over one history is ONE experiment however many bars it
# contains (constitution section 4), so a target met on one symbol is a claim
# about that symbol.  Three is the smallest count at which the claim is about
# the rule instead, and it is deliberately not larger: nine symbols would make
# the stop condition unreachable for an honest rule that only works where the
# forced flow is, which would be a threshold quietly chosen to never fire.
#
# Frozen 2026-09-04, on a ledger in which no cell met the numeric bar on even
# ONE symbol -- so it cannot have been picked to admit a result that existed.
MIN_SYMBOLS = 3

# The named ways this candidate could still be wrong.  Each is a check the
# project already implements, and each fails for a different reason, which is
# what makes passing all of them "verified several times" rather than one
# measurement repeated.
CHECKS = {
    "symbols": "같은 파라미터가 여러 심볼에서 목표를 만족하는가",
    "not_disqualified": "표면 판정(스파이크/독립경로/PBO/서치테스트)을 통과하는가",
    "robustness": "비용 스트레스·워크포워드·레짐 분할을 견디는가",
    "execution": "1분봉 체결로 다시 돌려도 답이 유지되는가",
    "holdout": "봉인된 홀드아웃에서 확인되었는가",
}

# States, worst to best.  The loop reads this string and nothing else.
NO_CANDIDATE = "NO_CANDIDATE"
CANDIDATE_UNVERIFIED = "CANDIDATE_UNVERIFIED"
VERIFIED_ON_DEVELOPMENT = "VERIFIED_ON_DEVELOPMENT"
COMPLETE = "COMPLETE"


def meets(metrics: dict) -> bool:
    """Does one recorded cell reach the target?

    Both halves, never one.  A CAGR without its drawdown is the number this
    project exists not to be fooled by: H0006's best SOLUSDT cell compounds at
    93 % a year and gives back two thirds of the account on the way, and a
    reader shown only the first figure would call that a finding.
    """
    try:
        cagr = float(metrics["cagr"])
        dd = float(metrics["max_drawdown"])
    except (KeyError, TypeError, ValueError):
        return False
    if cagr != cagr or dd != dd:                       # NaN is not a measurement
        return False
    return cagr >= config.TARGET_CAGR and dd <= config.TARGET_MAX_DRAWDOWN


def _signature(cfg: dict) -> str:
    """The cell's identity with the symbol removed.

    Two symbols meeting the target under DIFFERENT parameters are two results,
    not one result confirmed twice, and counting them together is how a search
    over nine symbols manufactures agreement it never found.
    """
    return json.dumps({k: v for k, v in sorted(cfg.items()) if k != "symbol"},
                      sort_keys=True, default=str)


def _rows(ledger: Ledger) -> list[dict]:
    """Every development-window Track B row that carries both target metrics.

    Sealed rows are excluded here rather than filtered by the caller.  A final
    test writes its rows into the same table, and a stop condition that could
    be satisfied by the holdout measurement it is supposed to precede would be
    circular in the one place it must not be.
    """
    sql = ("SELECT hypothesis_id, family, symbol, config_json, metrics_json"
           " FROM trials WHERE evaluator='signal' AND holdout_state=?"
           " AND json_extract(metrics_json,'$.cagr') IS NOT NULL")
    out = []
    for hid, family, symbol, cfg_json, met_json in ledger.conn.execute(sql, (DEVELOPMENT,)):
        out.append({"hypothesis_id": hid, "family": family, "symbol": symbol,
                    "config": json.loads(cfg_json), "metrics": json.loads(met_json)})
    return out


def best_so_far(rows: list[dict]) -> dict:
    """The closest anything has come, on each half of the target separately.

    Two numbers because the target is two conditions and a project can be far
    from it in two unrelated ways.  Reporting only the best CAGR would have
    said this project was 93 % of the way there on the day its best cell also
    lost two thirds of the account.
    """
    best_cagr = {"cagr": float("-inf")}
    best_within_dd = {"cagr": float("-inf")}
    for r in rows:
        m = r["metrics"]
        try:
            cagr, dd = float(m["cagr"]), float(m["max_drawdown"])
        except (KeyError, TypeError, ValueError):
            continue
        if cagr != cagr or dd != dd:
            continue
        cell = {"cagr": cagr, "max_drawdown": dd, "calmar": m.get("calmar"),
                "hypothesis_id": r["hypothesis_id"], "symbol": r["symbol"]}
        if cagr > best_cagr["cagr"]:
            best_cagr = cell
        if dd <= config.TARGET_MAX_DRAWDOWN and cagr > best_within_dd["cagr"]:
            best_within_dd = cell
    return {
        "best_cagr": None if best_cagr["cagr"] == float("-inf") else best_cagr,
        "best_cagr_within_drawdown":
            None if best_within_dd["cagr"] == float("-inf") else best_within_dd,
        "rows_considered": len(rows),
    }


def _report(name: str) -> dict:
    try:
        return json.loads((config.REPORTS / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _passed_in(report_name: str, hid: str, symbols: set[str]) -> str | None:
    """PASS only if every symbol carrying the candidate was checked and passed.

    None means unmeasured, which is not a pass.  That distinction is the same
    one `verdict.disqualifiers` makes about an uncomputed PBO, and for the same
    reason: a check that did not run is the easiest possible way to clear a
    check.
    """
    results = _report(report_name).get("results") or []
    seen = {r.get("symbol"): bool(r.get("passed"))
            for r in results if r.get("hypothesis_id") == hid}
    missing = symbols - set(seen)
    if missing:
        return None
    return "pass" if all(seen[s] for s in symbols) else "fail"


def _not_disqualified(hid: str, symbols: set[str]) -> str | None:
    """The surface verdict, read through the same code the status screen uses."""
    from orc.orchestrator.verdict import survivors

    report = _report(f"{hid}_SURFACE.json")
    if not report:
        return None
    cleared = {sym for sym, _ in survivors(report)}
    if not (set(report.get("surfaces") or {}) >= symbols):
        return None
    return "pass" if symbols <= cleared else "fail"


def _holdout_confirms(signature: str) -> str | None:
    """Has a final test been opened on this cell, and did it hold?

    The opening log is the only record of a sealed measurement, and it stores
    the candidate it was opened for.  A cell that has never been through that
    door is unmeasured; there is no way to be "probably confirmed".
    """
    from orc import holdout

    for rec in holdout._openings():
        cand = rec.get("candidate") or {}
        cfg = cand.get("config") or cand
        if isinstance(cfg, dict) and _signature(cfg) == signature:
            result = cand.get("result") or rec.get("result") or {}
            if isinstance(result, dict) and "cagr" in result:
                return "pass" if meets(result) else "fail"
            return None
    return None


def candidates(ledger: Ledger | None = None) -> list[dict]:
    """Every distinct parameter set that meets the target, and its verification.

    Grouped by parameters rather than listed per row, because the same cell is
    recorded once per symbol and once more whenever the code hash moves, and a
    list of rows would report one candidate as five.
    """
    own = ledger is None
    ledger = ledger or Ledger()
    try:
        rows = _rows(ledger)
    finally:
        if own:
            ledger.close()

    groups: dict[tuple[str, str], dict] = {}
    for r in rows:
        if not meets(r["metrics"]):
            continue
        key = (r["hypothesis_id"], _signature(r["config"]))
        g = groups.setdefault(key, {
            "hypothesis_id": r["hypothesis_id"], "family": r["family"],
            "config": {k: v for k, v in r["config"].items() if k != "symbol"},
            "signature": key[1], "symbols": {},
        })
        m = r["metrics"]
        g["symbols"][r["symbol"]] = {"cagr": float(m["cagr"]),
                                     "max_drawdown": float(m["max_drawdown"]),
                                     "calmar": m.get("calmar")}

    out = []
    for g in groups.values():
        syms = set(g["symbols"])
        checks = {
            "symbols": "pass" if len(syms) >= MIN_SYMBOLS else "fail",
            "not_disqualified": _not_disqualified(g["hypothesis_id"], syms),
            "robustness": _passed_in("ROBUSTNESS.json", g["hypothesis_id"], syms),
            "execution": _passed_in("EXECUTION_REALISM.json", g["hypothesis_id"], syms),
            "holdout": _holdout_confirms(g["signature"]),
        }
        g["checks"] = checks
        g["failed"] = sorted(k for k, v in checks.items() if v == "fail")
        g["unmeasured"] = sorted(k for k, v in checks.items() if v is None)
        g["verified"] = not g["failed"] and not g["unmeasured"]
        out.append(g)
    out.sort(key=lambda g: (-len(g["symbols"]),
                            -max(s["cagr"] for s in g["symbols"].values())))
    return out


def state(ledger: Ledger | None = None) -> dict:
    """What the loop reads.  One state string, and the evidence behind it."""
    own = ledger is None
    ledger = ledger or Ledger()
    try:
        rows = _rows(ledger)
        cands = candidates(ledger)
    finally:
        if own:
            ledger.close()

    target = {"cagr": config.TARGET_CAGR, "max_drawdown": config.TARGET_MAX_DRAWDOWN}
    if not cands:
        return {"state": NO_CANDIDATE, "target": target, "candidates": [],
                **best_so_far(rows),
                "headline": (
                    f"목표(CAGR {config.TARGET_CAGR:.0%} / MDD "
                    f"{config.TARGET_MAX_DRAWDOWN:.0%})를 만족하는 셀 없음, "
                    f"트랙B {len(rows)}행 기준")}

    done = [c for c in cands if c["verified"]]
    if done:
        st, head = COMPLETE, (
            f"연구 종료 조건 충족: {len(done)}개 후보가 모든 검증을 통과했습니다 "
            f"({', '.join(sorted(c['hypothesis_id'] for c in done))})")
    else:
        waiting = [c for c in cands if not c["failed"] and c["unmeasured"] == ["holdout"]]
        if waiting:
            st, head = VERIFIED_ON_DEVELOPMENT, (
                f"{len(waiting)}개 후보가 개발 구간 검증을 모두 통과했습니다. "
                "남은 것은 봉인 홀드아웃 최종 테스트뿐입니다")
        else:
            top = cands[0]
            st, head = CANDIDATE_UNVERIFIED, (
                f"목표 수치를 만족하는 후보 {len(cands)}개 — 미검증: "
                f"{', '.join(top['unmeasured']) or '없음'}; 실패: "
                f"{', '.join(top['failed']) or '없음'}")
    return {"state": st, "target": target, "candidates": cands,
            **best_so_far(rows), "headline": head}


def is_complete(ledger: Ledger | None = None) -> bool:
    return state(ledger)["state"] == COMPLETE


def write_report(ledger: Ledger | None = None) -> Path:
    """Publish the answer, so the readers stay report-only.

    `status.py`, `briefing.py` and `notify.py` all read `reports/` and nothing
    else, deliberately.  The cycle writes this file so they keep that property
    while still being able to say where the finish line is.
    """
    out = config.REPORTS / "TARGET.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(state(ledger), ensure_ascii=False, indent=2,
                              default=str), encoding="utf-8")
    return out


def main(argv: list[str]) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, OSError):                              # pragma: no cover
        pass
    s = state()
    if "--json" in argv:
        print(json.dumps(s, ensure_ascii=False, indent=2, default=str))
        return 0
    print(f"목표  CAGR >= {config.TARGET_CAGR:.0%},  MDD <= "
          f"{config.TARGET_MAX_DRAWDOWN:.0%}   (Calmar >= "
          f"{config.TARGET_CAGR / config.TARGET_MAX_DRAWDOWN:.1f})")
    print(f"상태  {s['state']}  —  {s['headline']}")
    b = s.get("best_cagr")
    if b:
        print(f"  최고 CAGR      {b['cagr']:+.1%}  (MDD {b['max_drawdown']:.1%}, "
              f"{b['hypothesis_id']} {b['symbol']})")
    b = s.get("best_cagr_within_drawdown")
    if b:
        print(f"  MDD 25% 이내   {b['cagr']:+.1%}  (MDD {b['max_drawdown']:.1%}, "
              f"{b['hypothesis_id']} {b['symbol']})")
    for c in s["candidates"]:
        print(f"  {c['hypothesis_id']} {c['family']}  "
              f"{len(c['symbols'])} symbols: {', '.join(sorted(c['symbols']))}")
        for name, why in CHECKS.items():
            mark = {"pass": "OK  ", "fail": "FAIL", None: "?   "}[c["checks"][name]]
            print(f"    {mark} {name:17s} {why}")
    return 0


if __name__ == "__main__":                                         # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
