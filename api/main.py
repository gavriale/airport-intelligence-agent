"""FastAPI app. Stateless: all conversation state goes through the SessionStore."""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.container import Container, build_container
from app.settings import Settings
from core.logging import configure_logging, correlation_id

MAX_MESSAGE_CHARS = 2000
CHAT_PAGE = Path(__file__).resolve().parent / "static" / "index.html"


class ChatRequest(BaseModel):
    session_id: str | None = Field(default=None, max_length=64)
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


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

    app = FastAPI(title="Customer-service agent", lifespan=lifespan)
    if container is not None:
        app.state.container = container

    @app.get("/", include_in_schema=False)
    async def chat_page() -> FileResponse:
        return FileResponse(CHAT_PAGE)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/chat", response_model=ChatResponse)
    async def chat(request: ChatRequest) -> ChatResponse:
        correlation_id.set(str(uuid.uuid4()))
        # Server-generated IDs are unguessable; a real deployment binds them to an auth token.
        session_id = request.session_id or str(uuid.uuid4())
        result = await app.state.container.agent.run_turn(session_id, request.message)
        return ChatResponse(
            session_id=session_id,
            reply=result.reply,
            failed=result.failed,
        )

    return app


def app_factory() -> FastAPI:
    return create_app()
