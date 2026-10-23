from core.session import Session


class MemorySessionStore:
    """Per-process dict, for unit tests, the CLI and evals. The API uses PostgresSessionStore."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    async def get_or_create(self, session_id: str) -> Session:
        session = self._sessions.get(session_id)
        if session is None:
            session = Session(id=session_id)
            self._sessions[session_id] = session
        return session

    async def save(self, session: Session) -> None:
        self._sessions[session.id] = session
