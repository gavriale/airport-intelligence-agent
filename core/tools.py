"""Tool registry: schemas, validation, timeouts and structured errors.

A call goes: known tool -> valid arguments -> run (with timeout and one retry). Every failure
becomes a structured error result for the model; nothing here raises into the agent loop.
"""

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from core.errors import ToolExecutionError
from core.interfaces import ToolCall, ToolResult, ToolSpec
from core.logging import log_event

RETRY_BACKOFF_S = 0.2

Handler = Callable[[Any], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_model: type[BaseModel]
    handler: Handler

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

    async def execute(self, call: ToolCall) -> ToolResult:
        started = time.perf_counter()
        error_code = None
        try:
            payload = await self._run(call)
            result = ToolResult(tool_call_id=call.id, content=_dump(payload))
        except ToolExecutionError as exc:
            error_code = exc.code
            result = _error(call, exc.code, exc.message)
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

    async def _run(self, call: ToolCall) -> dict[str, Any]:
        tool = self._tools.get(call.name)
        if tool is None:
            raise ToolExecutionError("unknown_tool", f"No tool named {call.name!r}.")
        try:
            args = tool.input_model.model_validate(call.arguments)
        except ValidationError as exc:
            raise ToolExecutionError("invalid_arguments", _summarise(exc)) from exc
        return await self._invoke(tool, args)

    async def _invoke(self, tool: Tool, args: BaseModel) -> dict[str, Any]:
        """Timeout per attempt, one retry on unexpected failure. Tools are read-only, so a
        retry is always safe."""
        for attempt in range(2):
            try:
                async with asyncio.timeout(self._timeout_s):
                    return await tool.handler(args)
            except ToolExecutionError:
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
