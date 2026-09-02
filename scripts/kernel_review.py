"""ORC | Adversarial review of the code every result depends on.

Six defects were found in the evaluation kernel on 2026-09-02. All six were
silent -- none crashed, each returned a plausible number -- and all six were
found by accident, while doing something else. One of them was putting sealed
funding data into the development window, which is the single guarantee this
project is built around.

Accident is not a review process. This is.

It runs weekly rather than daily because the kernel changes rarely and because
a review that fires constantly gets skimmed. Findings go to
reports/KERNEL_REVIEW.md and, when any are high severity, into the notifier so
they are not left sitting in a file nobody opens.

The reviewer reads and reports. It does not edit: a model that could patch the
evaluators could also quietly change what a result means.

Usage:  python scripts/kernel_review.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from orc import config, llm                                       # noqa: E402

# Exactly the directories the ledger's code hash covers, plus the two modules
# that decide what a trial is and what counts as a finding. If a file can
# change a recorded number, it belongs in this list.
REVIEWED = ("orc/eval", "orc/kernel", "orc/facts/panel.py",
            "orc/ledger/trials.py", "orc/orchestrator/runner.py",
            "orc/orchestrator/verdict.py", "orc/holdout.py")


def files_to_review() -> list[Path]:
    out: list[Path] = []
    for entry in REVIEWED:
        p = config.ORC_ROOT / entry
        if p.is_dir():
            out.extend(sorted(p.rglob("*.py")))
        elif p.exists():
            out.append(p)
    return out


def main() -> int:
    paths = files_to_review()
    listing = "\n".join(str(p.relative_to(config.ORC_ROOT)).replace("\\", "/")
                        for p in paths)
    print(f"reviewing {len(paths)} files")

    try:
        r = llm.ask_json(llm.load_prompt("kernel_review", files=listing),
                         cwd=config.ORC_ROOT)
    except llm.LLMUnavailable as exc:
        print(f"review unavailable: {exc}")
        return 2

    findings = r.get("findings", [])
    stamp = datetime.now(timezone.utc).isoformat()
    lines = [f"# Kernel review\n", f"Written {stamp}. Confidence "
             f"{r.get('confidence', 'unknown')}. {len(findings)} finding(s) "
             f"over {len(r.get('reviewed', []))} files read.\n"]
    if not findings:
        lines.append("No findings. An empty review is a result, not a formality: "
                     "it says the reviewer read the code and could not construct "
                     "an input that breaks it.\n")
    for f in sorted(findings, key=lambda x: {"high": 0, "medium": 1}.get(x.get("severity"), 2)):
        lines += [
            f"\n## {f.get('severity', '?').upper()} — {f.get('file')}"
            f":{f.get('line', '?')}\n",
            f"**{f.get('what', '')}**\n",
            f"- Trigger: {f.get('trigger', '')}",
            f"- Why it is silent: {f.get('why_silent', '')}\n",
        ]
    (config.REPORTS / "KERNEL_REVIEW.md").write_text("\n".join(lines), encoding="utf-8")
    (config.REPORTS / "KERNEL_REVIEW.json").write_text(
        json.dumps({"utc": stamp, **r}, indent=2, ensure_ascii=False), encoding="utf-8")

    # Into the ledger, so a finding survives the next review overwriting this
    # file and so skipping one becomes a decision on the record.
    import findings as ledger
    new_n, known_n = ledger.merge()
    print(f"{new_n} new to the findings ledger, {known_n} already known")

    high = [f for f in findings if f.get("severity") == "high"]
    for f in findings:
        print(f"  {f.get('severity', '?'):6s} {f.get('file')}:{f.get('line', '?')}  "
              f"{str(f.get('what', ''))[:90]}")
    print(f"{len(findings)} finding(s), {len(high)} high")
    return 1 if high else 0


if __name__ == "__main__":
    raise SystemExit(main())
