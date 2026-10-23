from adapters.anthropic_llm import _to_api_message
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
