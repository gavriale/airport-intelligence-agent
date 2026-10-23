"""Session stores: one contract for both implementations, plus Postgres-only durability tests.

The in-memory store always runs. The Postgres one runs when a database is reachable (see
tests/test_repository.py) and is skipped otherwise.
"""

import uuid

import pytest

from adapters.memory_session_store import MemorySessionStore
from adapters.postgres_repository import PostgresRepository
from adapters.postgres_session_store import (
    PostgresSessionStore,
    messages_from_json,
    messages_to_json,
)
from core.interfaces import Message, ToolCall, ToolResult
from core.session import Session
from tests.test_repository import DATA, DSN, SCHEMA, connect_postgres, tiny_snapshot


def conversation() -> list[Message]:
    """Text, parallel tool calls with nested arguments, results (one an error), a final answer."""
    return [
        Message(role="user", content="Compare LA and Santa Ana, city of São Paulo?"),
        Message(
            role="assistant",
            content="Let me look.",
            tool_calls=[
                ToolCall(
                    id="toolu_1", name="search_airports", arguments={"query": "LA", "limit": 5}
                ),
                ToolCall(
                    id="toolu_2",
                    name="rank_airports",
                    arguments={"weights": {"growth": 0.6, "peak": 0.0}, "states": ["CA", "ME"]},
                ),
            ],
        ),
        Message(
            role="user",
            tool_results=[
                ToolResult(tool_call_id="toolu_1", content='{"matches": [{"iata": "LAX"}]}'),
                ToolResult(
                    tool_call_id="toolu_2", content='{"error": {"code": "x"}}', is_error=True
                ),
            ],
        ),
        Message(role="assistant", content="LAX is busier."),
    ]


def new_session() -> Session:
    return Session(id=str(uuid.uuid4()), messages=conversation())


async def delete_session(pool, session_id: str) -> None:
    await pool.execute("DELETE FROM sessions WHERE session_id = $1", session_id)


@pytest.fixture(params=["memory", "postgres"])
async def store(request):
    if request.param == "memory":
        yield MemorySessionStore()
        return
    repository = await connect_postgres()
    store = PostgresSessionStore(repository.pool)
    created: list[str] = []
    original_save = store.save

    async def tracking_save(session: Session) -> None:
        created.append(session.id)
        await original_save(session)

    store.save = tracking_save
    yield store
    for session_id in created:
        await delete_session(repository.pool, session_id)
    await repository.close()


# ---------- serialization ----------


def test_messages_round_trip_through_json_with_nothing_lost():
    messages = conversation()

    assert messages_from_json(messages_to_json(messages)) == messages


# ---------- the contract, for both implementations ----------


async def test_an_unknown_id_is_an_empty_session(store):
    session = await store.get_or_create(str(uuid.uuid4()))

    assert session.messages == []


async def test_a_saved_session_loads_back_equal(store):
    session = new_session()
    await store.save(session)

    assert await store.get_or_create(session.id) == session


async def test_saving_again_replaces_the_messages(store):
    session = new_session()
    await store.save(session)
    session.messages = [*session.messages, Message(role="user", content="and Boston?")]
    await store.save(session)

    loaded = await store.get_or_create(session.id)
    assert loaded.messages == session.messages
    assert len(loaded.messages) == 5


async def test_sessions_are_independent(store):
    first, second = new_session(), new_session()
    second.messages = [Message(role="user", content="hello")]
    await store.save(first)
    await store.save(second)

    assert (await store.get_or_create(first.id)).messages == conversation()
    assert (await store.get_or_create(second.id)).messages == second.messages


# ---------- Postgres only: durability ----------


async def test_a_new_store_instance_on_the_same_database_sees_the_session():
    first_pool = await PostgresRepository.connect(DSN)
    await first_pool.load_snapshot(SCHEMA, DATA)
    session = new_session()
    await PostgresSessionStore(first_pool.pool).save(session)
    await first_pool.close()  # the "restart": the first connection pool is gone

    second_pool = await PostgresRepository.connect(DSN)
    try:
        loaded = await PostgresSessionStore(second_pool.pool).get_or_create(session.id)
        assert loaded == session
    finally:
        await delete_session(second_pool.pool, session.id)
        await second_pool.close()


async def test_reloading_the_airport_snapshot_does_not_touch_sessions(tmp_path):
    repository = await connect_postgres()
    store = PostgresSessionStore(repository.pool)
    session = new_session()
    await store.save(session)
    try:
        assert await repository.load_snapshot(SCHEMA, tiny_snapshot(tmp_path)) is True  # TRUNCATEs
        assert await store.get_or_create(session.id) == session
    finally:
        await repository.load_snapshot(SCHEMA, DATA)  # restore the real snapshot
        await delete_session(repository.pool, session.id)
        await repository.close()
