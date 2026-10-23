"""One conversational turn: the explicit tool-calling loop.

load session -> [call LLM -> run requested tools concurrently -> append results] until the
model answers or the iteration cap is hit -> output guardrail -> save session.
"""

import asyncio
import logging
import time

from pydantic import BaseModel

from core.errors import LLMError, PolicyViolation
from core.guardrails import Guardrails
from core.interfaces import LLMProvider, LLMResponse, Message, SessionStore, ToolCall, ToolResult
from core.logging import log_event
from core.logging import session_id as session_id_var
from core.session import Handoff, Session
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
    escalated: bool = False
    handoff: Handoff | None = None
    policy_violation: bool = False
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
        guardrails: Guardrails,
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
        self._guardrails = guardrails
        self._system_prompt = system_prompt
        self._llm_timeout_s = llm_timeout_s
        self._max_iterations = max_iterations
        self._llm_retries = llm_retries
        self._retry_backoff_s = retry_backoff_s

    async def run_turn(self, session_id: str, user_text: str) -> TurnResult:
        stats = _TurnStats()
        session_id_var.set(session_id)  # every log line of this turn carries it
        session = await self._sessions.get_or_create(session_id)
        if session.escalated:
            return self._finish(session, stats, self._guardrails.config.escalated_reply)

        session.turn += 1
        new_messages = [Message(role="user", content=user_text)]
        try:
            reply = await self._loop(session, new_messages, stats)
        except LLMError:
            reply = None

        if reply is None:
            # Keep state changes (verification, pending action) but drop the half-finished
            # history: a tool call without its result is invalid for the provider.
            await self._sessions.save(session)
            return self._finish(session, stats, FALLBACK_REPLY, failed=True)

        violation = False
        try:
            self._guardrails.check_output(reply)
        except PolicyViolation as exc:
            log_event("policy_violation", detail=str(exc))
            reply, violation = self._guardrails.config.advice_refusal_message, True
        new_messages.append(Message(role="assistant", content=reply))

        session.messages = [*session.messages, *new_messages]
        await self._sessions.save(session)
        return self._finish(session, stats, reply, policy_violation=violation)

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
            results = await self._run_tools(response.tool_calls, session, stats)
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

    async def _run_tools(
        self, calls: list[ToolCall], session: Session, stats: _TurnStats
    ) -> list[ToolResult]:
        """Independent calls from one model turn run concurrently."""
        started = time.perf_counter()
        timed = await asyncio.gather(*(self._timed_tool_call(c, session) for c in calls))
        stats.tools_ms += _ms_since(started)
        stats.tool_calls.extend(record for _, record in timed)
        return [result for result, _ in timed]

    async def _timed_tool_call(
        self, call: ToolCall, session: Session
    ) -> tuple[ToolResult, ToolCallRecord]:
        started = time.perf_counter()
        result = await self._tools.execute(call, session)
        record = ToolCallRecord(
            name=call.name,
            arguments=call.arguments,
            result=result.content,
            is_error=result.is_error,
            ms=_ms_since(started),
        )
        return result, record

    def _finish(
        self,
        session: Session,
        stats: _TurnStats,
        reply: str,
        *,
        failed: bool = False,
        policy_violation: bool = False,
    ) -> TurnResult:
        result = TurnResult(
            reply=reply,
            failed=failed,
            escalated=session.escalated,
            handoff=session.handoff,
            policy_violation=policy_violation,
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
            escalated=result.escalated,
            failed=failed,
            policy_violation=policy_violation,
        )
        return result


def _ms_since(started: float) -> float:
    return (time.perf_counter() - started) * 1000
