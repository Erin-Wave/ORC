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

# Findings and reports quote code and prose that a cp949 console cannot encode.
# A print that raises takes the whole run down over a dash, which is how the
# first full panel build died at symbol 807 of 810.
try:
    sys.stdout.reconfigure(errors="replace")
except (AttributeError, OSError):                                  # pragma: no cover
    pass
sys.path.insert(0, str(Path(__file__).resolve().parent))

from orc import config, llm                                       # noqa: E402

# Exactly the directories the ledger's code hash covers, plus the modules that
# decide what a trial is and what counts as a finding. If a file can change a
# number anyone will read, it belongs in this list -- which is why surface.py
# and spec.py are here even though the code hash does not cover them: PBO and
# the shape verdict decide whether a family lives, and the pre-registration
# hash decides whether a grid was edited after its results were seen. Neither
# is written to a trial row and both are read as if they were.
REVIEWED = ("orc/eval", "orc/kernel", "orc/facts/panel.py",
            "orc/ledger/trials.py", "orc/orchestrator/runner.py",
            "orc/orchestrator/verdict.py", "orc/orchestrator/surface.py",
            "orc/orchestrator/spec.py", "orc/holdout.py")


# Files per call.  The whole set in one prompt is one review of seventeen files,
# which is a skim: the reviewer has to hold every one of them at once and the
# call times out before it finishes trying.  Four is small enough that each file
# is actually read and that one batch failing costs four files rather than all
# of them.  Frozen before any review ran against the widened set.
REVIEW_BATCH = 4


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
    print(f"reviewing {len(paths)} files in batches of {REVIEW_BATCH}")

    findings: list[dict] = []
    reviewed: list[str] = []
    unreviewed: list[str] = []
    confidences: list[str] = []
    for i in range(0, len(paths), REVIEW_BATCH):
        batch = paths[i:i + REVIEW_BATCH]
        names = [str(q.relative_to(config.ORC_ROOT)).replace(chr(92), '/') for q in batch]
        try:
            r = llm.ask_json(llm.load_prompt("kernel_review",
                                             files=chr(10).join(names)),
                             cwd=config.ORC_ROOT)
        except llm.LLMUnavailable as exc:
            # A batch nobody could read is not a batch with no findings. Record
            # it as unreviewed so an empty result cannot be mistaken for a clean
            # one, which is the same mistake the gate already refuses to make.
            print(f"  batch {i // REVIEW_BATCH + 1} UNAVAILABLE: {exc}")
            unreviewed.extend(names)
            continue
        got = r.get("findings", [])
        findings.extend(got)
        reviewed.extend(r.get("reviewed", names))
        confidences.append(str(r.get("confidence", "unknown")))
        print(f"  batch {i // REVIEW_BATCH + 1}: {len(got)} finding(s) over "
              f"{len(names)} file(s)")

    if not reviewed:
        print("review unavailable: no batch could be read")
        return 2

    # The weakest batch sets the confidence of the whole review.
    order = {"low": 0, "medium": 1, "high": 2}
    r = {"confidence": min(confidences, key=lambda c: order.get(c, 0)) if confidences
         else "unknown",
         "reviewed": reviewed, "unreviewed": unreviewed, "findings": findings}

    stamp = datetime.now(timezone.utc).isoformat()
    lines = [f"# Kernel review\n", f"Written {stamp}. Confidence "
             f"{r['confidence']}. {len(findings)} finding(s) over "
             f"{len(reviewed)} file(s) read."]
    if unreviewed:
        lines.append(f"{len(unreviewed)} file(s) were NOT read this run and are "
                     f"not covered by the result below: " + ", ".join(unreviewed))
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
    if unreviewed:
        # A partial review must not be filed as a completed one. Non-zero so the
        # scheduler retries and so a green task result means the whole set was
        # actually read.
        print(f"PARTIAL: {len(unreviewed)} file(s) were not read")
        return 3
    return 1 if high else 0


if __name__ == "__main__":
    raise SystemExit(main())
