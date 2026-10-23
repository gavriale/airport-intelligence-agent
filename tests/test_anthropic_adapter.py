import anthropic
import httpx
import pytest

from adapters.anthropic_llm import (
    KEY_REJECTED,
    MODEL_UNAVAILABLE,
    AnthropicLLM,
    _to_api_message,
)
from core.errors import LLMError, LLMFatalError
from core.interfaces import Message, ToolCall, ToolResult


def test_plain_message_is_passed_through():
    assert _to_api_message(Message(role="user", content="hi")) == {"role": "user", "content": "hi"}


def test_assistant_tool_call_becomes_tool_use_block():
    message = Message(
        role="assistant",
        content="Checking.",
        tool_calls=[ToolCall(id="t1", name="get_portfolio", arguments={})],
    )

    assert _to_api_message(message)["content"] == [
        {"type": "text", "text": "Checking."},
        {"type": "tool_use", "id": "t1", "name": "get_portfolio", "input": {}},
    ]


def test_tool_result_becomes_tool_result_block():
    message = Message(
        role="user", tool_results=[ToolResult(tool_call_id="t1", content="{}", is_error=True)]
    )

    assert _to_api_message(message)["content"] == [
        {"type": "tool_result", "tool_use_id": "t1", "content": "{}", "is_error": True}
    ]


# ---------- which provider errors are retried ----------

MODEL = "claude-sonnet-5-5"
REQUEST = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def status_error(cls, status: int) -> anthropic.APIStatusError:
    return cls("raw provider text", response=httpx.Response(status, request=REQUEST), body=None)


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (status_error(anthropic.AuthenticationError, 401), KEY_REJECTED),
        (status_error(anthropic.PermissionDeniedError, 403), KEY_REJECTED),
        (status_error(anthropic.NotFoundError, 404), MODEL_UNAVAILABLE.format(model=MODEL)),
        (
            status_error(anthropic.BadRequestError, 400),
            "The model request was rejected (HTTP 400). See the server logs.",
        ),
    ],
)
def test_errors_a_retry_cannot_fix_are_fatal_with_a_clear_message(error, message):
    classified = AnthropicLLM("key", MODEL)._classify(error)

    assert isinstance(classified, LLMFatalError)
    assert classified.user_message == message
    assert "raw provider text" in str(classified)  # the real error stays in the exception


@pytest.mark.parametrize(
    "error",
    [
        status_error(anthropic.RateLimitError, 429),
        status_error(anthropic.InternalServerError, 500),
        status_error(anthropic.InternalServerError, 529),
        anthropic.APIConnectionError(request=REQUEST),
        anthropic.APITimeoutError(request=REQUEST),
    ],
)
def test_timeouts_rate_limits_and_5xx_stay_retryable(error):
    classified = AnthropicLLM("key", MODEL)._classify(error)

    assert type(classified) is LLMError


async def test_complete_raises_the_fatal_error_when_the_key_is_rejected():
    llm = AnthropicLLM("key", MODEL)

    async def reject(**_kwargs):
        raise status_error(anthropic.AuthenticationError, 401)

    llm._client.messages.create = reject

    with pytest.raises(LLMFatalError) as raised:
        await llm.complete("system", [Message(role="user", content="hi")], [])

    assert raised.value.user_message == KEY_REJECTED
