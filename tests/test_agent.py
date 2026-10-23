import asyncio

import pytest

from core.agent import FALLBACK_REPLY
from core.errors import LLMError
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
    r = rig([use(call("get_portfolio")), say("You have 125,400 NIS.")])
    await r.verify()

    result = await r.agent.run_turn("s1", "balance?")

    assert result.reply == "You have 125,400 NIS."
    assert [t.name for t in result.tool_calls] == ["get_portfolio"]
    assert "125400" in result.tool_calls[0].result
    _, history = r.llm.calls[1]
    assert history[-1].tool_results[0].tool_call_id == "t1"
    assert history[-2].tool_calls[0].name == "get_portfolio"


async def test_tool_history_is_kept_for_follow_up_turns(rig):
    r = rig([use(call("get_portfolio")), say("ok"), say("again")])
    await r.verify()

    await r.agent.run_turn("s1", "balance?")
    await r.agent.run_turn("s1", "thanks")

    _, history = r.llm.calls[2]
    assert [bool(m.tool_calls) for m in history[:3]] == [False, True, False]


async def test_parallel_tool_calls_run_concurrently(rig):
    r = rig([use(call("get_portfolio", "a"), call("get_recent_transactions", "b")), say("done")])
    await r.verify()
    delay = 0.15

    original = r.repo.get_portfolio

    async def slow_portfolio(customer_id):
        await asyncio.sleep(delay)
        return await original(customer_id)

    original_tx = r.repo.get_transactions

    async def slow_transactions(customer_id, limit):
        await asyncio.sleep(delay)
        return await original_tx(customer_id, limit)

    r.repo.get_portfolio = slow_portfolio
    r.repo.get_transactions = slow_transactions

    result = await r.agent.run_turn("s1", "balance and transactions")

    assert result.tools_ms < delay * 1000 * 1.8  # sequential would be >= 2 * delay


async def test_tool_error_is_returned_to_the_model_not_raised(rig):
    r = rig([use(call("no_such_tool")), say("sorry")])

    result = await r.agent.run_turn("s1", "hi")

    assert result.reply == "sorry"
    assert result.tool_calls[0].is_error
    assert "unknown_tool" in r.llm.calls[1][1][-1].tool_results[0].content


async def test_iteration_cap_stops_a_looping_model(rig):
    r = rig([use(call("search_knowledge", query="fees"))] * 10, max_iterations=3)

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


async def test_failure_after_a_tool_keeps_state_but_not_half_finished_history(rig):
    r = rig(
        [
            use(call("verify_identity", customer_id="C001", phone_last4="4412")),
            LLMError("503"),
            LLMError("503"),
        ]
    )

    result = await r.agent.run_turn("s1", "I'm C001, 4412")

    session = await r.sessions.get_or_create("s1")
    assert result.failed
    assert session.verified_customer_id == "C001"
    assert session.messages == []


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


async def test_advice_in_reply_is_replaced_and_not_stored(rig):
    r = rig([say("Yes, you should buy the Global Equity Fund.")])

    result = await r.agent.run_turn("s1", "what should I buy?")

    assert result.policy_violation
    assert "licensed" in result.reply
    stored = (await r.sessions.get_or_create("s1")).messages
    assert "should buy" not in stored[-1].content


async def test_escalation_returns_handoff_and_short_circuits_later_turns(rig):
    r = rig(
        [
            use(call("escalate_to_human", reason="user_request", summary="wants a person")),
            say("Connecting you."),
        ]
    )

    result = await r.agent.run_turn("s1", "let me talk to a person")
    later = await r.agent.run_turn("s1", "hello?")

    assert result.escalated
    assert result.handoff.summary == "wants a person"
    assert later.escalated
    assert len(r.llm.calls) == 2  # no LLM call on the later turn
