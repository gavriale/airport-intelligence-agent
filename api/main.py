"""FastAPI app. Stateless: all conversation state goes through the SessionStore."""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi import Path as PathParam
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.container import Container, build_container
from app.settings import Settings
from core.errors import ToolExecutionError
from core.logging import configure_logging, correlation_id

MAX_MESSAGE_CHARS = 2000
MAX_SESSION_ID_CHARS = 64
NO_API_KEY_MESSAGE = "Set ANTHROPIC_API_KEY to chat; GET /ranking works without it."
CHAT_PAGE = Path(__file__).resolve().parent / "static" / "index.html"


class ChatRequest(BaseModel):
    session_id: str | None = Field(default=None, max_length=MAX_SESSION_ID_CHARS)
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


class VisibleMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    failed: bool


def create_app(container: Container | None = None) -> FastAPI:
    """Pass a container in tests; otherwise one is built from settings at startup."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owned = container is None
        if owned:
            settings = Settings()
            configure_logging(settings.log_format)
            app.state.container = await build_container(settings)
        else:
            configure_logging()
            app.state.container = container
        try:
            yield
        finally:
            if owned:
                await app.state.container.close()

    app = FastAPI(title="Airport investment analyst", lifespan=lifespan)
    if container is not None:
        app.state.container = container

    @app.get("/", include_in_schema=False)
    async def chat_page() -> FileResponse:
        return FileResponse(CHAT_PAGE)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ranking")
    async def ranking(
        region: str | None = None,
        state: Annotated[list[str] | None, Query()] = None,
        top_n: Annotated[int, Query(ge=1, le=50)] = 10,
    ) -> dict:
        """The deterministic Expansion Pressure ranking. No model involved, so no API key needed."""
        try:
            return await app.state.container.analytics.rank(region, state, top_n, None)
        except ToolExecutionError as exc:
            raise HTTPException(400, detail={"code": exc.code, "message": exc.message}) from exc

    @app.post("/chat", response_model=ChatResponse)
    async def chat(request: ChatRequest) -> ChatResponse:
        if app.state.container.agent is None:
            raise HTTPException(503, detail=NO_API_KEY_MESSAGE)
        correlation_id.set(str(uuid.uuid4()))
        # Server-generated IDs are unguessable; a real deployment binds them to an auth token.
        session_id = request.session_id or str(uuid.uuid4())
        result = await app.state.container.agent.run_turn(session_id, request.message)
        return ChatResponse(
            session_id=session_id,
            reply=result.reply,
            failed=result.failed,
        )

    @app.get("/sessions/{session_id}/messages", response_model=list[VisibleMessage])
    async def session_messages(
        session_id: Annotated[str, PathParam(max_length=MAX_SESSION_ID_CHARS)],
    ) -> list[VisibleMessage]:
        """What the chat page shows after a refresh: the user's messages and the final answers.
        Tool requests, tool results and text that came with a tool request stay hidden.
        An unknown id is an empty list. The session id is the only secret (no login yet)."""
        session = await app.state.container.sessions.get_or_create(session_id)
        return [
            VisibleMessage(role=m.role, content=m.content)
            for m in session.messages
            if m.content and not m.tool_calls and not m.tool_results
        ]

    return app


def app_factory() -> FastAPI:
    return create_app()
