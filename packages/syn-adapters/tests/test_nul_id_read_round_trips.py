"""Read back what you wrote, with an id Postgres cannot store verbatim (#1241).

Every fix in this issue has the same shape and so does every regression: a
WRITE lands under the sanitised spelling of an id, a READ asks for the raw
one, and the answer is an empty result that is indistinguishable from "this
was never recorded". Nothing raises. Nobody is paged.

A write-only test cannot catch that - it asserts the value handed to the
driver is storable and stops, which is true of both the fixed and the broken
version of every reader here. So each test below does a ROUND TRIP: it puts a
record in a store keyed the way production keys it, then asks a real reader
for it using the id as an outside caller holds it, and fails when the reader
comes back empty.

The doubles deliberately know one thing only - the SPELLING of the id they
hold. They are not SQL engines; they are the sentence "the row is there, under
the name the writer used", which is the whole content of this bug.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.projection_stores.postgres_store import PostgresProjectionStore

pytestmark = pytest.mark.unit

#: One column value as a driver would hand it back. Spelled out rather than
#: left open: an erased row type is what the untyped-dicts ratchet counts, in
#: test files too.
type _Cell = str | int | datetime | dict[str, str] | None

# Written via chr() so no editor or formatter can turn the real codepoint into
# its harmless six-character spelling - the near-miss that certifies this class
# closed while it is open.
NUL = chr(0)
LONE_SURROGATE = chr(0xDEAD)

#: The id as a harness hands it to us.
RAW_ID = "sess-" + NUL + "abc" + LONE_SURROGATE + "def"
#: ...and the only spelling Postgres can hold, which is therefore the only
#: spelling any stored row is keyed by.
STORED_ID = "sess-abcdef"


def test_the_two_spellings_differ() -> None:
    """Guards every assertion below: if these were equal, nothing is tested."""
    from syn_adapters.postgres_text import pg_safe

    assert RAW_ID != STORED_ID
    assert pg_safe(RAW_ID) == STORED_ID


# --- Class 1: the projection store, Postgres ---------------------------------


class _ProjectionTable:
    """A projection table that stores rows under the key it was given.

    Understands the four statements the store actually issues - insert, get by
    id, prefix scan, filtered query - and nothing else. DDL is accepted and
    ignored, as Postgres would.
    """

    def __init__(self) -> None:
        self.rows: dict[str, str] = {}

    async def execute(self, query: str, *args: object) -> str:
        if "INSERT INTO" in query:
            key, data = args[0], args[1]
            assert isinstance(key, str) and isinstance(data, str)
            self.rows[key] = data
            return "INSERT 0 1"
        if "DELETE FROM" in query and "WHERE id" in query:
            key = args[0]
            assert isinstance(key, str)
            self.rows.pop(key, None)
            return "DELETE 1"
        return "CREATE"

    async def fetchrow(self, query: str, *args: object) -> dict[str, _Cell] | None:
        assert "WHERE id = $1" in query
        key = args[0]
        assert isinstance(key, str)
        data = self.rows.get(key)
        return None if data is None else {"data": data}

    async def fetch(self, query: str, *args: object) -> list[dict[str, _Cell]]:
        if "LIKE" in query:
            prefix = args[0]
            assert isinstance(prefix, str)
            return [{"id": k, "data": v} for k, v in self.rows.items() if k.startswith(prefix)]
        return [{"data": v} for v in self.rows.values() if _matches(query, v, args)]

    async def fetchval(self, query: str, *args: object) -> int:
        return len([v for v in self.rows.values() if _matches(query, v, args)])


def _matches(query: str, data_json: str, args: tuple[object, ...]) -> bool:
    """Compare a bound filter value against the stored document, as ``->>`` does."""
    field = query.split("data->>'", 1)[1].split("'", 1)[0]
    stored = json.loads(data_json).get(field)
    wanted = args[0]
    values = wanted if isinstance(wanted, list) else [wanted]
    return any(str(stored) == v for v in values)


class _Acquire[ConnT]:
    def __init__(self, conn: ConnT) -> None:
        self._conn = conn

    async def __aenter__(self) -> ConnT:
        return self._conn

    async def __aexit__(self, *_exc: object) -> bool:
        return False


class _Pool[ConnT]:
    def __init__(self, conn: ConnT) -> None:
        self.conn = conn

    def acquire(self) -> _Acquire[ConnT]:
        return _Acquire(self.conn)


def _postgres_store() -> PostgresProjectionStore:
    return PostgresProjectionStore(_Pool(_ProjectionTable()))  # type: ignore[arg-type]


async def test_postgres_projection_store_reads_back_a_nul_bearing_key() -> None:
    store = _postgres_store()

    await store.save("sessions", RAW_ID, {"session_id": RAW_ID, "n": 1})

    assert await store.get("sessions", RAW_ID) is not None
    assert await store.get("sessions", STORED_ID) is not None


async def test_postgres_projection_store_filters_on_a_nul_bearing_value() -> None:
    """The filter path, which is the one a dashboard read goes through."""
    store = _postgres_store()
    await store.save("sessions", RAW_ID, {"session_id": RAW_ID, "n": 1})

    assert len(await store.query("sessions", filters={"session_id": RAW_ID})) == 1
    assert await store.count("sessions", filters={"session_id": RAW_ID}) == 1
    assert len(await store.query("sessions", filters={"session_id": [RAW_ID, "other"]})) == 1


async def test_postgres_prefix_resolve_returns_the_id_as_stored() -> None:
    """A resolved id is bound by the NEXT reader, so it must be the stored one."""
    from syn_adapters.projection_stores.prefix_match import resolve_by_prefix

    store = _postgres_store()
    await store.save("sessions", RAW_ID, {"session_id": RAW_ID})

    result = await resolve_by_prefix(store, "sessions", RAW_ID)

    assert result.full_id == STORED_ID


async def test_postgres_projection_store_deletes_the_row_it_wrote() -> None:
    store = _postgres_store()
    await store.save("sessions", RAW_ID, {"session_id": RAW_ID})

    await store.delete("sessions", RAW_ID)

    assert await store.get("sessions", STORED_ID) is None


# --- Class 2: the projection store, in-memory --------------------------------
#
# ADR-060 lets this run for real in offline mode, but the reason it is tested
# here is narrower: a double that stores the RAW id is self-consistent and so
# passes its own tests, while pinning the opposite of production behaviour.
# Any test written against it would then certify a reader this issue breaks.


def _memory_store() -> InMemoryProjectionStore:
    return InMemoryProjectionStore()


async def test_memory_projection_store_reads_back_a_nul_bearing_key() -> None:
    store = _memory_store()
    await store.save("sessions", RAW_ID, {"session_id": RAW_ID})

    assert await store.get("sessions", RAW_ID) is not None
    assert await store.get("sessions", STORED_ID) is not None


async def test_memory_projection_store_filters_on_a_nul_bearing_value() -> None:
    store = _memory_store()
    await store.save("sessions", RAW_ID, {"session_id": RAW_ID})

    assert len(await store.query("sessions", filters={"session_id": RAW_ID})) == 1
    assert await store.count("sessions", filters={"session_id": RAW_ID}) == 1


async def test_memory_prefix_resolve_returns_the_id_as_stored() -> None:
    from syn_adapters.projection_stores.prefix_match import resolve_by_prefix

    store = _memory_store()
    await store.save("sessions", RAW_ID, {"session_id": RAW_ID})

    assert (await resolve_by_prefix(store, "sessions", RAW_ID)).full_id == STORED_ID


async def test_the_two_stores_agree_about_what_they_hold() -> None:
    """Whatever the spelling is, it must be the SAME one in both stores."""
    memory, postgres = _memory_store(), _postgres_store()
    await memory.save("sessions", RAW_ID, {"session_id": RAW_ID})
    await postgres.save("sessions", RAW_ID, {"session_id": RAW_ID})

    assert list(memory._data["sessions"]) == list(postgres._pool.conn.rows)


# --- Class 3: the agent_events readers ---------------------------------------


class _AgentEventsTable:
    """Rows keyed by the id ``AgentEvent`` sanitised on the way in.

    Answers any query with its rows when the bound parameters carry that id,
    and with nothing when they do not - which is precisely what Postgres does
    for a ``WHERE session_id = $1`` that asks for a name no row has.
    """

    def __init__(self, stored_id: str, rows: list[dict[str, _Cell]]) -> None:
        self._stored_id = stored_id
        self._rows = rows
        self.binds: list[tuple[object, ...]] = []

    def _asked_for_stored_id(self, args: tuple[object, ...]) -> bool:
        for arg in args:
            if arg == self._stored_id:
                return True
            if isinstance(arg, (list, tuple)) and self._stored_id in arg:
                return True
        return False

    async def fetch(self, _query: str, *args: object) -> list[dict[str, _Cell]]:
        self.binds.append(args)
        return self._rows if self._asked_for_stored_id(args) else []

    async def fetchrow(self, query: str, *args: object) -> dict[str, _Cell] | None:
        rows = await self.fetch(query, *args)
        return rows[0] if rows else None

    async def fetchval(self, query: str, *args: object) -> object:
        row = await self.fetchrow(query, *args)
        return None if row is None else next(iter(row.values()))


def _agent_events(rows: list[dict[str, _Cell]]) -> _Pool[_AgentEventsTable]:
    return _Pool(_AgentEventsTable(STORED_ID, rows))


def _tool_row() -> dict[str, _Cell]:
    return {
        "event_type": "tool_execution_completed",
        "time": datetime(2026, 9, 17, 12, 0, tzinfo=UTC),
        "data": {"tool_name": "Bash", "tool_use_id": "t1", "session_id": STORED_ID},
    }


def _stored_id_from_a_real_write() -> str:
    """The stored spelling, taken from the writer rather than hard-coded."""
    from syn_adapters.events.models import AgentEvent

    event = AgentEvent(event_type="tool_execution_completed", session_id=RAW_ID)
    assert event.session_id == STORED_ID
    return STORED_ID


async def test_session_tools_reads_back_a_session_written_with_a_nul_id() -> None:
    from syn_adapters.projections.session_tools import SessionToolsProjection
    from syn_adapters.projections.session_tools_helpers import get_session_tools

    assert _stored_id_from_a_real_write() == STORED_ID
    proj = SessionToolsProjection(pool=_agent_events([_tool_row()]))  # type: ignore[arg-type]

    ops = await get_session_tools(
        proj,
        RAW_ID,
        timeline_exclude=(),
        tool_execution_started="tool_execution_started",
        tool_execution_completed="tool_execution_completed",
        subagent_tool_names=set(),
        git_event_types=(),
    )

    assert len(ops) == 1


async def test_query_session_tools_reads_back_ids_written_with_a_nul() -> None:
    from syn_adapters.projections.session_tools import SessionToolsProjection
    from syn_adapters.projections.session_tools_queries import query_session_tools

    proj = SessionToolsProjection(pool=_agent_events([_tool_row()]))  # type: ignore[arg-type]

    by_execution = await query_session_tools(proj, (), set(), (), execution_id=RAW_ID)
    by_phase = await query_session_tools(proj, (), set(), (), phase_id=RAW_ID)

    assert len(by_execution) == 1
    assert len(by_phase) == 1


# --- Class 4: the durable import ledger --------------------------------------


class _LedgerTable:
    """The ledger row, keyed by the composite primary key as written."""

    def __init__(self) -> None:
        self.rows: dict[tuple[object, object], dict[str, int]] = {}

    async def execute(self, query: str, *args: object) -> str:
        if "INSERT INTO delegate_import_ledger" in query:
            self.rows[(args[0], args[1])] = {
                "uncached_input_tokens": int(args[2]),  # type: ignore[arg-type]
                "cache_read_tokens": int(args[3]),  # type: ignore[arg-type]
                "cache_creation_tokens": int(args[4]),  # type: ignore[arg-type]
                "output_tokens": int(args[5]),  # type: ignore[arg-type]
            }
        return "OK"

    async def fetchrow(self, _query: str, *args: object) -> dict[str, int] | None:
        return self.rows.get((args[0], args[1]))


async def test_import_ledger_reads_back_a_mark_written_with_a_nul_id() -> None:
    """The importer holds the harness's raw id; a later reader holds the stored one.

    Billing the difference against a mark of zero re-bills work already paid
    for, so a lookup that misses is not a blank screen here - it is money.
    """
    from syn_adapters.import_ledger.postgres_ledger import PostgresImportLedger
    from syn_domain.contexts.agent_sessions import BilledUsage

    ledger = PostgresImportLedger(_Pool(_LedgerTable()))  # type: ignore[arg-type]
    ledger._table_created = True

    await ledger.record_billed(RAW_ID, RAW_ID, BilledUsage(uncached_input_tokens=1_000))
    mark = await ledger.already_billed(STORED_ID, STORED_ID)

    assert mark.uncached_input_tokens == 1_000


# --- Class 5: object storage keys --------------------------------------------


class _FakeStorage:
    """Just a dict of keys, which is all an object store is for this bug."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def upload(
        self,
        key: str,
        content: bytes,
        *,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> object:
        self.objects[key] = content
        return key

    async def download(self, key: str) -> bytes:
        from syn_adapters.object_storage.protocol import ObjectNotFoundError

        if key not in self.objects:
            raise ObjectNotFoundError(key)
        return self.objects[key]


async def test_bundle_uploaded_under_a_raw_id_loads_under_the_stored_one() -> None:
    """The upload knows the harness's id; the download reads it out of Postgres.

    Same desync this issue already closed between MinIO and Postgres for
    conversations: two spellings, one object, and a bundle that uploaded
    successfully reports as never written.
    """
    from syn_adapters.artifacts.bundle import ArtifactBundle

    storage = _FakeStorage()
    bundle = ArtifactBundle(bundle_id="b1", phase_id="verify", session_id=RAW_ID)
    await bundle.save_to_storage(storage)  # type: ignore[arg-type]

    loaded = await ArtifactBundle.load_from_storage(
        storage,  # type: ignore[arg-type]
        "b1",
        session_id=STORED_ID,
    )

    assert loaded.bundle_id == "b1"
