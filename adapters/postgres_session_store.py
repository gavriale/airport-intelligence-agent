import json

import asyncpg

from core.interfaces import Message
from core.session import Session

_GET_SQL = "SELECT messages FROM sessions WHERE session_id = $1"
_UPSERT_SQL = """
INSERT INTO sessions (session_id, messages) VALUES ($1, $2::jsonb)
ON CONFLICT (session_id) DO UPDATE SET messages = EXCLUDED.messages, updated_at = now()
"""


def messages_to_json(messages: list[Message]) -> str:
    return json.dumps([m.model_dump(mode="json") for m in messages], ensure_ascii=False)


def messages_from_json(text: str) -> list[Message]:
    return [Message.model_validate(m) for m in json.loads(text)]


class PostgresSessionStore:
    """Sessions in the `sessions` table (created by schema.sql), so they survive a restart and
    are shared by every API replica. An unknown id is an empty session, saved on first `save`.
    Concurrent turns on one session: the last write wins."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def get_or_create(self, session_id: str) -> Session:
        stored = await self._pool.fetchval(_GET_SQL, session_id)
        if stored is None:
            return Session(id=session_id)
        return Session(id=session_id, messages=messages_from_json(stored))

    async def save(self, session: Session) -> None:
        await self._pool.execute(_UPSERT_SQL, session.id, messages_to_json(session.messages))
