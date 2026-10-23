"""One conversational turn: the explicit tool-calling loop.

load session -> [call LLM -> run requested tools concurrently -> append results] until the
model answers or the iteration cap is hit -> save session.
"""

import asyncio
import logging
import time

from pydantic import BaseModel

from core.errors import LLMError
from core.interfaces import LLMProvider, LLMResponse, Message, SessionStore, ToolCall, ToolResult
from core.logging import log_event
from core.logging import session_id as session_id_var
from core.session import Session
from core.tools import ToolRegistry

FALLBACK_REPLY = "I'm having trouble right now. Please try again in a moment."


class ToolCallRecord(BaseModel):
    name: str
    arguments: dict
    result: str
    is_error: bool
    ms: float


class TurnResult(BaseModel):
    reply: str
    failed: bool = False
    tool_calls: list[ToolCallRecord] = []
    latency_ms: float = 0
    llm_ms: float = 0
    tools_ms: float = 0
    input_tokens: int = 0
    output_tokens: int = 0


class _TurnStats:
    """Mutable accumulator for one turn, turned into a TurnResult at the end."""

    def __init__(self) -> None:
        self.started = time.perf_counter()
        self.llm_ms = 0.0
        self.tools_ms = 0.0
        self.input_tokens = 0
        self.output_tokens = 0
        self.tool_calls: list[ToolCallRecord] = []


class Agent:
    def __init__(
        self,
        llm: LLMProvider,
        sessions: SessionStore,
        tools: ToolRegistry,
        system_prompt: str,
        *,
        llm_timeout_s: float,
        max_iterations: int = 6,
        llm_retries: int = 1,
        retry_backoff_s: float = 0.5,
    ) -> None:
        self._llm = llm
        self._sessions = sessions
        self._tools = tools
        self._system_prompt = system_prompt
        self._llm_timeout_s = llm_timeout_s
        self._max_iterations = max_iterations
        self._llm_retries = llm_retries
        self._retry_backoff_s = retry_backoff_s

    async def run_turn(self, session_id: str, user_text: str) -> TurnResult:
        stats = _TurnStats()
        session_id_var.set(session_id)  # every log line of this turn carries it
        session = await self._sessions.get_or_create(session_id)

        new_messages = [Message(role="user", content=user_text)]
        try:
            reply = await self._loop(session, new_messages, stats)
        except LLMError:
            reply = None

        if reply is None:
            # Drop the half-finished history: a tool call without its result is invalid for
            # the provider, so the next message starts from the last complete turn.
            return self._finish(stats, FALLBACK_REPLY, failed=True)

        new_messages.append(Message(role="assistant", content=reply))
        session.messages = [*session.messages, *new_messages]
        await self._sessions.save(session)
        return self._finish(stats, reply)

    async def _loop(
        self, session: Session, new_messages: list[Message], stats: _TurnStats
    ) -> str | None:
        """Returns the final text, or None if the iteration cap was reached."""
        for _ in range(self._max_iterations):
            history = [*session.messages, *new_messages]
            response = await self._timed_llm_call(history, stats)
            if not response.tool_calls:
                return response.text

            new_messages.append(
                Message(role="assistant", content=response.text, tool_calls=response.tool_calls)
            )
            results = await self._run_tools(response.tool_calls, stats)
            new_messages.append(Message(role="user", tool_results=results))
        log_event("max_iterations_reached", logging.WARNING, limit=self._max_iterations)
        return None

    async def _timed_llm_call(self, history: list[Message], stats: _TurnStats) -> LLMResponse:
        started = time.perf_counter()
        try:
            response = await self._call_llm(history)
        finally:
            stats.llm_ms += _ms_since(started)
        stats.input_tokens += response.input_tokens
        stats.output_tokens += response.output_tokens
        return response

    async def _call_llm(self, history: list[Message]) -> LLMResponse:
        """Timeout per attempt; retry with backoff; raise LLMError when attempts run out."""
        for attempt in range(self._llm_retries + 1):
            try:
                async with asyncio.timeout(self._llm_timeout_s):
                    return await self._llm.complete(
                        self._system_prompt, history, self._tools.specs()
                    )
            except (TimeoutError, LLMError) as exc:
                if attempt == self._llm_retries:
                    log_event("llm_failed", logging.ERROR, exc_info=True, attempts=attempt + 1)
                    raise LLMError(f"LLM failed after {attempt + 1} attempts: {exc!r}") from exc
                log_event("llm_retry", logging.WARNING, exc_info=True, attempt=attempt + 1)
                await asyncio.sleep(self._retry_backoff_s * 2**attempt)
        raise AssertionError("unreachable")

    async def _run_tools(self, calls: list[ToolCall], stats: _TurnStats) -> list[ToolResult]:
        """Independent calls from one model turn run concurrently."""
        started = time.perf_counter()
        results_and_records = await asyncio.gather(*(self._timed_tool_call(c) for c in calls))
        stats.tools_ms += _ms_since(started)
        results = [result for result, _ in results_and_records]
        stats.tool_calls.extend(record for _, record in results_and_records)
        return results

    # Returns (result for the model, record for turn stats and logging).
    async def _timed_tool_call(self, call: ToolCall) -> tuple[ToolResult, ToolCallRecord]:
        started = time.perf_counter()
        result = await self._tools.execute(call)
        record = ToolCallRecord(
            name=call.name,
            arguments=call.arguments,
            result=result.content,
            is_error=result.is_error,
            ms=_ms_since(started),
        )
        return result, record

    def _finish(self, stats: _TurnStats, reply: str, *, failed: bool = False) -> TurnResult:
        result = TurnResult(
            reply=reply,
            failed=failed,
            tool_calls=stats.tool_calls,
            latency_ms=_ms_since(stats.started),
            llm_ms=stats.llm_ms,
            tools_ms=stats.tools_ms,
            input_tokens=stats.input_tokens,
            output_tokens=stats.output_tokens,
        )
        log_event(
            "turn",
            tools=[t.name for t in result.tool_calls],
            tool_errors=sum(t.is_error for t in result.tool_calls),
            latency_ms=round(result.latency_ms),
            llm_ms=round(result.llm_ms),
            tools_ms=round(result.tools_ms),
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            failed=failed,
        )
        return result


def _ms_since(started: float) -> float:
    return (time.perf_counter() - started) * 1000
