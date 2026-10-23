import asyncio

import pytest

from core.agent import FALLBACK_REPLY
from core.errors import LLMError, LLMFatalError
from core.interfaces import LLMResponse
from tests.conftest import call, say, use


async def test_returns_llm_text_and_token_counts(rig):
    r = rig([LLMResponse(text="hello", input_tokens=10, output_tokens=3)])

    result = await r.agent.run_turn("s1", "hi")

    assert result.reply == "hello"
    assert not result.failed
    assert (result.input_tokens, result.output_tokens) == (10, 3)


async def test_history_is_kept_across_turns_and_system_prompt_is_sent(rig):
    r = rig([say("one"), say("two")])

    await r.agent.run_turn("s1", "first")
    await r.agent.run_turn("s1", "second")

    system, messages = r.llm.calls[1]
    assert system == "SYSTEM"
    assert [(m.role, m.content) for m in messages] == [
        ("user", "first"),
        ("assistant", "one"),
        ("user", "second"),
    ]


async def test_sessions_are_isolated(rig):
    r = rig([say("a"), say("b")])

    await r.agent.run_turn("s1", "hi")
    await r.agent.run_turn("s2", "hi")

    assert len(r.llm.calls[1][1]) == 1


async def test_tool_loop_runs_tool_and_feeds_result_back(rig):
    r = rig([use(call("add", a=2, b=3)), say("The sum is 5.")])

    result = await r.agent.run_turn("s1", "2+3?")

    assert result.reply == "The sum is 5."
    assert [t.name for t in result.tool_calls] == ["add"]
    assert '"sum": 5' in result.tool_calls[0].result
    _, history = r.llm.calls[1]
    assert history[-1].tool_results[0].tool_call_id == "t1"
    assert history[-2].tool_calls[0].name == "add"


async def test_tool_history_is_kept_for_follow_up_turns(rig):
    r = rig([use(call("add", a=1, b=1)), say("ok"), say("again")])

    await r.agent.run_turn("s1", "first")
    await r.agent.run_turn("s1", "thanks")

    _, history = r.llm.calls[2]
    assert [bool(m.tool_calls) for m in history[:3]] == [False, True, False]


async def test_parallel_tool_calls_run_concurrently(rig):
    delay = 0.15
    r = rig([use(call("slow", "a", delay=delay), call("slow", "b", delay=delay)), say("done")])

    result = await r.agent.run_turn("s1", "two slow things")

    assert r.calls["slow"] == 2
    assert result.tools_ms < delay * 1000 * 1.8  # sequential would be >= 2 * delay


async def test_tool_error_is_returned_to_the_model_not_raised(rig):
    r = rig([use(call("no_such_tool")), say("sorry")])

    result = await r.agent.run_turn("s1", "hi")

    assert result.reply == "sorry"
    assert result.tool_calls[0].is_error
    assert "unknown_tool" in r.llm.calls[1][1][-1].tool_results[0].content


async def test_iteration_cap_stops_a_looping_model(rig):
    r = rig([use(call("add", a=1, b=1))] * 10, max_iterations=3)

    result = await r.agent.run_turn("s1", "hi")

    assert result.failed
    assert result.reply == FALLBACK_REPLY
    assert len(r.llm.calls) == 3


async def test_retries_once_then_succeeds(rig):
    r = rig([LLMError("503"), say("ok")])

    result = await r.agent.run_turn("s1", "hi")

    assert result.reply == "ok"
    assert len(r.llm.calls) == 2


async def test_falls_back_and_does_not_save_the_turn_when_retries_run_out(rig):
    r = rig([LLMError("503"), LLMError("503")])

    result = await r.agent.run_turn("s1", "hi")

    assert result.reply == FALLBACK_REPLY
    assert result.failed
    assert (await r.sessions.get_or_create("s1")).messages == []


async def test_failure_after_a_tool_leaves_no_half_finished_history(rig):
    r = rig([use(call("add", a=1, b=2)), LLMError("503"), LLMError("503")])

    result = await r.agent.run_turn("s1", "hi")

    assert result.failed
    assert (await r.sessions.get_or_create("s1")).messages == []


async def test_timeout_counts_as_a_failed_attempt(rig):
    r = rig([], llm_timeout_s=0.01)

    async def slow(system, messages, tools):
        await asyncio.sleep(1)

    r.agent._llm.complete = slow

    result = await r.agent.run_turn("s1", "hi")

    assert result.failed


@pytest.mark.parametrize("retries,expected_calls", [(0, 1), (2, 3)])
async def test_retry_count_is_configurable(rig, retries, expected_calls):
    r = rig([LLMError("x")] * 5, llm_retries=retries)

    await r.agent.run_turn("s1", "hi")

    assert len(r.llm.calls) == expected_calls


async def test_a_fatal_error_is_not_retried_and_the_user_gets_its_message(rig):
    r = rig([LLMFatalError("The key was rejected.", "401 raw"), say("never reached")])

    result = await r.agent.run_turn("s1", "hi")

    assert result.reply == "The key was rejected."
    assert result.failed
    assert len(r.llm.calls) == 1  # no retry
    assert (await r.sessions.get_or_create("s1")).messages == []


async def test_a_fatal_error_after_a_tool_is_not_retried_either(rig):
    r = rig([use(call("add", a=1, b=2)), LLMFatalError("Model x is not available.", "404 raw")])

    result = await r.agent.run_turn("s1", "hi")

    assert result.reply == "Model x is not available."
    assert len(r.llm.calls) == 2
    assert (await r.sessions.get_or_create("s1")).messages == []
