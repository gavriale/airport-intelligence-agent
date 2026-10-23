"""A reply cut off by the output-token limit must be visible in the logs."""

import logging
from types import SimpleNamespace

from adapters.anthropic_llm import MAX_OUTPUT_TOKENS, AnthropicLLM
from core.interfaces import Message


def fake_response(stop_reason: str):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text="partial answer")],
        stop_reason=stop_reason,
        usage=SimpleNamespace(
            input_tokens=10,
            output_tokens=MAX_OUTPUT_TOKENS,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
        ),
    )


def llm_returning(response) -> AnthropicLLM:
    llm = AnthropicLLM("test-key", "test-model")

    async def create(**kwargs):
        return response

    llm._client.messages.create = create
    return llm


async def test_a_reply_cut_off_by_the_token_limit_logs_a_warning(caplog):
    llm = llm_returning(fake_response("max_tokens"))

    with caplog.at_level(logging.INFO, logger="agent"):
        result = await llm.complete("sys", [Message(role="user", content="hi")], [])

    assert result.text == "partial answer"
    warnings = [r for r in caplog.records if r.getMessage() == "llm_truncated"]
    assert len(warnings) == 1 and warnings[0].levelno == logging.WARNING
    assert warnings[0].fields["limit"] == MAX_OUTPUT_TOKENS


async def test_a_normal_reply_does_not_warn_and_usage_records_the_stop_reason(caplog):
    llm = llm_returning(fake_response("end_turn"))

    with caplog.at_level(logging.INFO, logger="agent"):
        await llm.complete("sys", [Message(role="user", content="hi")], [])

    assert [r for r in caplog.records if r.getMessage() == "llm_truncated"] == []
    [usage] = [r for r in caplog.records if r.getMessage() == "llm_usage"]
    assert usage.fields["stop_reason"] == "end_turn"
