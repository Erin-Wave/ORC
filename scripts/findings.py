"""ORC | The findings ledger: what the reviews found, and what was done about it.

Detection was automated today. Disposition was not, and the gap bit within the
hour: the kernel review returned thirteen findings, five high and six medium; I
fixed the five and moved on; and one of the mediums - plateau_score dividing
one negative by another and calling a collapse a plateau - turned out to be
mislabelling every losing symbol on the board. The post-mortem found it again
from the other end. The report had said so and nobody had written down that it
was being skipped.

Fixing stays manual on purpose. An agent that could patch the evaluators could
also quietly change what a result means, and that is the one thing this project
cannot allow. What is automated here is the memory: every finding gets an
explicit disposition, an unaddressed one stays visible, and skipping becomes a
decision on the record instead of an omission.

A finding is identified by file and text rather than by line number, so a
finding does not reappear as new because the code above it moved.

Usage:
  python scripts/findings.py                 list what is open
  python scripts/findings.py merge           fold a new review into the ledger
  python scripts/findings.py fixed <id> ...  mark as fixed
  python scripts/findings.py wontfix <id> <reason>
  python scripts/findings.py defer <id> <reason>
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orc import config                                            # noqa: E402

LEDGER = config.REPORTS / "FINDINGS.json"

# An open high finding stops the pipeline. A result computed on code known to
# be wrong is worse than no result: it looks like evidence and it is not, and
# it will be quoted long after the review that flagged it is forgotten.
BLOCKING = ("high",)
OPEN_STATES = ("open", "deferred")


def _fid(f: dict) -> str:
    """Identity from file and text, so a finding survives the code moving."""
    return hashlib.sha256(
        f"{f.get('file')}|{f.get('what')}".encode()).hexdigest()[:12]


def load() -> dict:
    if LEDGER.exists():
        return json.loads(LEDGER.read_text(encoding="utf-8"))
    return {"findings": {}}


def save(d: dict) -> None:
    LEDGER.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")


def merge(review_path: Path | None = None) -> tuple[int, int]:
    """Fold a review's findings in. Returns (new, already known)."""
    src = review_path or (config.REPORTS / "KERNEL_REVIEW.json")
    if not src.exists():
        return (0, 0)
    review = json.loads(src.read_text(encoding="utf-8"))
    d = load()
    new = known = 0
    for f in review.get("findings", []):
        k = _fid(f)
        if k in d["findings"]:
            d["findings"][k]["last_seen_utc"] = review.get("utc", "")
            known += 1
            continue
        d["findings"][k] = {
            "id": k, "status": "open", "first_seen_utc": review.get("utc", ""),
            "last_seen_utc": review.get("utc", ""), "disposition": "",
            **{x: f.get(x) for x in ("file", "line", "severity", "what",
                                     "trigger", "why_silent")},
        }
        new += 1
    save(d)
    return (new, known)


def open_findings(severity: tuple[str, ...] | None = None) -> list[dict]:
    return [f for f in load()["findings"].values()
            if f["status"] in OPEN_STATES
            and (severity is None or f.get("severity") in severity)]


def blocking() -> list[dict]:
    """Open findings severe enough that no cycle should run on top of them."""
    return [f for f in open_findings(BLOCKING) if f["status"] == "open"]


def set_status(fid: str, status: str, reason: str = "") -> bool:
    d = load()
    if fid not in d["findings"]:
        return False
    d["findings"][fid].update({
        "status": status, "disposition": reason,
        "decided_utc": datetime.now(timezone.utc).isoformat()})
    save(d)
    return True


def main(argv: list[str]) -> int:
    if argv and argv[0] == "merge":
        n, k = merge()
        print(f"{n} new finding(s), {k} already known")
        argv = []
    elif argv and argv[0] in ("fixed", "wontfix", "defer"):
        state = {"fixed": "fixed", "wontfix": "wontfix", "defer": "deferred"}[argv[0]]
        reason = " ".join(argv[2:])
        if state != "fixed" and not reason:
            print(f"{argv[0]} needs a reason; a skip without one is an omission")
            return 2
        print("updated" if set_status(argv[1], state, reason) else f"no finding {argv[1]}")
        return 0

    d = load()
    rows = sorted(d["findings"].values(),
                  key=lambda f: ({"high": 0, "medium": 1}.get(f.get("severity"), 2),
                                 f.get("file", "")))
    for f in rows:
        mark = {"open": "OPEN  ", "deferred": "DEFER ", "fixed": "fixed ",
                "wontfix": "won't "}.get(f["status"], f["status"])
        print(f"{mark} {f['id']}  {f.get('severity', '?'):6s} "
              f"{f.get('file')}:{f.get('line', '?')}")
        print(f"         {str(f.get('what', ''))[:96]}")
        if f.get("disposition"):
            print(f"         -> {f['disposition'][:96]}")
    n_open = len(open_findings())
    n_block = len(blocking())
    print(f"\n{len(rows)} finding(s), {n_open} open, {n_block} blocking")
    if n_block:
        print("A cycle will refuse to run while a high finding is open. Fix it, or "
              "record why not with  python scripts/findings.py wontfix <id> <reason>")
    return 1 if n_block else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
