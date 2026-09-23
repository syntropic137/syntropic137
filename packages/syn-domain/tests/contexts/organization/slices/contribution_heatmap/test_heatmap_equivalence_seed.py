"""The equivalence test's seed must actually reach the database (#1253).

NOT A SUBSTITUTE for test_heatmap_rollup_equivalence.py. That file compares the
pre-#1253 heatmap with the post-#1253 one against a real database, and nothing
here does any of that. This guards ONE way that file could pass while proving
nothing.

``insert_batch`` validates each event and, on failure, logs a warning and DROPS
it. Two implementations agree perfectly about a commit neither of them can see,
so an event silently lost on the way in weakens the comparison without
breaking it - and the loss is invisible, because a dropped row leaves no mark
in the assertion, only a line in the log.

That is not hypothetical. The first draft of the seed gave each commit a
``message`` field; ``AgentEvent.from_dict`` reads ``message`` as a Claude
content envelope and calls ``.get`` on it, so every commit in the seed raised,
every commit was dropped, and the equivalence assertions would have compared
two heatmaps reporting zero commits.

Marked ``unit``: the integration job does not run on a PR into ``main``, and a
guard against a vacuous test is worth having before the merge rather than
after it. It needs no database, because the validation it exercises is the
pure-Python half of the write path.
"""

from __future__ import annotations

import pytest

from .test_heatmap_rollup_equivalence import (
    SEEDED_COMMITS,
    SEEDED_SESSIONS,
    _events_reaching_the_rollup_by_backfill,
    _events_reaching_the_rollup_by_trigger,
)

pytestmark = pytest.mark.unit

_BATCHES = {
    "backfill": _events_reaching_the_rollup_by_backfill,
    "trigger": _events_reaching_the_rollup_by_trigger,
}


@pytest.mark.parametrize("batch_name", sorted(_BATCHES))
def test_every_seeded_event_survives_the_write_path(batch_name: str) -> None:
    """Each event must produce a COPY row - the same check insert_batch makes.

    ``_build_copy_buffer`` is the private half of ``insert_batch``, and it is
    what is called here on purpose: it is the exact code that decides whether
    an event becomes a row, and asserting against a reimplementation of its
    rules would pass while the real one dropped things.
    """
    from syn_adapters.events.store_helpers import _build_copy_buffer

    events = _BATCHES[batch_name]()
    buffer = _build_copy_buffer(list(events), None, None)
    rows = buffer.getvalue().decode().splitlines()

    assert len(rows) == len(events), (
        f"the {batch_name} batch seeds {len(events)} events but only {len(rows)} "
        "reach agent_events. insert_batch logged a warning and dropped the rest, "
        "so the equivalence test would compare two heatmaps that cannot see them."
    )


def test_the_seed_holds_what_the_equivalence_assertions_claim() -> None:
    """The named constants are the numbers the seed actually contains.

    The equivalence test asserts exact totals - nine sessions, ten commits -
    rather than "> 0", because an exact count is what makes agreement
    non-vacuous. Those constants are stated in one place and the seed in
    another, so this is what keeps them the same statement.
    """
    events = [*_events_reaching_the_rollup_by_backfill(), *_events_reaching_the_rollup_by_trigger()]

    sessions = {event["session_id"] for event in events}
    commits = [event for event in events if event["event_type"] == "git_commit"]

    assert len(sessions) == SEEDED_SESSIONS
    assert len(commits) == SEEDED_COMMITS


def test_both_halves_of_the_seed_are_substantial_and_disjoint() -> None:
    """Sessions belong to one path or the other, and both paths carry real ones.

    The point of the two batches is that half the rows reach the rollup through
    the BACKFILL and half through the TRIGGER. A session appearing in both
    would be written partly before the rollup exists and partly after, so
    neither path would be tested on its own; an empty batch would mean one path
    is not tested at all.
    """
    before = {event["session_id"] for event in _events_reaching_the_rollup_by_backfill()}
    after = {event["session_id"] for event in _events_reaching_the_rollup_by_trigger()}

    assert before & after == set(), "a session cannot be seeded through both paths"
    assert len(before) >= 4
    assert len(after) >= 4
