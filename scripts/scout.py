"""ORC | Where the next mechanism comes from, when it is not in this repository.

Six of the first eight families rested on the funding rate, and section 6 of the
constitution says why that is a narrower tree than its hypothesis count
suggests. On 2026-09-03 the reasoning layer showed exactly how it happens: it
proposed H0009, and both adversaries killed it as a finer grid over closed
H0007 -- the same liquidated-long payer, the same dip-gated deployment code
path, a different threshold. That was not a bad model. It was a proposer whose
tools are Read, Glob, Grep and Write, asked to name a payer it has never been
given a way to hear about. All it can do is re-arrange the registry.

So this step goes outside. It asks every available provider - Claude, which can
search the web, and Codex, which is a genuinely independent model and therefore
a second opinion rather than the same one twice - for PAYERS: someone with a
structural reason to keep making a payment, with sources. Candidates land in an
append-only notebook the proposer reads alongside the cycle report.

Two rules hold this together, and both are in the prompt as well as here:

  no numbers from this project. Section 9 keeps the proposing step away from
  the ledger because hunting a maximum across every trial ever recorded is the
  selection bias the whole protocol exists to contain. An outside notebook does
  not violate that -- external literature cannot be tainted by ORC's own
  results -- but a notebook carrying ORC's returns would, so the prompt forbids
  performance figures and reject() drops any entry that smuggles one in.

  no rules, no parameters, no grids. A mechanism is a payer and a constraint.
  Turning one into a rule shape is the proposer's job, under the adversary and
  under the probe ceiling. A scout that proposed rules would be a second
  proposer, and a second proposer raises N.

It costs zero ledger rows, which is what makes it the right thing to do with a
machine that would otherwise be idle.

  python scripts/scout.py              ask every ready provider
  python scripts/scout.py --provider codex
  python scripts/scout.py --list       what the notebook holds
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    sys.stdout.reconfigure(errors="replace")
except (AttributeError, OSError):                                  # pragma: no cover
    pass

from orc import config, llm, runstate                              # noqa: E402

NOTEBOOK = config.REPORTS / "SCOUT.jsonl"
PROMPT = config.CONFIGS / "prompts" / "scout.md"

# The scout is the only step besides the mechanism checker allowed out to the
# network, and only to read.  It never writes to the repository; this script
# does that, from what came back.
SCOUT_TOOLS = ("WebSearch", "WebFetch", "Read")

# A payer this notebook already holds is not a new mechanism, and a second
# entry for it crowds the one file whose job is to widen the search.  Identity
# is the payer phrase, normalised - not the whole record, because two providers
# describing the same constraint in different words are one candidate.
STOPWORDS = {"a", "an", "the", "who", "that", "which", "of", "on", "in", "to",
             "for", "and", "or", "is", "are", "be", "by", "with", "at", "from",
             "must", "their", "its", "it", "as", "this", "these", "those"}

# Anything that looks like a performance figure from this project.  The prompt
# forbids them; this is the check, because a prompt is not an enforcement.
PERFORMANCE_WORDS = re.compile(
    r"\b(sharpe|calmar|cagr|mwrr|irr|tm_q05|drawdown|pbo|backtest|"
    r"annuali[sz]ed|win rate|profit factor)\b", re.I)


def _slug(payer: str) -> str:
    words = [w for w in re.findall(r"[a-z0-9]+", str(payer).lower())
             if w not in STOPWORDS]
    return "-".join(words[:8]) or hashlib.sha256(
        str(payer).encode()).hexdigest()[:12]


def load(path: Path | None = None) -> list[dict]:
    """The notebook, newest first."""
    return runstate._read_jsonl(path or NOTEBOOK, 10_000, "utc")


def known_payers(path: Path | None = None) -> list[str]:
    seen, out = set(), []
    for r in load(path):
        s = r.get("slug") or _slug(r.get("payer", ""))
        if s in seen:
            continue
        seen.add(s)
        out.append(r.get("payer", s))
    return out


def closed_mechanisms() -> str:
    """What is already answered, as prose with no numbers in it.

    The closed records carry the reason a family died, and those reasons are
    full of measurements.  Handing them to a step whose only value is that it
    has not seen this project's results would defeat the step, so only the
    family name and its own claim's first sentence go across.
    """
    from orc.orchestrator.spec import closed_families

    lines = [
        "- perpetual LONG accumulation, paying the funding rate on every "
        "settlement (KT-1: closed)",
        "- leverage above 1x for averaging down, closed on liquidation (KT-2)",
        "- any alt-basket shape, blocked until survivorship is resolved (KT-3)",
    ]
    for hid, rec in sorted(closed_families().items()):
        family = rec.get("family", "?")
        claim = ""
        reg = config.REGISTRY / f"{hid}.json"
        if reg.exists():
            try:
                claim = str(json.loads(reg.read_text(encoding="utf-8")
                                       ).get("claim", ""))
            except ValueError:
                claim = ""
        first = re.split(r"(?<=[.!?])\s", " ".join(claim.split()))[0][:240]
        first = PERFORMANCE_WORDS.sub("[metric]", first)
        lines.append(f"- {family} ({hid}): {first}")
    return "\n".join(lines)


def reject(rec: dict) -> str | None:
    """Why this candidate must not enter the notebook, or None."""
    for key in ("payer", "why_they_keep_paying", "what_would_end_it",
                "observable", "confidence", "distinct_from"):
        if not str(rec.get(key) or "").strip():
            return f"missing {key}"
    if str(rec.get("confidence")).lower() not in ("high", "medium", "low"):
        return f"confidence {rec.get('confidence')!r} is not high/medium/low"
    blob = json.dumps(rec, ensure_ascii=False)
    hit = PERFORMANCE_WORDS.search(blob)
    if hit:
        # Not pedantry.  The proposer reads this file, and it is kept away from
        # performance figures on purpose; one leaking in here would reach it by
        # the back door.
        return f"carries a performance term ({hit.group(0)!r}); the notebook is " \
               "read by the step that must not see this project's results"
    if len(str(rec.get("payer"))) > 300:
        return "the payer phrase is a paragraph, not an identifiable party"
    return None


def scout_prompt(notebook: Path | None = None) -> str:
    """The question, which is the same for every provider."""
    known = known_payers(notebook or NOTEBOOK)
    return PROMPT.read_text(encoding="utf-8").format(
        closed=closed_mechanisms(),
        known=("\n".join(f"- {k}" for k in known[:40]) if known
               else "(the notebook is empty)"))


def scout_once(provider: str, notebook: Path | None = None,
               text: str | None = None, error: str | None = None) -> dict:
    """One provider, one pass.  Returns what happened, and never raises for a
    provider problem: a scout that cannot be reached has found nothing, which
    is a normal outcome and not a failure of the loop.

    `text` and `error` let the CALLER do the asking, so several providers can be
    asked at once while the merge below stays serial.  The merge must stay
    serial: it dedupes against payers already in the notebook, and two of them
    appending at the same time would each miss what the other had just added
    and write the same payer twice.
    """
    nb = notebook or NOTEBOOK
    known = known_payers(nb)
    out = {"provider": provider, "asked_utc": datetime.now(timezone.utc).isoformat(),
           "added": [], "rejected": [], "duplicates": []}
    if error is not None:
        out["error"] = error
        return out
    if text is None:
        try:
            text = llm.ask(scout_prompt(nb), tools=SCOUT_TOOLS, provider=provider,
                           cwd=config.ORC_ROOT)
        except llm.LLMUnavailable as exc:
            out["error"] = str(exc)
            return out
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        out["error"] = f"no JSON array in the reply: {text[:200]}"
        return out
    try:
        cands = json.loads(m.group(0))
    except ValueError as exc:
        out["error"] = f"unparseable array: {exc}"
        return out
    if not isinstance(cands, list):
        out["error"] = "the reply was not an array"
        return out

    have = {_slug(k) for k in known}
    for rec in cands:
        if not isinstance(rec, dict):
            out["rejected"].append({"payer": str(rec)[:80], "why": "not an object"})
            continue
        why = reject(rec)
        if why:
            out["rejected"].append({"payer": str(rec.get("payer"))[:80], "why": why})
            continue
        slug = _slug(rec["payer"])
        if slug in have:
            out["duplicates"].append(rec["payer"])
            continue
        have.add(slug)
        row = {"utc": datetime.now(timezone.utc).isoformat(), "provider": provider,
               "slug": slug, "status": "open",
               **{k: rec.get(k) for k in
                  ("payer", "why_they_keep_paying", "what_would_end_it",
                   "observable", "needs_data_we_lack", "confidence",
                   "sources", "distinct_from")}}
        runstate._append(nb, row)
        out["added"].append(rec["payer"])
    return out


def main(argv: list[str]) -> int:
    if "--list" in argv:
        rows = load()
        for r in rows:
            need = r.get("needs_data_we_lack") or ""
            print(f"{str(r.get('utc'))[:16]}  {r.get('provider'):7s} "
                  f"{str(r.get('confidence')):6s} {r.get('payer')}")
            print(f"          why: {str(r.get('why_they_keep_paying'))[:120]}")
            print(f"          see: {str(r.get('observable'))[:120]}")
            if need:
                print(f"          NEEDS DATA WE LACK: {need[:110]}")
        print(f"\n{len(rows)} candidate(s) in {NOTEBOOK.name}")
        return 0

    if "--provider" in argv:
        wanted = [argv[argv.index("--provider") + 1]]
    else:
        wanted = [p for p, s in llm.availability().items() if s == "ready"]
    if not wanted:
        print("no provider is ready; nothing was asked")
        return 1

    # Asked at once, merged in turn.  Two providers in series made the scout
    # cost the sum of two model calls -- 483s on the run that found three new
    # payers -- for two questions that do not depend on each other.
    replies, errors = llm.ask_many(scout_prompt(), wanted, tools=SCOUT_TOOLS,
                                   cwd=config.ORC_ROOT)

    worst = 0
    for p in wanted:
        r = scout_once(p, text=replies.get(p), error=errors.get(p))
        if r.get("error"):
            print(f"{p}: SKIPPED -- {r['error'][:200]}")
            worst = max(worst, 1)
            continue
        print(f"{p}: {len(r['added'])} new, {len(r['duplicates'])} already known, "
              f"{len(r['rejected'])} rejected")
        for a in r["added"]:
            print(f"  + {a}")
        for d in r["duplicates"]:
            print(f"  = {d}")
        for x in r["rejected"]:
            print(f"  - {x['payer']}: {x['why']}")
    return worst


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
