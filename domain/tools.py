"""Domain tools for the placeholder investment house. Swap this file for a new domain."""

from typing import Any, Protocol

from pydantic import BaseModel, Field

from core.errors import ToolExecutionError
from core.guardrails import Guardrails
from core.interfaces import DataRepository, KnowledgeIndex
from core.tools import Tool, ToolContext

MAX_TRANSACTIONS = 20
KNOWLEDGE_HITS = 3


class AccountRepository(DataRepository, Protocol):
    """The client backend as the tools see it. Every method takes the verified customer's ID."""

    async def get_portfolio(self, customer_id: str) -> dict[str, Any]: ...

    async def get_transactions(self, customer_id: str, limit: int) -> list[dict[str, Any]]: ...

    async def get_withdrawals(
        self, customer_id: str, request_id: str | None
    ) -> list[dict[str, Any]]: ...

    async def create_withdrawal(
        self, customer_id: str, amount_nis: float, idempotency_key: str
    ) -> dict[str, Any]: ...


class VerifyIdentityArgs(BaseModel):
    customer_id: str = Field(description="Customer ID, e.g. C001")
    phone_last4: str = Field(pattern=r"^\d{4}$", description="Last 4 digits of the phone number")


class NoArgs(BaseModel):
    pass


class TransactionsArgs(BaseModel):
    limit: int = Field(default=5, ge=1, le=MAX_TRANSACTIONS)


class WithdrawalStatusArgs(BaseModel):
    request_id: str | None = Field(default=None, description="e.g. W-1002; omit to list all")


class WithdrawalArgs(BaseModel):
    amount_nis: float = Field(gt=0, description="Amount to withdraw in NIS")


class SearchArgs(BaseModel):
    query: str = Field(min_length=2, description="What to look up in the knowledge base")


class EscalateArgs(BaseModel):
    reason: str = Field(description="Why: user_request, out_of_scope, fraud, complaint, other")
    summary: str = Field(description="Short factual summary of the conversation for the human")


def build_tools(
    repo: AccountRepository, knowledge: KnowledgeIndex, guardrails: Guardrails
) -> list[Tool]:
    async def verify_identity(ctx: ToolContext, args: VerifyIdentityArgs) -> dict[str, Any]:
        session = ctx.session
        if session.verified_customer_id is not None:
            raise ToolExecutionError("already_verified", "This session is already verified.")
        if await repo.verify_identity(args.customer_id, args.phone_last4):
            session.verified_customer_id = args.customer_id
            return {"verified": True}

        session.failed_verifications += 1
        if guardrails.verification_limit_reached(session.failed_verifications):
            session.escalate(
                "identity_verification_failed",
                f"{session.failed_verifications} failed identity checks; no data was shared.",
            )
            return {"verified": False, "escalated": True}
        return {"verified": False, "escalated": False}

    async def get_portfolio(ctx: ToolContext, args: NoArgs) -> dict[str, Any]:
        return await repo.get_portfolio(ctx.customer_id)

    async def get_recent_transactions(ctx: ToolContext, args: TransactionsArgs) -> dict[str, Any]:
        return {"transactions": await repo.get_transactions(ctx.customer_id, args.limit)}

    async def get_withdrawal_status(ctx: ToolContext, args: WithdrawalStatusArgs) -> dict[str, Any]:
        requests = await repo.get_withdrawals(ctx.customer_id, args.request_id)
        if not requests:
            raise ToolExecutionError("not_found", "No matching withdrawal request.")
        return {"withdrawal_requests": requests}

    async def request_withdrawal(ctx: ToolContext, args: WithdrawalArgs) -> dict[str, Any]:
        balance = (await repo.get_portfolio(ctx.customer_id))["total_value_nis"]
        if args.amount_nis > balance:
            raise ToolExecutionError(
                "insufficient_balance", f"The amount exceeds the balance of {balance} NIS."
            )
        assert ctx.idempotency_key is not None  # set by the registry for every write
        created = await repo.create_withdrawal(
            ctx.customer_id, args.amount_nis, ctx.idempotency_key
        )
        return {"executed": True, "withdrawal_request": created}

    async def search_knowledge(ctx: ToolContext, args: SearchArgs) -> dict[str, Any]:
        hits = await knowledge.search(args.query, KNOWLEDGE_HITS)
        return {"documents": [{"title": h.title, "text": h.text} for h in hits]}

    async def escalate_to_human(ctx: ToolContext, args: EscalateArgs) -> dict[str, Any]:
        handoff = ctx.session.escalate(args.reason, args.summary)
        return {"escalated": True, "handoff": handoff.model_dump()}

    return [
        Tool(
            "verify_identity",
            "Check the customer's identity with their customer ID and last 4 phone digits.",
            VerifyIdentityArgs,
            verify_identity,
            requires_verification=False,
        ),
        Tool(
            "get_portfolio",
            "Get the verified customer's holdings and total balance in NIS.",
            NoArgs,
            get_portfolio,
        ),
        Tool(
            "get_recent_transactions",
            "Get the verified customer's most recent transactions.",
            TransactionsArgs,
            get_recent_transactions,
        ),
        Tool(
            "get_withdrawal_status",
            "Get the status of the verified customer's withdrawal requests.",
            WithdrawalStatusArgs,
            get_withdrawal_status,
        ),
        Tool(
            "request_withdrawal",
            "Open a withdrawal request. Needs customer confirmation: the first call only "
            "proposes, the second call (after they confirm) executes.",
            WithdrawalArgs,
            request_withdrawal,
            access="write",
        ),
        Tool(
            "search_knowledge",
            "Search company documents: fees, withdrawal rules, products, policies.",
            SearchArgs,
            search_knowledge,
            requires_verification=False,
        ),
        Tool(
            "escalate_to_human",
            "Hand the conversation to a human agent with a short summary.",
            EscalateArgs,
            escalate_to_human,
            requires_verification=False,
        ),
    ]
