"""ORC | Decide whether anything happened worth interrupting someone for.

Three things are worth a notification, and they are the three ways this system
goes quiet without going wrong-looking:

  a survivor    A cell cleared every check. This is the one the whole apparatus
                exists to produce, and it must not scroll past unseen.
  a rejection   A queued hypothesis failed its schema and was moved aside. The
                cycle carries on reporting success while the reasoning layer's
                output is silently going in the bin.
  a stall       No cycle has finished recently. The worker runs every six hours
                and the reasoning layer daily, so silence past a day means one
                of them stopped and nothing else will say so.

Prints one line per item and exits 0 when there is news, 1 when there is not,
so a scheduler can branch on the exit code without parsing anything.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orc import config                                            # noqa: E402
from orc.orchestrator.verdict import survivors                    # noqa: E402

# The worker fires every six hours; a day of silence is past any schedule
# slipping and means something stopped.
STALL_AFTER = timedelta(hours=30)


def _load(name: str):
    p = config.REPORTS / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def collect() -> list[str]:
    news: list[str] = []

    summary = _load("CYCLE_SUMMARY.json")
    if summary is None:
        return ["ORC: no cycle has ever finished"]

    finished = datetime.fromisoformat(summary["finished_utc"])
    if finished.tzinfo is None:
        finished = finished.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - finished
    if age > STALL_AFTER:
        news.append(f"ORC stalled: last cycle was {age.days}d {age.seconds // 3600}h ago")

    for res in summary.get("results", []):
        rep = _load(f"{res['hypothesis_id']}_SURFACE.json")
        if rep is None:
            continue
        for sym, s in survivors(rep):
            news.append(
                f"{rep['hypothesis_id']} {rep['family']}: {sym} clears every check "
                f"at {rep['metric']} {s['best_value']:+.4f}  {s['best_config']}")

    rejected = sorted((config.QUEUE / "rejected").glob("*.json")) \
        if (config.QUEUE / "rejected").exists() else []
    for r in rejected:
        news.append(f"ORC rejected a queued hypothesis: {r.name}")

    return news


def main() -> int:
    news = collect()
    for line in news:
        print(line)
    return 0 if news else 1


if __name__ == "__main__":
    raise SystemExit(main())
