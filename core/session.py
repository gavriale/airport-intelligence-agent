"""Conversation state: the message history, including tool calls and results."""

from pydantic import BaseModel, Field

from core.interfaces import Message


class Session(BaseModel):
    id: str
    messages: list[Message] = Field(default_factory=list)
