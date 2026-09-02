"""ORC | The daily reasoning pass, with judgement spent on doubt.

The evaluation layer is deterministic and costs nothing per run. What is scarce
here is not compute but N: every configuration a registered hypothesis
enumerates enters an append-only ledger, and that count is the denominator of
the multiple-testing correction applied to every result the project will ever
produce. Registering a badly posed hypothesis does not waste a day. It
permanently raises the bar for everything else.

So this spends model calls on the things that reduce what enters the ledger, or
that read what is already in it, and never on producing more of it:

  propose     one pass over the cycle report, proposing rule shapes
  adversary   tries to kill each proposal BEFORE registration -- the only step
              that spends judgement to protect N rather than to consume it
  mechanism   checks with sources whether the named payer actually exists
  surfaces    describes the response surfaces rather than their maxima
  postmortem  when the proposer closes a family, writes down why it broke

Nothing here touches a number. The evaluators stay deterministic, the verdict
thresholds stay pre-registered constants, and a model that could argue a cell
through the gate would make the whole apparatus theatre.

Every step degrades to a skip. A missing CLI, an expired token or a timeout
leaves the pipeline reporting what it could not do, because a judgement step
that silently vanishes is worse than one that never ran.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from orc import config, llm                                       # noqa: E402

PROPOSED = config.CONFIGS / "proposed"
KILLED = config.CONFIGS / "killed"
CLOSED = config.CONFIGS / "closed"

# The proposer writes files; it must not commit or evaluate. Everything it
# produces passes the adversary before it can reach the queue.
PROPOSER_TOOLS = ("Read", "Glob", "Grep", "Write")
# The researcher is the only step allowed out to the network, and only to read.
RESEARCH_TOOLS = ("WebSearch", "WebFetch", "Read")


def _log(msg: str) -> None:
    print(f"  {msg}", flush=True)


def propose() -> list[Path]:
    """One pass over the cycle report. Returns the files it wrote."""
    PROPOSED.mkdir(parents=True, exist_ok=True)
    for stale in PROPOSED.glob("*.json"):
        stale.unlink()
    prompt = (config.ORC_ROOT / "scripts" / "reasoning_prompt.txt").read_text(encoding="utf-8")
    llm.ask(prompt, tools=PROPOSER_TOOLS, cwd=config.ORC_ROOT)
    return sorted(PROPOSED.glob("*.json"))


def expandable(path: Path) -> str | None:
    """Can the evaluator actually express this? Returns the failure, or None.

    The adversary judges whether a hypothesis is well posed as research. That
    is a different question from whether the machine can run it, and it is not
    a question worth asking a model: expanding the grid answers it exactly.
    The first three proposals were all good research and none of them could be
    expanded -- they named parameters the config types do not have -- and
    without this they would have reached the worker and been recorded as
    failures with the day already spent.
    """
    from orc.orchestrator.spec import Hypothesis

    try:
        h = Hypothesis(**json.loads(path.read_text(encoding="utf-8")))
        h.register()
        cfgs = h.expand()
    except Exception as exc:                                       # noqa: BLE001
        return f"{type(exc).__name__}: {exc}"
    if not cfgs:
        return "the grid expands to nothing"
    rule = h.fixed.get("rule") or (cfgs[0].rule if hasattr(cfgs[0], "rule") else None)
    if rule is not None:
        from orc.eval.signal_rules import RULES
        if rule not in RULES:
            return f"unknown signal rule {rule!r}; known rules are {sorted(RULES)}"
    return None


def review(path: Path) -> dict:
    """The adversary. A proposal reaches the queue only by surviving this."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw.pop("registered_utc", None)
    raw.pop("prereg_hash", None)
    return llm.ask_json(
        llm.load_prompt("adversary", proposal=json.dumps(raw, indent=2, ensure_ascii=False)),
        cwd=config.ORC_ROOT)


def research(claim: str) -> dict:
    """Does the named payer actually exist, according to sources?"""
    return llm.ask_json(llm.load_prompt("mechanism", claim=claim),
                        tools=RESEARCH_TOOLS, cwd=config.ORC_ROOT)


def read_surfaces() -> str:
    """Describe the response surfaces instead of their maxima."""
    out = []
    for p in sorted(config.REPORTS.glob("*_SURFACE.json")):
        rep = json.loads(p.read_text(encoding="utf-8"))
        # The grids themselves, not the summary rows: the point is the shape.
        trimmed = {
            "hypothesis_id": rep["hypothesis_id"], "family": rep["family"],
            "metric": rep["metric"],
            "axes": next(iter(rep["surfaces"].values()), {}).get("axes"),
            "axis_values": next(iter(rep["surfaces"].values()), {}).get("axis_values"),
            "grids": {s: v["grid"] for s, v in rep["surfaces"].items()},
            "best": {s: v["best_config"] for s, v in rep["surfaces"].items()},
        }
        text = llm.ask(llm.load_prompt("surface_read",
                                       surface=json.dumps(trimmed, ensure_ascii=False)),
                       cwd=config.ORC_ROOT)
        out.append(f"## {rep['hypothesis_id']} — {rep['family']}\n\n{text}\n")
    return "\n".join(out)


def postmortem(family_file: Path) -> str:
    """Write the map entry for a family the proposer decided to close."""
    closed = json.loads(family_file.read_text(encoding="utf-8"))
    hid = closed.get("hypothesis_id", "")
    surface = config.REPORTS / f"{hid}_SURFACE.json"
    gate = config.REPORTS / "ROBUSTNESS.json"
    return llm.ask(llm.load_prompt(
        "postmortem",
        family_report=surface.read_text(encoding="utf-8") if surface.exists() else json.dumps(closed),
        gate_report=gate.read_text(encoding="utf-8") if gate.exists() else "no gate results"),
        cwd=config.ORC_ROOT)


def main() -> int:
    config.ensure_dirs()
    for d in (PROPOSED, KILLED, CLOSED):
        d.mkdir(parents=True, exist_ok=True)
    report: dict = {"utc": datetime.now(timezone.utc).isoformat(), "steps": {}}

    # A cycle run on code known to be wrong produces numbers that look like
    # evidence and are not, and they get quoted long after the review that
    # flagged them is forgotten. Refuse, and say exactly what is blocking.
    import findings as ledger
    blocked = ledger.blocking()
    if blocked:
        print("BLOCKED: an unaddressed high-severity finding stands")
        for f in blocked:
            print(f"  {f['id']}  {f['file']}:{f.get('line')}  {str(f['what'])[:90]}")
        print("Fix it, or record the decision:")
        print("  python scripts/findings.py wontfix <id> <reason>")
        report["steps"]["blocked"] = [f["id"] for f in blocked]
        (config.REPORTS / "REASONING_LOG.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        return 1

    print("propose")
    try:
        proposals = propose()
        _log(f"{len(proposals)} proposal(s)")
        report["steps"]["propose"] = [p.name for p in proposals]
    except llm.LLMUnavailable as exc:
        _log(f"SKIPPED: {exc}")
        report["steps"]["propose"] = f"skipped: {exc}"
        proposals = []

    print("adversary")
    registered = []
    for p in proposals:
        why = expandable(p)
        if why:
            (KILLED / p.name).write_text(
                json.dumps({"proposal": json.loads(p.read_text(encoding="utf-8")),
                            "verdict": {"verdict": "KILL", "reason": why,
                                        "killed_by": "expandability"}},
                           indent=2, ensure_ascii=False), encoding="utf-8")
            p.unlink()
            _log(f"{p.name} KILLED    not expressible -- {why[:100]}")
            report["steps"].setdefault("unexpandable", []).append(
                {"file": p.name, "reason": why})
            continue
        try:
            v = review(p)
        except llm.LLMUnavailable as exc:
            # Unreviewed is not approved. A proposal that could not be judged
            # waits rather than entering the ledger on the strength of silence.
            _log(f"{p.name} HELD: review unavailable ({exc})")
            report["steps"].setdefault("held", []).append(p.name)
            continue
        if v.get("verdict") == "REGISTER":
            shutil.move(str(p), str(config.QUEUE / p.name))
            registered.append(p.name)
            _log(f"{p.name} REGISTER  ({v.get('configurations', '?')} configs)")
        else:
            (KILLED / p.name).write_text(
                json.dumps({"proposal": json.loads(p.read_text(encoding="utf-8")),
                            "verdict": v}, indent=2, ensure_ascii=False), encoding="utf-8")
            p.unlink()
            _log(f"{p.name} KILLED    {v.get('reason', '')[:120]}")
        report["steps"].setdefault("adversary", []).append({"file": p.name, **v})

    print("mechanism")
    for name in registered:
        h = json.loads((config.QUEUE / name).read_text(encoding="utf-8"))
        try:
            r = research(h.get("claim", ""))
            (config.REPORTS / f"MECHANISM_{h['hypothesis_id']}.json").write_text(
                json.dumps(r, indent=2, ensure_ascii=False), encoding="utf-8")
            _log(f"{h['hypothesis_id']} payer_exists={r.get('payer_exists')} "
                 f"({r.get('confidence')}) {str(r.get('who'))[:60]}")
            report["steps"].setdefault("mechanism", []).append(
                {"hypothesis_id": h["hypothesis_id"], **r})
        except llm.LLMUnavailable as exc:
            _log(f"{h['hypothesis_id']} SKIPPED: {exc}")

    print("surfaces")
    try:
        text = read_surfaces()
        (config.REPORTS / "SURFACE_READING.md").write_text(
            f"# Response surfaces\n\nWritten {report['utc']}\n\n{text}", encoding="utf-8")
        _log(f"{len(text)} chars written")
        report["steps"]["surfaces"] = "written"
    except llm.LLMUnavailable as exc:
        _log(f"SKIPPED: {exc}")
        report["steps"]["surfaces"] = f"skipped: {exc}"

    print("postmortem")
    for f in sorted(CLOSED.glob("*.json")):
        try:
            text = postmortem(f)
            out = config.REPORTS / f"POSTMORTEM_{f.stem}.md"
            out.write_text(text, encoding="utf-8")
            f.unlink()
            _log(f"{f.stem} written to {out.name}")
            report["steps"].setdefault("postmortem", []).append(f.stem)
        except llm.LLMUnavailable as exc:
            _log(f"{f.stem} SKIPPED: {exc}")

    (config.REPORTS / "REASONING_LOG.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    subprocess.run(["git", "add", "-A", "configs", "reports"],
                   cwd=config.ORC_ROOT, check=False)
    r = subprocess.run(["git", "diff", "--cached", "--quiet"],
                       cwd=config.ORC_ROOT, check=False)
    if r.returncode != 0:
        subprocess.run(["git", "commit", "-q", "-m",
                        f"reasoning: {len(registered)} registered, "
                        f"{len(list(KILLED.glob('*.json')))} killed to date"],
                       cwd=config.ORC_ROOT, check=False)
        subprocess.run(["git", "pull", "--rebase", "--autostash", "-q"],
                       cwd=config.ORC_ROOT, check=False)
        subprocess.run(["git", "push", "-q"], cwd=config.ORC_ROOT, check=False)
        print("committed and pushed")
    else:
        print("nothing to commit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
