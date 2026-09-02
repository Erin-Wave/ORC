"""ORC | Calling a model, from code that is not itself a model.

Five things in this project want a judgement rather than a calculation: an
adversary that tries to kill a hypothesis before it is registered, a researcher
that checks whether the named payer exists, a reviewer that reads the
evaluation kernel looking for the next silent divergence, a post-mortem that
writes down why a family broke, and a reader that describes a response surface
instead of its maximum.

None of them may touch a number.  The evaluators are deterministic and
cross-checked, the verdict thresholds are pre-registered constants, and both
stay that way -- a model that could argue a cell through the gate would make
the whole apparatus theatre.  What a model is allowed to do here is doubt, and
doubt is cheap to check: every one of these writes prose or a small JSON
verdict, and every verdict is either "this is fine" or a reason it is not.

Calls run through the CLI rather than an SDK so the subscription pays for them
rather than an API key, and so this file needs no secret to exist.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

# Judgement work, so the larger model.  A cheaper one is a false economy on a
# task whose entire output is whether something is worth believing.
DEFAULT_MODEL = "claude-opus-5"

# These calls read files and answer.  None of them commits, pushes, or edits
# the working tree: the orchestrating script does that, so a model that goes
# wrong produces a bad answer rather than a bad repository.
READ_ONLY_TOOLS = ("Read", "Glob", "Grep")

# Long enough for a real read of the kernel, short enough that a hung call does
# not eat the whole scheduled window.
DEFAULT_TIMEOUT_S = 900


class LLMUnavailable(RuntimeError):
    """No CLI, no credentials, or the call failed.  Callers degrade, never guess."""


def _binary() -> str:
    exe = shutil.which("claude")
    if exe:
        return exe
    local = Path(os.environ.get("USERPROFILE", "~")).expanduser() / ".local/bin/claude.exe"
    if local.exists():
        return str(local)
    raise LLMUnavailable("the claude CLI is not on PATH; judgement steps are skipped")


def ask(prompt: str, *, model: str = DEFAULT_MODEL,
        tools: tuple[str, ...] = READ_ONLY_TOOLS,
        cwd: str | Path | None = None,
        timeout_s: int = DEFAULT_TIMEOUT_S) -> str:
    """Run one prompt and return what came back, or raise LLMUnavailable."""
    cmd = [_binary(), "-p", "--model", model]
    if tools:
        cmd += ["--allowedTools", *tools]
    try:
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           timeout=timeout_s, cwd=str(cwd) if cwd else None)
    except subprocess.TimeoutExpired as exc:
        raise LLMUnavailable(f"call timed out after {timeout_s}s") from exc
    except OSError as exc:
        raise LLMUnavailable(str(exc)) from exc
    if r.returncode != 0:
        raise LLMUnavailable(f"exit {r.returncode}: {(r.stderr or '').strip()[:300]}")
    if not (r.stdout or "").strip():
        raise LLMUnavailable("the model returned nothing")
    return r.stdout.strip()


def ask_json(prompt: str, **kw) -> dict:
    """Same, for a verdict.  Extracts the first JSON object in the reply.

    Models wrap JSON in prose and fences however they like, and a parse failure
    here must not be mistaken for a verdict, so an unreadable reply raises
    rather than defaulting to either answer.
    """
    text = ask(prompt, **kw)
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise LLMUnavailable(f"no JSON object in the reply: {text[:200]}")
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError as exc:
        raise LLMUnavailable(f"unparseable JSON: {exc}") from exc


def load_prompt(name: str, **fields) -> str:
    """Read configs/prompts/<name>.md and substitute {placeholders}.

    Prompts live in the repository rather than in the scripts so they are
    versioned, diffable and reviewable like any other part of the protocol.
    """
    from orc import config

    p = config.ORC_ROOT / "configs" / "prompts" / f"{name}.md"
    if not p.exists():
        raise LLMUnavailable(f"no prompt file at {p}")
    text = p.read_text(encoding="utf-8")
    for k, v in fields.items():
        text = text.replace("{" + k + "}", str(v))
    return text
