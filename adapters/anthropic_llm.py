import logging

import anthropic

from core.errors import LLMError
from core.interfaces import LLMResponse, Message, ToolCall, ToolSpec
from core.logging import log_event

MAX_OUTPUT_TOKENS = 2048


class AnthropicLLM:
    def __init__(self, api_key: str, model: str) -> None:
        # max_retries=0: retrying is the agent's job, so timeouts and backoff live in one place.
        self._client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=0)
        self._model = model

    async def complete(
        self, system: str, messages: list[Message], tools: list[ToolSpec]
    ) -> LLMResponse:
        kwargs = {}
        if tools:
            kwargs["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.input_schema}
                for t in tools
            ]
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=MAX_OUTPUT_TOKENS,
                system=system,
                messages=[_to_api_message(m) for m in messages],
                # Prompt caching: the API caches the longest stable prefix (tools, then system,
                # then the conversation so far), so repeated calls pay a fraction for it.
                cache_control={"type": "ephemeral"},
                **kwargs,
            )
        except anthropic.APIError as exc:
            raise LLMError(str(exc)) from exc
        usage = response.usage
        log_event(
            "llm_usage",
            uncached_input_tokens=usage.input_tokens,
            cache_write_tokens=usage.cache_creation_input_tokens or 0,
            cache_read_tokens=usage.cache_read_input_tokens or 0,
            output_tokens=usage.output_tokens,
            stop_reason=response.stop_reason,
        )
        if response.stop_reason == "max_tokens":
            log_event(
                "llm_truncated",
                logging.WARNING,
                output_tokens=usage.output_tokens,
                limit=MAX_OUTPUT_TOKENS,
            )
        return LLMResponse(
            text="".join(b.text for b in response.content if b.type == "text"),
            tool_calls=[
                ToolCall(id=b.id, name=b.name, arguments=b.input)
                for b in response.content
                if b.type == "tool_use"
            ],
            # Total input processed, whether or not it was served from cache.
            input_tokens=(
                usage.input_tokens
                + (usage.cache_creation_input_tokens or 0)
                + (usage.cache_read_input_tokens or 0)
            ),
            output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_input_tokens or 0,
            cache_write_tokens=usage.cache_creation_input_tokens or 0,
        )


def _to_api_message(message: Message) -> dict:
    if not message.tool_calls and not message.tool_results:
        return {"role": message.role, "content": message.content}
    blocks: list[dict] = []
    if message.content:
        blocks.append({"type": "text", "text": message.content})
    blocks += [
        {"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments}
        for c in message.tool_calls
    ]
    blocks += [
        {
            "type": "tool_result",
            "tool_use_id": r.tool_call_id,
            "content": r.content,
            "is_error": r.is_error,
        }
        for r in message.tool_results
    ]
    return {"role": message.role, "content": blocks}
