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

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
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


def tree_fingerprint(cwd: str | Path | None = None) -> str | None:
    """`git status --porcelain`, or None if it cannot be read.

    The docstring above promises that none of these calls edits the working
    tree, and for the Claude CLI that is enforced by --allowedTools. A second
    vendor has its own flags and its own idea of a sandbox, so the promise
    needed enforcing rather than restating: codex, invoked with
    `--sandbox read-only`, wrote a 193-line copy of the constitution into
    AGENTS.md during an adversary review. Benign content, broken invariant --
    and it was then committed by a `git add -A` that trusted the promise.
    """
    try:
        r = subprocess.run(["git", "status", "--porcelain"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=30,
                           cwd=str(cwd) if cwd else None)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None

    # Each dirty path carries a hash of its CONTENT, because the status line
    # alone is blind in exactly the case that bit this project.
    #
    # On 2026-09-04 a reasoning pass ran while tests/test_protocol.py was
    # already modified, and a provider appended four tests to it. The file was
    # " M" before the call and " M" after, the line sets were identical, and
    # nothing was recorded: the detector could see a file BECOME dirty and not
    # a dirty file being edited further. An unattended model writing into a
    # working tree it was told to leave alone is the whole reason this function
    # exists, and it had a hole the size of every file already being worked on.
    root = Path(cwd) if cwd else Path.cwd()
    out = []
    for line in (r.stdout or "").splitlines():
        if not line.strip():
            continue
        path = line[3:].strip()
        if " -> " in path:                       # a rename; the target is what exists
            path = path.split(" -> ")[-1]
        path = path.strip('"')
        try:
            digest = hashlib.sha256(
                (root / path).read_bytes()).hexdigest()[:16]
        except (OSError, ValueError):
            digest = "-"                         # deleted, or a directory
        out.append(f"{line[:3]}{line[3:]}\t{digest}")
    return "\n".join(out) + ("\n" if out else "")


def _named(entry: str) -> str:
    """The path out of a fingerprint line, without the content hash."""
    return entry.split("\t")[0].strip().strip('"')


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


def _which(provider: str = DEFAULT_PROVIDER) -> str:
    """Where a provider's CLI is, or raise.  A LOOKUP, and nothing more.

    Split from `_binary` so that asking whether a provider exists and being
    about to launch it are two different calls.  The suite closes the second
    door and leaves the first open: availability() is a probe every step makes,
    and a test that probes has not tried to reach a model.
    """
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


def _binary(provider: str = DEFAULT_PROVIDER) -> str:
    """The last step before a provider CLI is launched, and the only caller of
    it is ask().  tests/conftest.py refuses this and not _which."""
    return _which(provider)


def availability() -> dict[str, str]:
    """Which providers could answer right now, and why the others could not.

    A step that wants a second opinion asks this rather than assuming: an
    absent CLI must degrade to one opinion, never to a fabricated one.
    """
    out = {}
    for name, spec in providers().items():
        try:
            _which(name)                     # a probe, never a launch
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
        provider: str = DEFAULT_PROVIDER,
        check_tree: bool = True) -> str:
    """Run one prompt and return what came back, or raise LLMUnavailable.

    `check_tree` exists for ask_many and nothing else.  The before/after
    fingerprint below attributes a working-tree edit to the provider that made
    it, and two calls running at once in one directory would each see the
    other's edits.  A concurrent batch therefore takes the fingerprint once,
    around the whole batch, and this is how the per-call check is turned off.
    """
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
    before = tree_fingerprint(cwd) if (cwd and check_tree) else None
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

    # A read-only call that changed the tree has broken its contract, so the
    # answer is recorded together with the fact rather than quietly trusted.
    # Nothing is reverted here: deleting a file this project did not expect is
    # a worse failure than reporting one.
    if before is not None:
        after = tree_fingerprint(cwd)
        if after is not None and after != before:
            b = {ln[3:] for ln in before.splitlines()}
            a = {ln[3:] for ln in after.splitlines()}
            touched = sorted({_named(e) for e in a - b}) or ["(a tracked file changed)"]
            ask.tree_violations.append({"provider": provider, "files": touched})
            print(f"WARNING: the {provider!r} call was read-only and changed the "
                  f"working tree: {', '.join(touched)}. The answer is kept and "
                  "the violation is recorded; nothing was reverted.",
                  file=sys.stderr)
    return r.stdout.strip()


# Appended to by ask(); the reasoning pass writes it into REASONING_LOG.json so
# a broken invariant is visible in the record rather than only on a console.
ask.tree_violations = []


def ask_many(prompt: str, provider_names: list[str], *,
             cwd: str | Path | None = None,
             **kw) -> tuple[dict[str, str], dict[str, str]]:
    """Ask several providers the same question AT ONCE.

    Returns ({provider: reply}, {provider: why it could not answer}).  A
    provider that cannot be reached is reported, never assumed to have agreed:
    that rule belongs to the callers and this must not quietly break it.

    Every step that wants more than one opinion -- the adversary veto, the
    close vote, the scout -- asked each provider in turn and paid the SUM of
    them, and these are subprocesses waiting on a network rather than on this
    CPU.  A pass that runs two providers serially is a pass that uses the
    second subscription half as often as it could.

    Threads, not processes: the work is entirely in `subprocess.run` waiting on
    a child, so the GIL is not held and a process pool would only add the cost
    of shipping the prompt.

    The tree check moves from the call to the BATCH.  ask() fingerprints the
    working tree before and after so a read-only call that edited it is
    recorded against whoever did it -- codex, invoked with
    `--sandbox read-only`, once wrote a 193-line copy of the constitution into
    AGENTS.md.  Concurrent calls in one directory would each see the other's
    edits and name the wrong provider, so the batch records every provider that
    was running when the tree changed.  That is a weaker attribution than the
    serial path gives, and unlike the alternative it is true.
    """
    from concurrent.futures import ThreadPoolExecutor

    names = list(provider_names)
    if not names:
        return {}, {}

    before = tree_fingerprint(cwd) if cwd else None

    def _one(name: str) -> tuple[str, str | None, str | None]:
        try:
            return name, ask(prompt, cwd=cwd, provider=name,
                             check_tree=False, **kw), None
        except LLMUnavailable as exc:
            return name, None, str(exc)

    replies: dict[str, str] = {}
    errors: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=len(names)) as pool:
        for name, text, err in pool.map(_one, names):
            if err is None:
                replies[name] = text
            else:
                errors[name] = err

    if before is not None:
        after = tree_fingerprint(cwd)
        if after is not None and after != before:
            b = {ln[3:] for ln in before.splitlines()}
            a = {ln[3:] for ln in after.splitlines()}
            touched = sorted({_named(e) for e in a - b}) or ["(a tracked file changed)"]
            ask.tree_violations.append(
                {"provider": "+".join(sorted(names)),
                 "files": touched,
                 "note": "concurrent batch; the tree changed while these "
                         "providers were running and the edit cannot be "
                         "attributed to one of them"})
            print(f"WARNING: a concurrent read-only batch ({', '.join(names)}) "
                  f"changed the working tree: {', '.join(touched)}. The answers "
                  "are kept and the violation is recorded; nothing was reverted.",
                  file=sys.stderr)
    return replies, errors


def ask_json_many(prompt: str, provider_names: list[str],
                  **kw) -> tuple[dict[str, dict], dict[str, str]]:
    """ask_many, with each reply parsed as a verdict.

    A reply that cannot be parsed joins the errors rather than the verdicts: an
    unreadable answer is not a vote, and defaulting it to either side is how a
    veto gets lost.
    """
    replies, errors = ask_many(prompt, provider_names, **kw)
    out: dict[str, dict] = {}
    for name, text in replies.items():
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            errors[name] = f"no JSON object in the reply: {text[:200]}"
            continue
        try:
            out[name] = json.loads(m.group(0))
        except json.JSONDecodeError as exc:
            errors[name] = f"unparseable JSON: {exc}"
    return out, errors


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
