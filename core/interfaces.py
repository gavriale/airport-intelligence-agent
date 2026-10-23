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
    input_tokens: int = 0  # everything sent, including parts served from the prompt cache
    output_tokens: int = 0
    cache_read_tokens: int = 0  # part of input_tokens read from the cache
    cache_write_tokens: int = 0  # part of input_tokens written to the cache


class LLMProvider(Protocol):
    async def complete(
        self, system: str, messages: list[Message], tools: list[ToolSpec]
    ) -> LLMResponse: ...


class SessionStore(Protocol):
    async def get_or_create(self, session_id: str) -> Session: ...

    async def save(self, session: Session) -> None: ...
