"""ORC | What the suite is never allowed to reach, and what must not reach it.

On 2026-09-04 the adversary veto and the close vote moved from `llm.ask_json`
to `llm.ask_json_many`, so that two providers are asked at once instead of the
pass paying the sum of them.  Two tests pinned `llm.ask_json` and nothing else,
so the moment the call site moved they stopped stubbing anything and went to
the real CLIs: the suite ran for 5 minutes 57 instead of 8 seconds, and two
verdicts came back from a live model instead of from the fixture.

Nothing failed loudly.  The tests failed on the ANSWER, which is the shape a
test takes when it has quietly started measuring something else entirely, and
the only reason it was caught is that a live model disagreed with the fixture.

So the boundary is enforced here rather than restated in each test.  Every
model call in the project funnels through `orc.llm.ask`, and in the suite that
function raises.  A test that wants an answer pins the function it actually
calls -- which is now checked, because pinning the wrong one fails instead of
silently going to the network.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


@pytest.fixture(autouse=True)
def no_ambient_runner_environment(monkeypatch):
    """GITHUB_ACTIONS must not decide what a test measures.

    `runstate.next_action()` reads it: on a runner a non-empty queue makes the
    answer `cycle`, because the runner is the machine that collects the queue.
    A test that called next_action() therefore passed here and failed there --
    and the suite is the gate on the research cycle, so it stopped research for
    the second time in one day.

    Unset by default. A test that wants the runner's behaviour says so with
    monkeypatch.setenv, which is per-test and visible in the test.
    """
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    yield


@pytest.fixture(autouse=True)
def no_live_model_calls(monkeypatch):
    """Autouse: `llm._binary` is the last step before a real CLI is launched.

    The guard sits here rather than on `ask` for two reasons.  `ask` carries
    `ask.tree_violations`, which several tests read, and replacing the function
    takes the attribute with it.  More importantly, the tests that exercise
    `ask` ITSELF -- the unverified-provider refusal, the tree-violation record,
    the concurrency barrier -- do so by pointing `_binary` at a fake, and a
    test that has taken control of `_binary` has said what it wants to run.
    A test that has NOT is about to launch whatever is on PATH.
    """
    from orc import llm

    def _refuse(provider=None, *a, **k):
        raise AssertionError(
            f"a test tried to launch the real {provider!r} provider CLI. The "
            "suite must never reach one: it costs minutes, it needs "
            "credentials the runner does not have, and an answer from a live "
            "model is not the answer the test wrote down. Pin the function the "
            "code under test actually calls (ask, ask_json, ask_many, "
            "ask_json_many), or point llm._binary at a fake.")

    monkeypatch.setattr(llm, "_binary", _refuse)
    yield
