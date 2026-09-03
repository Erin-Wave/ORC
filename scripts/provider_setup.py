"""ORC | Find out how a model CLI actually wants to be called, by calling it.

llm.py refuses to use a provider that is not marked verified, because an
invocation that half-works is worse than one that fails: a CLI given the wrong
flags prints its help text on stdout and exits zero, and ask_json would parse
that as a verdict. Something has to do the verifying, and it should not be a
human reading `--help` and hand-editing JSON -- that is how the wrong flags get
written down with confidence.

So this tries the candidate invocations in order and keeps the first one that
answers a question with a checkable answer. An end-to-end reply is proof of
three things at once that no amount of reading `--help` can establish: the
binary runs, the account is logged in, and the argv is right.

  python scripts/provider_setup.py           what is usable right now
  python scripts/provider_setup.py codex     probe, smoke-test, write the config

Two smoke tests, because the pipeline needs both shapes: prose (the surface
reader, the post-mortem) and a JSON object (the adversary, the mechanism check).
A provider that passes the first and fails the second is recorded as prose-only
rather than as working, since the adversary is the step a second vendor exists
for.

Each probe sends a handful of tokens to the vendor and therefore spends a
little of whatever pays for that account.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    sys.stdout.reconfigure(errors="replace")
except (AttributeError, OSError):                                  # pragma: no cover
    pass

from orc import config, llm                                        # noqa: E402

# A token no help text and no refusal will contain by accident.
TOKEN = "ORCPROBE7391"

# The probe prompt has to look like a real one or it verifies nothing.  A one
# line probe passed this project's first attempt at `codex exec <prompt>` --
# exit 0, token returned -- and the real 2 KB, 38 line adversary prompt then
# arrived empty, so the vendor answered "please share the document" and the
# reply was recorded as a review that could not be parsed.  On Windows the CLI
# is reached through a .CMD shim, and a long multi-line argument does not
# survive it.
#
# So: several KB, many lines, braces and quotes, and the instruction LAST.  An
# invocation that truncates, mangles or ignores its prompt fails this, which is
# the whole job.
_FILLER = "\n".join(
    f'Line {i}: filler that makes this prompt realistically long, containing '
    '{"braces": true}, "quotes", and a trailing backslash \\ to be awkward.'
    for i in range(40))
PROSE_PROMPT = (f"You are reviewing a document.\n{_FILLER}\n\n"
                f"IGNORE every line above. Reply with exactly {TOKEN} and "
                "nothing else.")
JSON_PROMPT = (f"You are reviewing a document.\n{_FILLER}\n\n"
               "IGNORE every line above. Reply with exactly this JSON object "
               'and nothing else, no code fence: {"ok": true, "probe": "'
               + TOKEN + '"}')

# Ordered candidates, stdin forms FIRST.  A prompt on stdin has no length limit
# and no quoting rules; a prompt in argv has both, and on Windows it also has a
# batch-file shim in the way.  The conservative sandbox flag comes before the
# permissive one -- none of these calls has any business writing anything.
CANDIDATES: dict[str, list[dict]] = {
    "codex": [
        {"argv": ["exec", "--sandbox", "read-only", "-"], "stdin": True},
        {"argv": ["exec", "-"], "stdin": True},
        {"argv": ["exec", "--sandbox", "read-only", "{prompt}"], "stdin": False},
        {"argv": ["exec", "{prompt}"], "stdin": False},
    ],
    "gemini": [
        {"argv": [], "stdin": True},
        {"argv": ["-p", "{prompt}"], "stdin": False},
    ],
}

PROBE_TIMEOUT_S = 180


def _run(binary: str, spec: dict, prompt: str) -> tuple[int, str, str]:
    use_stdin = spec.get("stdin", True)
    cmd = [binary] + [a.replace("{prompt}", prompt) if not use_stdin else a
                      for a in spec.get("argv", [])]
    try:
        r = subprocess.run(cmd, input=prompt if use_stdin else None,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=PROBE_TIMEOUT_S,
                           cwd=str(config.ORC_ROOT))
    except subprocess.TimeoutExpired:
        return 124, "", f"no reply within {PROBE_TIMEOUT_S}s"
    except OSError as exc:
        return 126, "", str(exc)
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


def probe(name: str) -> int:
    spec_default = llm.providers().get(name, {})
    binary = spec_default.get("binary", name)
    exe = shutil.which(binary)
    if not exe:
        print(f"the {binary!r} CLI is not on PATH.")
        if name == "codex":
            print("\nInstall it and sign in with the ChatGPT account -- that is what "
                  "makes the subscription pay for these calls instead of an API key:")
            print("    npm install -g @openai/codex")
            print("    codex login")
            print("\n`codex login` opens a browser and needs your hands; run it "
                  "yourself, then run this again.")
        return 2
    print(f"found {exe}")

    candidates = CANDIDATES.get(name) or [
        {"argv": spec_default.get("argv", []), "stdin": spec_default.get("stdin", True)}]

    winner = None
    for i, cand in enumerate(candidates, 1):
        shown = " ".join([binary] + list(cand["argv"]))
        print(f"\n[{i}/{len(candidates)}] {shown}"
              f"{'   (prompt on stdin)' if cand['stdin'] else ''}")
        rc, out, err = _run(exe, cand, PROSE_PROMPT)
        if rc != 0:
            print(f"    exit {rc}: {(err or out)[:200]}")
            continue
        if TOKEN not in out:
            # Ran, but did not answer.  Either help text, or -- the case that
            # cost this project a mangled review -- the prompt never arrived
            # and the vendor answered the empty question politely, with a zero
            # exit code and prose that looks like a real reply.
            print(f"    exit 0 but the prompt did not arrive. "
                  f"First 160 chars back: {out[:160]!r}")
            continue
        print("    answered")
        winner = cand
        break

    if winner is None:
        print(f"\nNo invocation of {binary!r} answered a question.")
        print("If one of the lines above shows a login or quota error, fix that "
              "and run this again. If they all show help text, paste `"
              f"{binary} exec --help` here and I will add the right form.")
        return 1

    print("\nchecking it can return a JSON verdict, which the adversary needs")
    rc, out, err = _run(exe, winner, JSON_PROMPT)
    json_ok = False
    if rc == 0 and TOKEN in out:
        try:
            import re
            m = re.search(r"\{.*\}", out, re.S)
            json_ok = bool(m and json.loads(m.group(0)).get("ok") is True)
        except (ValueError, AttributeError):
            json_ok = False
    print("    JSON verdict ok" if json_ok else
          f"    NOT usable for verdicts: {(err or out)[:200]!r}")

    path = config.CONFIGS / "providers.json"
    current = {}
    if path.exists():
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            print(f"\n{path} exists but is not valid JSON; leaving it alone.")
            return 1
    current[name] = {
        "binary": binary,
        "argv": list(winner["argv"]),
        "stdin": bool(winner["stdin"]),
        "verified": bool(json_ok),
        "verified_note": (
            "probed end to end by scripts/provider_setup.py: this argv answered "
            "a prose prompt and returned a parseable JSON object"
            if json_ok else
            "answers prose but did not return a parseable JSON object, so it is "
            "NOT enabled: the adversary is the step a second vendor exists for "
            "and it needs a verdict object"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
    print(f"\nwritten: {path}")
    print(json.dumps(current[name], indent=2))
    if json_ok:
        print(f"\n{name} is now a voting adversary. Every proposal must survive "
              "it AND claude to reach the queue; either one can kill. It cannot "
              "approve anything on its own and it never proposes -- a second "
              "proposer would raise N, which is the one thing that cannot be "
              "undone.")
    else:
        print(f"\n{name} stays disabled. Nothing else changes.")
    return 0 if json_ok else 1


def main(argv: list[str]) -> int:
    if not argv:
        for name, state in llm.availability().items():
            print(f"{name:10s} {state}")
        known = ", ".join(sorted(CANDIDATES))
        print(f"\nTo set one up:  python scripts/provider_setup.py <name>   "
              f"(probes known: {known})")
        return 0
    return probe(argv[0])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
