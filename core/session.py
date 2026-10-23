"""Conversation state, including who the customer has proven they are."""

from typing import Any

from pydantic import BaseModel, Field

from core.errors import IdentityNotVerified
from core.interfaces import Message


class PendingAction(BaseModel):
    """A write the model proposed and the user has not yet confirmed."""

    tool: str
    arguments: dict[str, Any]
    idempotency_key: str
    turn: int


class Handoff(BaseModel):
    """Structured summary passed to the human agent."""

    reason: str
    summary: str
    customer_id: str | None
    verified: bool
    failed_verifications: int
    turns: int


class Session(BaseModel):
    id: str
    messages: list[Message] = Field(default_factory=list)
    turn: int = 0
    verified_customer_id: str | None = None
    failed_verifications: int = 0
    pending_action: PendingAction | None = None
    handoff: Handoff | None = None

    @property
    def escalated(self) -> bool:
        return self.handoff is not None

    def require_customer_id(self) -> str:
        if self.verified_customer_id is None:
            raise IdentityNotVerified("The customer has not been verified in this session.")
        return self.verified_customer_id

    def escalate(self, reason: str, summary: str) -> Handoff:
        self.handoff = Handoff(
            reason=reason,
            summary=summary,
            customer_id=self.verified_customer_id,
            verified=self.verified_customer_id is not None,
            failed_verifications=self.failed_verifications,
            turns=self.turn,
        )
        return self.handoff
