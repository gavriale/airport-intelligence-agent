"""Ports: the only things `core/` knows about the outside world.

Concrete implementations live in `adapters/` and are wired in `app/container.py`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, Protocol

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from core.session import Session


class ToolSpec(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]


class ToolResult(BaseModel):
    tool_call_id: str
    content: str
    is_error: bool = False


class Message(BaseModel):
    """Provider-neutral message. An assistant message may carry tool calls; the user message
    that follows carries the matching results."""

    role: Literal["user", "assistant"]
    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)


class LLMResponse(BaseModel):
    text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


class KnowledgeHit(BaseModel):
    doc_id: str
    title: str
    text: str
    score: float


class LLMProvider(Protocol):
    async def complete(
        self, system: str, messages: list[Message], tools: list[ToolSpec]
    ) -> LLMResponse: ...


class SessionStore(Protocol):
    async def get_or_create(self, session_id: str) -> Session: ...

    async def save(self, session: Session) -> None: ...


class DataRepository(Protocol):
    """What core needs from the client's backend: checking who the customer is.

    Domain tools use a richer repository (see `domain/tools.py`) that extends this."""

    async def verify_identity(self, customer_id: str, secret: str) -> bool: ...


class KnowledgeIndex(Protocol):
    async def search(self, query: str, k: int = 3) -> list[KnowledgeHit]: ...
