import logging

import pytest

from adapters.fake_llm import FakeLLMProvider
from adapters.llm_cache import CachingLLMProvider
from core.errors import LLMError
from core.interfaces import LLMResponse, Message, ToolCall, ToolSpec

USER = [Message(role="user", content="hi")]


def make(tmp_path, script, model="m"):
    inner = FakeLLMProvider(script)
    return inner, CachingLLMProvider(inner, tmp_path / "cache", model)


async def test_miss_calls_inner_then_hit_does_not(tmp_path):
    inner, cache = make(tmp_path, [LLMResponse(text="a", input_tokens=50, output_tokens=5)])

    first = await cache.complete("sys", USER, [])
    second = await cache.complete("sys", USER, [])

    assert first.text == second.text == "a"
    assert len(inner.calls) == 1


async def test_replay_reports_zero_tokens_but_miss_keeps_real_ones(tmp_path):
    _, cache = make(tmp_path, [LLMResponse(text="a", input_tokens=50, output_tokens=5)])

    first = await cache.complete("sys", USER, [])
    replay = await cache.complete("sys", USER, [])

    assert (first.input_tokens, first.output_tokens) == (50, 5)
    assert (replay.input_tokens, replay.output_tokens) == (0, 0)


async def test_entries_survive_a_new_instance(tmp_path):
    _, cache = make(tmp_path, [LLMResponse(text="a")])
    await cache.complete("sys", USER, [])

    inner, fresh = make(tmp_path, [])  # empty script: any real call would raise
    assert (await fresh.complete("sys", USER, [])).text == "a"
    assert inner.calls == []


@pytest.mark.parametrize(
    "system,messages,tools,model",
    [
        ("other", USER, [], "m"),
        ("sys", [Message(role="user", content="hello")], [], "m"),
        ("sys", USER, [ToolSpec(name="t", description="d", input_schema={})], "m"),
        ("sys", USER, [], "other-model"),
    ],
)
async def test_any_input_change_is_a_miss(tmp_path, system, messages, tools, model):
    inner, cache = make(tmp_path, [LLMResponse(text="a"), LLMResponse(text="b")])
    await cache.complete("sys", USER, [])

    other = CachingLLMProvider(inner, tmp_path / "cache", model)
    result = await other.complete(system, messages, tools)

    assert result.text == "b"


async def test_tool_calls_round_trip(tmp_path):
    call = ToolCall(id="t1", name="get_portfolio", arguments={"x": 1})
    _, cache = make(tmp_path, [LLMResponse(tool_calls=[call])])

    await cache.complete("sys", USER, [])
    replay = await cache.complete("sys", USER, [])

    assert replay.tool_calls == [call]


async def test_failures_are_not_cached(tmp_path):
    inner, cache = make(tmp_path, [LLMError("503"), LLMResponse(text="ok")])

    with pytest.raises(LLMError):
        await cache.complete("sys", USER, [])
    result = await cache.complete("sys", USER, [])

    assert result.text == "ok"
    assert len(inner.calls) == 2


async def test_hit_and_miss_are_logged(tmp_path, caplog):
    _, cache = make(tmp_path, [LLMResponse(text="a")])

    with caplog.at_level(logging.INFO, logger="agent"):
        await cache.complete("sys", USER, [])
        await cache.complete("sys", USER, [])

    assert [r.getMessage() for r in caplog.records] == ["llm_cache_miss", "llm_cache_hit"]
