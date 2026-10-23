"""Tool registry: schemas, validation, and the code-level gates in front of every handler.

Gates, in order: known tool -> valid arguments -> identity -> write confirmation -> execute
(with timeout and one retry). Every failure becomes a structured error result for the model;
nothing here raises into the agent loop.
"""

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from core.errors import IdentityNotVerified, ToolExecutionError
from core.interfaces import ToolCall, ToolResult, ToolSpec
from core.logging import log_event
from core.session import PendingAction, Session

RETRY_BACKOFF_S = 0.2


@dataclass
class ToolContext:
    """What a handler may use. The customer ID comes from the session, never from the model."""

    session: Session
    idempotency_key: str | None = None

    @property
    def customer_id(self) -> str:
        return self.session.require_customer_id()


Handler = Callable[[ToolContext, Any], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_model: type[BaseModel]
    handler: Handler
    access: Literal["read", "write"] = "read"
    requires_verification: bool = True

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=self.description,
            input_schema=self.input_model.model_json_schema(),
        )


class ToolRegistry:
    def __init__(self, tools: list[Tool], *, timeout_s: float) -> None:
        self._tools = {tool.name: tool for tool in tools}
        self._timeout_s = timeout_s

    def specs(self) -> list[ToolSpec]:
        return [tool.spec() for tool in self._tools.values()]

    async def execute(self, call: ToolCall, session: Session) -> ToolResult:
        started = time.perf_counter()
        error_code = None
        try:
            payload = await self._run(call, session)
            result = ToolResult(tool_call_id=call.id, content=_dump(payload))
        except ToolExecutionError as exc:
            error_code = exc.code
            result = _error(call, exc.code, exc.message)
        except IdentityNotVerified as exc:
            error_code = "identity_not_verified"
            result = _error(call, error_code, str(exc))
        except Exception:  # noqa: BLE001 - the loop must survive any handler bug
            error_code = "internal_error"
            log_event("tool_exception", logging.ERROR, exc_info=True, tool=call.name)
            result = _error(call, error_code, "The tool failed. Do not guess the data.")
        log_event(
            "tool_call",
            name=call.name,
            ms=round((time.perf_counter() - started) * 1000),
            is_error=result.is_error,
            error_code=error_code,
        )
        return result

    async def _run(self, call: ToolCall, session: Session) -> dict[str, Any]:
        tool = self._tools.get(call.name)
        if tool is None:
            raise ToolExecutionError("unknown_tool", f"No tool named {call.name!r}.")
        try:
            args = tool.input_model.model_validate(call.arguments)
        except ValidationError as exc:
            raise ToolExecutionError("invalid_arguments", _summarise(exc)) from exc

        if tool.requires_verification:
            session.require_customer_id()

        if tool.access == "write":
            return await self._run_write(tool, args, session)
        return await self._invoke(tool, ToolContext(session), args)

    async def _run_write(self, tool: Tool, args: BaseModel, session: Session) -> dict[str, Any]:
        """Two steps across two user turns: propose (nothing happens), then execute."""
        arguments = args.model_dump()
        pending = session.pending_action
        matches = (
            pending is not None and pending.tool == tool.name and pending.arguments == arguments
        )
        if matches and pending.turn < session.turn:
            session.pending_action = None
            return await self._invoke(tool, ToolContext(session, pending.idempotency_key), args)

        if not matches:
            session.pending_action = PendingAction(
                tool=tool.name,
                arguments=arguments,
                idempotency_key=str(uuid.uuid4()),
                turn=session.turn,
            )
        return {
            "status": "confirmation_required",
            "executed": False,
            "arguments": arguments,
            "instruction": (
                "Nothing has been done yet. Show these details to the customer and ask for "
                "explicit confirmation. After they confirm in their next message, call this "
                "tool again with exactly the same arguments."
            ),
        }

    async def _invoke(self, tool: Tool, ctx: ToolContext, args: BaseModel) -> dict[str, Any]:
        """Timeout per attempt, one retry on unexpected failure. Safe for writes because the
        idempotency key makes a repeated write return the first result."""
        for attempt in range(2):
            try:
                async with asyncio.timeout(self._timeout_s):
                    return await tool.handler(ctx, args)
            except (ToolExecutionError, IdentityNotVerified):
                raise
            except Exception:  # noqa: BLE001 - timeouts and backend errors alike
                if attempt == 1:
                    raise
                log_event("tool_retry", logging.WARNING, exc_info=True, tool=tool.name)
                await asyncio.sleep(RETRY_BACKOFF_S)
        raise AssertionError("unreachable")


def _dump(payload: dict[str, Any]) -> str:
    return json.dumps(payload, default=str, ensure_ascii=False)


def _error(call: ToolCall, code: str, message: str) -> ToolResult:
    content = _dump({"error": {"code": code, "message": message}})
    return ToolResult(tool_call_id=call.id, content=content, is_error=True)


def _summarise(exc: ValidationError) -> str:
    return "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
