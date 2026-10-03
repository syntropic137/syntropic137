"""Untrusted agent text must never be able to fail a Postgres write (#1241, #781).

An agent emitted a NUL byte in its output; persisting it raised

    unsupported Unicode escape sequence
    DETAIL: \\u0000 cannot be converted to text

and took down the ENTIRE execution rather than that one field. Three of a
hundred executions between 2026-09-08 and 2026-09-16 died that way.

These tests drive each Postgres write boundary agent-produced text crosses, with
a payload that carries the real hostile codepoints - an actual chr(0) and an
actual lone surrogate, not a "\\u0000"-looking string - and assert on the values
that reach the driver, not on the objects the boundary was handed. A boundary
that sanitises and then drops the sanitised value one hop later passes every
test that only looks at either end.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit

from syn_adapters.postgres_text import pg_safe  # noqa: E402
from syn_domain import tool_call_counts  # noqa: E402

# The actual characters. Written via chr() so no editor, formatter or copy-paste
# can quietly turn them into their harmless six-character text spelling - which
# is the near-miss that would certify this class closed while it is open.
NUL = chr(0)
LONE_SURROGATE = chr(0xDEAD)
ESCAPE_TEXT = chr(92) + "u0000"  # six ordinary characters: backslash u 0 0 0 0

#: What an agent's captured tool output looked like on the way in.
HOSTILE = "before" + NUL + "middle" + LONE_SURROGATE + "after"
#: ...and what it must look like on the way out.
#:
#: The readable text survives IN FRONT, followed by a marker recording that the
#: value was altered. The marker is not decoration: stripping alone is not
#: injective, so `"session-a\x00b"` and `"session-ab"` stripped to the same
#: string and two sessions shared every key derived from it. The suffix is a
#: function of the raw input, so distinct inputs stay distinct.
#:
#: It also makes the edit VISIBLE, which plain stripping never did. Agent text
#: that reaches a reader without its NUL is text the system changed, and a
#: reader has a right to know that rather than being handed a quiet forgery.
CLEANED_PREFIX = "beforemiddleafter"


def assert_postgres_would_accept(value: object) -> None:
    """Fail unless Postgres could store ``value`` as text or as jsonb.

    Both halves are real rejections, not proxies for one:
    * the driver encodes every text parameter as UTF-8, and a lone surrogate
      has no UTF-8 encoding at all;
    * a text value cannot contain a NUL, and jsonb parses the escape and then
      refuses it for the same reason - so the JSON is parsed here too, exactly
      as Postgres parses it, rather than searched for a substring.
    """
    if value is None:
        return
    assert isinstance(value, str), f"not a text parameter: {value!r}"
    value.encode("utf-8")  # raises UnicodeEncodeError on a lone surrogate
    assert NUL not in value
    try:
        parsed: object = json.loads(value)
    except ValueError:
        return  # a plain text parameter, already checked above
    for leaf in _strings(parsed):
        assert NUL not in leaf, f"jsonb would reject {leaf!r}"
        leaf.encode("utf-8")


def _strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():  # pyright: ignore[reportUnknownVariableType]
            yield from _strings(k)
            yield from _strings(v)
    elif isinstance(value, list):
        for item in value:  # pyright: ignore[reportUnknownVariableType]
            yield from _strings(item)


class FakeConn:
    """Records what the boundary actually handed the driver."""

    def __init__(self, calls: list[tuple[str, tuple[object, ...]]]) -> None:
        self._calls = calls

    async def execute(self, query: str, *args: object) -> str:
        self._calls.append((query, args))
        return "INSERT 0 1"

    async def fetchrow(self, query: str, *args: object) -> None:
        self._calls.append((query, args))
        return None

    async def fetch(self, query: str, *args: object) -> list[object]:
        self._calls.append((query, args))
        return []

    async def copy_to_table(self, table: str, **kwargs: object) -> str:
        self._calls.append((table, (kwargs.get("source"),)))
        return "COPY 1"

    def transaction(self) -> FakeTransaction:
        """The write path wraps the row and its tool-call tally in one (#1322)."""
        return FakeTransaction()


class FakeTransaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *exc: object) -> None:
        return None


class FakeAcquire:
    def __init__(self, conn: FakeConn) -> None:
        self._conn = conn

    async def __aenter__(self) -> FakeConn:
        return self._conn

    async def __aexit__(self, *exc: object) -> None:
        return None


class FakePool:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.conn = FakeConn(self.calls)

    def acquire(self) -> FakeAcquire:
        return FakeAcquire(self.conn)

    @property
    def args(self) -> tuple[object, ...]:
        """Arguments of the last call, ignoring the tool-call tally.

        Every write path also updates ``agent_tool_call_counts`` in the same
        transaction (#1322). That is a derived number, never agent text, and
        these tests are about what the row itself carries - so it is skipped
        rather than allowed to shadow the write under inspection.
        """
        for query, args in reversed(self.calls):
            if tool_call_counts.TABLE not in query:
                return args
        raise AssertionError("the boundary never wrote anything")


# --------------------------------------------------------------------------
# The sanitiser itself
# --------------------------------------------------------------------------


def test_pg_safe_removes_nul_and_lone_surrogate() -> None:
    from syn_adapters.postgres_text import pg_safe

    cleaned = pg_safe(HOSTILE)

    assert cleaned.startswith(CLEANED_PREFIX), cleaned
    assert NUL not in cleaned
    assert cleaned != CLEANED_PREFIX, (
        "a value the sanitiser changed is indistinguishable from one it did not"
    )


def test_pg_safe_recurses_into_containers() -> None:
    from syn_adapters.postgres_text import pg_safe

    cleaned = pg_safe({"k" + NUL: ["a" + NUL, {"b": "c" + LONE_SURROGATE}, 7]})

    assert isinstance(cleaned, dict)
    [(key, values)] = cleaned.items()
    assert isinstance(key, str) and key.startswith("k")
    assert isinstance(values, list)
    assert isinstance(values[0], str) and values[0].startswith("a")
    assert isinstance(values[1], dict)
    inner = values[1]["b"]
    assert isinstance(inner, str) and inner.startswith("c")
    assert values[2] == 7, "a non-string value must pass through untouched"


def test_pg_safe_keeps_the_text_that_merely_looks_like_an_escape() -> None:
    """Stripping the six-character spelling would corrupt honest agent output."""
    from syn_adapters.postgres_text import pg_safe

    assert pg_safe("a" + ESCAPE_TEXT + "b") == "a" + ESCAPE_TEXT + "b"


def test_pg_json_output_is_accepted_and_still_says_what_it_said() -> None:
    from syn_adapters.postgres_text import pg_json

    out = pg_json({"output": HOSTILE, "at": datetime(2026, 9, 16, tzinfo=UTC)})

    assert_postgres_would_accept(out)
    assert str(json.loads(out)["output"]).startswith(CLEANED_PREFIX)
    assert json.loads(out)["at"].startswith("2026-09-16")


# --------------------------------------------------------------------------
# agent_events - where captured tool output and the harness's session id land
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_insert_one_writes_storable_values() -> None:
    from syn_adapters.events.store import AgentEventStore

    store = AgentEventStore("postgresql://unused")
    store._initialized = True
    pool = FakePool()
    store.pool = pool  # type: ignore[assignment]  # FakePool records what a real pool would send

    await store.insert_one(
        {
            "event_type": "tool_completed",
            # the harness supplies its own session id, so it is untrusted too
            "session_id": "sess" + NUL + "-1",
            "output_preview": HOSTILE,
        }
    )

    for arg in pool.args:
        if isinstance(arg, str):
            assert_postgres_would_accept(arg)
    data = json.loads(str(pool.args[5]))
    assert str(data["output_preview"]).startswith(CLEANED_PREFIX), (
        "sanitised into oblivion, not stored"
    )
    # The key it was written under, asked for the same way the writer derives
    # it, rather than a literal that has to be kept in step with the policy.
    assert pool.args[2] == pg_safe("sess" + NUL + "-1")


@pytest.mark.asyncio
async def test_insert_batch_buffer_is_encodable() -> None:
    """The COPY path builds a UTF-8 buffer; a lone surrogate cannot be encoded.

    Unsanitised, this raises UnicodeEncodeError before a connection is even
    taken - the same class of failure as the NUL, on the other write path.
    """
    from syn_adapters.events.store import AgentEventStore

    store = AgentEventStore("postgresql://unused")
    store._initialized = True
    pool = FakePool()
    store.pool = pool  # type: ignore[assignment]  # see above

    count = await store.insert_batch(
        [{"event_type": "tool_completed", "session_id": "s1", "output_preview": HOSTILE}]
    )

    assert count == 1
    source = pool.args[0]
    assert source is not None
    body = source.read().decode("utf-8")  # type: ignore[union-attr]  # io.BytesIO
    assert CLEANED_PREFIX in body
    assert NUL not in body


# --------------------------------------------------------------------------
# projection records - the payload AND the key it is stored under
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_projection_save_writes_storable_key_and_payload() -> None:
    from syn_adapters.projection_stores.postgres_store import PostgresProjectionStore

    store = PostgresProjectionStore()
    pool = FakePool()
    store._pool = pool  # type: ignore[assignment]  # see above
    store._initialized_tables.add("execution_detail")

    await store.save(
        "execution_detail",
        "exec-1" + NUL,
        {"error_message": HOSTILE},
    )

    key, payload = pool.args
    assert_postgres_would_accept(key)
    assert_postgres_would_accept(payload)
    assert str(json.loads(str(payload))["error_message"]).startswith(CLEANED_PREFIX)


# --------------------------------------------------------------------------
# the conversation index - session id, model and tool names off the stream
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_conversation_index_writes_storable_values() -> None:
    from syn_adapters.conversations.minio_index import insert_index
    from syn_adapters.conversations.protocol import SessionContext

    pool = FakePool()
    context = SessionContext(
        execution_id="exec" + NUL + "-1",
        phase_id="implement",
        workflow_id="wf-1",
        event_count=2,
        total_input_tokens=1,
        total_output_tokens=1,
        tool_counts={"Bash" + NUL: 3},
        started_at=datetime(2026, 9, 16, tzinfo=UTC),
        completed_at=datetime(2026, 9, 16, tzinfo=UTC),
        model="claude" + LONE_SURROGATE,
        success=True,
    )

    await insert_index(
        pool,  # type: ignore[arg-type]  # see above
        "sess" + NUL + "-1",
        f"conversations/{pg_safe('sess' + NUL + '-1')}.jsonl",
        123,
        context,
        "syn-conversations",
    )

    for arg in pool.args:
        if isinstance(arg, str):
            assert_postgres_would_accept(arg)
    assert pool.args[0] == pg_safe("sess" + NUL + "-1")
    # The tool name carried a NUL, so its key is marked as altered rather than
    # silently becoming plain "Bash" - which would merge it with a real Bash
    # count from the same session.
    assert json.loads(str(pool.args[10])) == {pg_safe("Bash" + NUL): 3}


# --------------------------------------------------------------------------
# the import ledger - a harness-supplied id in a TEXT primary key
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_import_ledger_agrees_with_itself_about_a_hostile_session_id() -> None:
    """Write and read must normalise identically, or the ledger loses the row."""
    from syn_adapters.import_ledger import PostgresImportLedger
    from syn_domain.contexts.agent_sessions import BilledUsage

    pool = FakePool()
    ledger = PostgresImportLedger(pool)  # type: ignore[arg-type]  # see above
    hostile_id = "harness" + NUL + "-session"

    await ledger.record_billed("exec-1", hostile_id, BilledUsage(output_tokens=5))
    written = pool.args
    await ledger.already_billed("exec-1", hostile_id)
    read = pool.args

    for arg in (*written, *read):
        if isinstance(arg, str):
            assert_postgres_would_accept(arg)
    assert written[1] == read[1], "the row was written under a key the read cannot find"


# --------------------------------------------------------------------------
# agent_events again, via COPY - where the text is not refused, it is misfiled
#
# A different failure from everything above, and it needs a different fix. COPY
# text format frames a row with TAB, LF and backslash, all of which occur freely
# in agent output, so unescaped text does not fail the write the way a NUL does:
# it moves the column boundaries. pg_safe cannot help - a tab is not a codepoint
# Postgres refuses, it is the delimiter - so these tests assert on what a COPY
# PARSER makes of the row, never on what the writer put in it.
#
# The sixth boundary, the backfill script, is covered in
# scripts/tests/test_backfill_failed_session_observations.py, beside its subject.
# --------------------------------------------------------------------------

TAB = chr(9)
NEWLINE = chr(10)
BACKSLASH = chr(92)

#: Postgres' own spelling of NULL inside a COPY row.
COPY_NULL_MARKER = BACKSLASH + "N"

#: What COPY turns each backslash escape into on the way IN. Straight from the
#: COPY documentation's table, which is the whole point: a reader built from the
#: implementation under test could not catch the implementation being wrong.
_COPY_UNESCAPE = {
    "b": chr(8),
    "f": chr(12),
    "n": NEWLINE,
    "r": chr(13),
    "t": TAB,
    "v": chr(11),
    BACKSLASH: BACKSLASH,
}


def read_copy_row(row: str) -> list[str | None]:
    """Parse one COPY text-format row the way Postgres parses it.

    Fails if the text is not exactly one row - an unescaped newline in a field
    ends the row early, which is the same defect as an unescaped tab one axis
    over and is just as invisible to a writer-side assertion.

    Numeric (``\\xHH``, ``\\ooo``) escapes are not decoded: nothing in this
    system emits them, and a literal one in agent text survives as itself.
    """
    assert row.endswith(NEWLINE), "a COPY row ends with the row terminator"
    body = row[:-1]
    assert NEWLINE not in body, f"{body.count(NEWLINE) + 1} rows, not one: {row!r}"
    return [None if raw == COPY_NULL_MARKER else _unescape(raw) for raw in _split_fields(body)]


def _split_fields(body: str) -> list[str]:
    """Split on TABs that are not themselves escaped - COPY's column boundaries."""
    fields: list[str] = []
    current: list[str] = []
    i = 0
    while i < len(body):
        char = body[i]
        if char == BACKSLASH and i + 1 < len(body):
            current.append(body[i : i + 2])
            i += 2
        elif char == TAB:
            fields.append("".join(current))
            current = []
            i += 1
        else:
            current.append(char)
            i += 1
    fields.append("".join(current))
    return fields


def _unescape(raw: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(raw):
        if raw[i] != BACKSLASH:
            out.append(raw[i])
            i += 1
            continue
        following = raw[i + 1] if i + 1 < len(raw) else ""
        # "Any other backslashed character represents itself" - so an unescaped
        # writer does not merely mangle the escapes it meant, it eats the rest.
        out.append(_COPY_UNESCAPE.get(following, following))
        i += 2
    return "".join(out)


def copy_row_for(**event: object) -> list[str | None]:
    """Run one event through the real batch path and read the row back.

    Goes through ``_build_copy_buffer``, which is what ``insert_batch`` hands to
    the driver - not through the row builder alone, so a value corrected and
    then dropped by the buffer would still be caught.
    """
    from syn_adapters.events.store_helpers import _build_copy_buffer

    payload = _build_copy_buffer([event], None, None)  # type: ignore[list-item]  # an event payload is arbitrary agent JSON
    return read_copy_row(payload.buffer.read().decode("utf-8"))


#: Column order of the COPY, from store_write.insert_batch.
TIME, EVENT_TYPE, SESSION_ID, EXECUTION_ID, PHASE_ID, DATA = range(6)


def test_the_copy_reader_sees_an_unescaped_tab_as_an_extra_column() -> None:
    """The reader must be able to fail, or every test below is vacuous."""
    with pytest.raises(AssertionError):
        read_copy_row("a" + NEWLINE + "b" + NEWLINE)
    assert read_copy_row("a" + TAB + "b" + NEWLINE) == ["a", "b"]
    assert len(read_copy_row("a" + TAB + "b" + TAB + "c" + NEWLINE)) == 3


@pytest.mark.parametrize(
    ("label", "hostile_id"),
    [
        ("tab is the column delimiter", "sess" + TAB + "abc"),
        ("newline is the row terminator", "sess" + NEWLINE + "abc"),
        ("backslash is the escape character", "sess" + BACKSLASH + "abc"),
        ("all three at once", "s" + TAB + BACKSLASH + NEWLINE + "1"),
    ],
)
def test_framing_characters_in_a_session_id_stay_inside_their_column(
    label: str, hostile_id: str
) -> None:
    """The harness supplies its own session id and can put anything in it.

    Unescaped, the tab case desyncs the row to seven columns against six
    declared ones ("COPY field count: 7 (expected 6)"), and the backslash case
    does not even do that - it lands a quietly different string in the right
    column, which nothing downstream can detect.
    """
    fields = copy_row_for(event_type="tool_completed", session_id=hostile_id, detail="ok")

    assert len(fields) == 6, f"{label}: row desynced to {len(fields)} columns"
    assert fields[SESSION_ID] == hostile_id, f"{label}: stored as something else"


def test_a_backslash_in_tool_output_is_not_eaten_before_jsonb_sees_it() -> None:
    """JSON's own escapes are made of the character COPY escapes with.

    ``C:\\temp`` is written by json.dumps as the four characters ``C:\\\\t``...,
    and COPY reads ``\\\\`` as one backslash, handing the jsonb parser
    ``"C:\\temp"`` - which it reads as C, colon, TAB. The write succeeds and the
    stored value is wrong. A newline is worse still: COPY hands jsonb a raw
    control character inside a string literal and the whole batch is rejected.
    """
    windows_path = "C:" + BACKSLASH + "temp"
    multiline = "line1" + NEWLINE + "line2" + TAB + "tail"

    fields = copy_row_for(
        event_type="tool_completed",
        session_id="s1",
        path=windows_path,
        stdout=multiline,
    )

    assert len(fields) == 6
    payload = fields[DATA]
    assert payload is not None
    data = json.loads(payload)  # exactly what the jsonb parser is handed
    assert data["path"] == windows_path
    assert data["stdout"] == multiline


def test_a_missing_execution_id_is_null_and_a_literal_one_is_text() -> None:
    """``\\N`` means NULL; agent text that spells it must not.

    The two are the same six characters on the wire and only the escaping tells
    them apart, so a writer that emits the marker by hand cannot express the
    difference at all.
    """
    absent = copy_row_for(event_type="tool_completed", session_id="s1")
    assert absent[EXECUTION_ID] is None
    assert absent[PHASE_ID] is None

    spelled = copy_row_for(
        event_type="tool_completed",
        session_id=COPY_NULL_MARKER,
        execution_id=COPY_NULL_MARKER,
    )
    assert spelled[SESSION_ID] == COPY_NULL_MARKER, "text became NULL"
    assert spelled[EXECUTION_ID] == COPY_NULL_MARKER, "text became NULL"


def test_the_copy_path_answers_both_questions_at_once() -> None:
    """Unstorable codepoints AND framing, on one row, neither fixing the other."""
    fields = copy_row_for(
        event_type="tool_completed",
        session_id="sess" + NUL + TAB + "1",
        output_preview=HOSTILE + BACKSLASH + NEWLINE,
    )

    assert len(fields) == 6
    assert fields[SESSION_ID] == pg_safe("sess" + NUL + TAB + "1"), (
        "the NUL went, the tab stayed put"
    )
    assert fields[SESSION_ID].startswith("sess" + TAB + "1"), (
        "the tab is storable and must survive untouched in the readable part"
    )
    payload = fields[DATA]
    assert payload is not None
    assert_postgres_would_accept(payload)
    preview = str(json.loads(payload)["output_preview"])
    assert preview.startswith(CLEANED_PREFIX)
    # The ordinary characters after the hostile ones are untouched. The marker
    # goes on the END of the whole value, so the readable text - backslash and
    # newline included - sits in front of it, not behind.
    assert preview.startswith(CLEANED_PREFIX + BACKSLASH + NEWLINE)


@pytest.mark.asyncio
async def test_projection_read_asks_for_the_key_the_write_stored() -> None:
    """Sanitising only the write side loses the row (#1241).

    ``save`` normalised the key and ``get``/``delete``/``get_by_prefix`` did
    not, so a projection written under a hostile session id was stored under one
    name and looked up under another. This is the failure the import ledger is
    already guarded against, one store over - and ``delete`` is the worst of the
    three, because matching no rows is indistinguishable from having deleted
    them.
    """
    from syn_adapters.projection_stores.postgres_store import PostgresProjectionStore

    store = PostgresProjectionStore()
    pool = FakePool()
    store._pool = pool  # type: ignore[assignment]  # see above
    store._initialized_tables.add("session_detail")
    hostile_key = "sess" + NUL + "-1"

    await store.save("session_detail", hostile_key, {"error_message": HOSTILE})
    written = pool.args[0]
    await store.get("session_detail", hostile_key)
    read = pool.args[0]
    await store.delete("session_detail", hostile_key)
    deleted = pool.args[0]
    await store.get_by_prefix("session_detail", hostile_key)
    scanned = pool.args[0]

    for value in (written, read, deleted, scanned):
        assert_postgres_would_accept(value)
    assert read == written, "the row was written under a key the read cannot find"
    assert deleted == written, "the delete matched nothing and said nothing"
    assert scanned == written, "the prefix scan cannot see what was written"


@pytest.mark.asyncio
async def test_agent_events_are_queried_under_the_id_they_were_stored_under() -> None:
    """insert_one normalises the ids; the queries that serve them must agree.

    A session whose id carried a NUL is written, and then every dashboard, cost
    query and conversation view asks for it by the id the harness reported -
    which is not the id it is filed under. The events exist and nothing can
    reach them, so the session reads as having produced no telemetry at all.
    """
    from syn_adapters.events.queries import query_execution_events, query_session_events
    from syn_adapters.events.store import AgentEventStore

    store = AgentEventStore("postgresql://unused")
    store._initialized = True
    pool = FakePool()
    store.pool = pool  # type: ignore[assignment]  # see above
    hostile_session = "sess" + NUL + "-1"
    hostile_execution = "exec" + LONE_SURROGATE + "-1"

    await store.insert_one(
        {
            "event_type": "tool_completed",
            "session_id": hostile_session,
            "execution_id": hostile_execution,
        }
    )
    stored_session, stored_execution = pool.args[2], pool.args[3]

    await query_session_events(pool, hostile_session)  # type: ignore[arg-type]  # see above
    queried_session = pool.args[0]
    await query_execution_events(pool, hostile_execution)  # type: ignore[arg-type]  # see above
    queried_execution = pool.args[0]

    for value in (stored_session, stored_execution, queried_session, queried_execution):
        assert_postgres_would_accept(value)
    assert queried_session == stored_session, "the query cannot reach the events"
    assert queried_execution == stored_execution, "the query cannot reach the events"


@pytest.mark.asyncio
async def test_conversation_index_is_read_under_the_id_it_was_written_under() -> None:
    """Same asymmetry, the store that points at the transcript in object storage."""
    from syn_adapters.conversations.minio_index import (
        get_session_metadata,
        list_sessions_for_execution,
    )

    pool = FakePool()
    hostile_session = "sess" + NUL + "-1"
    hostile_execution = "exec" + NUL + "-1"

    await get_session_metadata(pool, hostile_session)  # type: ignore[arg-type]  # see above
    looked_up = pool.args[0]
    await list_sessions_for_execution(pool, hostile_execution)  # type: ignore[arg-type]  # see above
    listed = pool.args[0]

    for value in (looked_up, listed):
        assert_postgres_would_accept(value)
    # insert_index stores pg_safe(session_id); these must ask for the same thing.
    assert looked_up == pg_safe("sess" + NUL + "-1"), (
        "the transcript is filed under a name this cannot ask for"
    )
    assert listed == pg_safe("exec" + NUL + "-1"), "the execution's conversations are unreachable"
