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


# --------------------------------------------------------------------------
# What may stop the research cycle, and what may not
# --------------------------------------------------------------------------
# `orc-cycle` ran `pytest tests -q` and skipped its Research step on ANY red
# test. Twice on 2026-09-04 that was a test of mine about this workstation --
# one asserting .git/hooks exists, one reading the real configs/queue/ while
# GITHUB_ACTIONS was set -- and research stopped for hours over a briefing's
# line count and a screen's wording.
#
# CLAUDE.md section 5 says what actually voids a result: "if that test fails,
# every result in the project is void", about the two evaluators agreeing. It
# does not say a long briefing stops research. So the cycle now runs
# `pytest tests -m gate`, and the FULL suite still runs on every push in
# orc-guard -- a tooling defect stays loud without holding the research
# hostage.
#
# tests/test_kernel.py is the gate in its entirety: it is the correctness
# suite. From the protocol suite, these are the ones whose failure means a
# recorded number could be wrong or the seal could be breached. The list is
# frozen here rather than scattered as decorators so that one test can assert
# every name in it still exists -- a renamed invariant that silently left the
# gate is the failure this list is most likely to have.
GATE_MODULE = "test_kernel.py"
GATE_TESTS = frozenset({
    # the seal
    "test_development_slice_stops_at_the_seal",
    "test_sealed_slice_is_the_complement",
    "test_sealed_bars_are_refused_outside_a_final_test",
    "test_a_final_test_can_ask_for_the_sealed_span_alone",
    "test_final_test_refuses_without_a_hand_written_token",
    "test_final_test_rejects_a_wrong_token",
    "test_final_test_consumes_the_token_and_is_capped",
    "test_one_opening_cannot_quietly_cover_a_whole_grid",
    "test_the_permit_is_dropped_even_when_the_final_test_raises",
    "test_the_spend_count_is_the_ordinal_not_the_line_count",
    # pre-registration
    "test_editing_the_grid_after_registration_is_refused",
    "test_editing_the_claim_after_registration_is_refused",
    "test_registration_survives_a_round_trip",
    "test_a_grid_beyond_the_ceiling_is_refused_whole",
    "test_a_grid_that_can_never_be_shape_checked_is_refused",
    "test_intake_refuses_a_wide_grid_on_an_untested_mechanism",
    # the ledger, and N
    "test_ledger_rejects_update",
    "test_ledger_rejects_delete",
    "test_the_code_hash_covers_everything_that_writes_a_number",
    "test_the_code_hash_covers_the_module_that_routes_and_prices_a_trial",
    "test_the_code_hash_covers_every_file_that_can_change_a_number",
    "test_a_ledger_conflict_unions_and_never_picks_a_side",
    "test_the_merge_driver_refuses_rather_than_shrink_the_ledger",
    # what disqualifies a cell
    "test_a_spike_is_not_a_finding_however_large",
    "test_every_disqualifier_is_reported_not_just_the_first",
    "test_an_unmeasured_check_is_not_a_pass_and_not_a_failure",
    "test_an_unmeasured_path_count_is_not_a_pass_either",
    "test_a_pbo_that_was_never_computed_is_not_a_pass",
    "test_a_pbo_measured_on_other_cells_does_not_clear_this_one",
    "test_plateau_score_cannot_see_a_two_level_grid",
    "test_the_search_test_null_runs_the_shape_it_is_a_null_for",
    "test_the_null_routes_a_cell_the_way_a_real_trial_does",
    # the stop condition
    "test_the_stop_condition_needs_both_halves",
    "test_the_stop_condition_ignores_sealed_rows",
    "test_a_candidate_is_not_verified_by_checks_that_never_ran",
})


def pytest_collection_modifyitems(config, items):
    """Mark the gate, in one place, from the list above."""
    for item in items:
        module = Path(str(item.fspath)).name
        if module == GATE_MODULE or item.name.split("[")[0] in GATE_TESTS:
            item.add_marker(pytest.mark.gate)


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
