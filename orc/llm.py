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

That is also why a second vendor fits here at all.  A second opinion is worth
having on exactly one of these five -- the adversary, the step that spends
judgement to PROTECT N rather than to consume it -- because two models that
disagree about whether a payer is real is information, and one model checking
its own homework is not.  Providers are therefore declared in
configs/providers.json rather than hard-coded: a CLI's flags are not this
project's business, and getting them wrong should cost a line of config rather
than a patch.
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

# The provider every step uses unless told otherwise.  Nothing about the
# protocol depends on which vendor answers; what depends on it is that the
# answer is written down, so every verdict records the provider that gave it.
DEFAULT_PROVIDER = "claude"

# Shipped defaults.  configs/providers.json overrides or adds to these.
#   binary   looked up on PATH
#   argv     the command, with {prompt} substituted if stdin is false
#   stdin    true: the prompt goes to stdin.  false: it is an argv element
#   tools_flag / model_flag  omitted when the CLI has no such concept
BUILTIN_PROVIDERS: dict[str, dict] = {
    "claude": {
        "binary": "claude",
        "argv": ["-p"],
        "stdin": True,
        "model_flag": "--model",
        "model": DEFAULT_MODEL,
        "tools_flag": "--allowedTools",
        "verified": True,
    },
    # OpenAI's Codex CLI signs in with a ChatGPT account, so a ChatGPT
    # subscription pays for these calls the same way the Claude subscription
    # pays for the ones above -- no API key, no per-token bill.
    #
    # UNVERIFIED on this machine: the CLI is not installed here and its flags
    # are its own business, not this project's.  Run `codex exec --help`, put
    # what it actually wants in configs/providers.json, and set verified true.
    # Until then availability() reports it as absent and every step degrades to
    # the single provider, which is exactly today's behaviour.
    "codex": {
        "binary": "codex",
        "argv": ["exec", "--sandbox", "read-only", "{prompt}"],
        "stdin": False,
        "model_flag": None,
        "model": None,
        "tools_flag": None,
        "verified": False,
    },
}


class LLMUnavailable(RuntimeError):
    """No CLI, no credentials, or the call failed.  Callers degrade, never guess."""


def providers() -> dict[str, dict]:
    """The built-in table, overlaid with configs/providers.json if it exists."""
    from orc import config

    out = {k: dict(v) for k, v in BUILTIN_PROVIDERS.items()}
    p = config.ORC_ROOT / "configs" / "providers.json"
    if p.exists():
        try:
            for name, spec in json.loads(p.read_text(encoding="utf-8")).items():
                out.setdefault(name, {}).update(spec)
        except (ValueError, OSError):
            pass
    return out


def _binary(provider: str = DEFAULT_PROVIDER) -> str:
    spec = providers().get(provider)
    if spec is None:
        raise LLMUnavailable(f"no provider {provider!r} in configs/providers.json")
    name = spec.get("binary", provider)
    exe = shutil.which(name)
    if exe:
        return exe
    local = Path(os.environ.get("USERPROFILE", "~")).expanduser() / f".local/bin/{name}.exe"
    if local.exists():
        return str(local)
    raise LLMUnavailable(f"the {name} CLI is not on PATH; this step is skipped")


def availability() -> dict[str, str]:
    """Which providers could answer right now, and why the others could not.

    A step that wants a second opinion asks this rather than assuming: an
    absent CLI must degrade to one opinion, never to a fabricated one.
    """
    out = {}
    for name, spec in providers().items():
        try:
            _binary(name)
        except LLMUnavailable as exc:
            out[name] = f"unavailable: {exc}"
            continue
        out[name] = "ready" if spec.get("verified") else (
            "installed, but its invocation is unverified -- check `--help`, fix "
            "configs/providers.json and set verified true")
    return out


def ask(prompt: str, *, model: str | None = None,
        tools: tuple[str, ...] = READ_ONLY_TOOLS,
        cwd: str | Path | None = None,
        timeout_s: int = DEFAULT_TIMEOUT_S,
        provider: str = DEFAULT_PROVIDER) -> str:
    """Run one prompt and return what came back, or raise LLMUnavailable."""
    spec = providers().get(provider) or {}
    if not spec.get("verified", False):
        raise LLMUnavailable(
            f"provider {provider!r} is not marked verified in "
            "configs/providers.json; an unverified invocation would report a "
            "CLI usage error as a model verdict")
    cmd = [_binary(provider)]
    argv = list(spec.get("argv", []))
    if spec.get("model_flag") and (model or spec.get("model")):
        cmd += [spec["model_flag"], model or spec["model"]]
    if spec.get("tools_flag") and tools:
        cmd += [spec["tools_flag"], *tools]
    use_stdin = spec.get("stdin", True)
    cmd += [a.replace("{prompt}", prompt) if not use_stdin else a for a in argv]
    try:
        r = subprocess.run(cmd, input=prompt if use_stdin else None,
                           capture_output=True, text=True,
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


if __name__ == "__main__":                                         # pragma: no cover
    for _name, _state in availability().items():
        print(f"{_name:10s} {_state}")
