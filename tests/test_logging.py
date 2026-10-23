import json
import logging

from core.logging import ConsoleFormatter, JsonFormatter, correlation_id, log_event, session_id
from tests.conftest import call, say, use


def records(caplog, event):
    return [r for r in caplog.records if r.getMessage() == event]


async def test_failing_tool_handler_logs_a_traceback(rig, caplog):
    r = rig([])

    with caplog.at_level(logging.INFO, logger="agent"):
        result = await r.tools.execute(call("boom"))

    assert result.is_error
    [failure] = records(caplog, "tool_exception")
    assert failure.levelno == logging.ERROR
    assert "RuntimeError: secret internals" in JsonFormatter().format(failure)
    assert failure.exc_info is not None


async def test_tool_retry_is_logged_with_its_traceback(rig, caplog):
    r = rig([])

    with caplog.at_level(logging.INFO, logger="agent"):
        await r.tools.execute(call("flaky"))

    [retry] = records(caplog, "tool_retry")
    assert retry.levelno == logging.WARNING
    assert "ConnectionError: temporary" in JsonFormatter().format(retry)


async def test_tool_call_event_has_name_ms_error_flag_and_code(rig, caplog):
    r = rig([])

    with caplog.at_level(logging.INFO, logger="agent"):
        await r.tools.execute(call("refuse"))

    [event] = records(caplog, "tool_call")
    assert event.fields["name"] == "refuse"
    assert event.fields["is_error"] is True
    assert event.fields["error_code"] == "not_found"
    assert isinstance(event.fields["ms"], int)


async def test_expected_errors_are_not_logged_as_exceptions(rig, caplog):
    r = rig([])

    with caplog.at_level(logging.INFO, logger="agent"):
        await r.tools.execute(call("refuse"))

    assert records(caplog, "tool_exception") == []


async def test_successful_tool_call_event_has_no_error_code(rig, caplog):
    r = rig([])

    with caplog.at_level(logging.INFO, logger="agent"):
        await r.tools.execute(call("add", a=1, b=2))

    [event] = records(caplog, "tool_call")
    assert (event.fields["is_error"], event.fields["error_code"]) == (False, None)


async def test_llm_retry_and_final_failure_are_logged_with_tracebacks(rig, caplog):
    from core.errors import LLMError

    r = rig([LLMError("503"), LLMError("503")])

    with caplog.at_level(logging.INFO, logger="agent"):
        await r.agent.run_turn("s1", "hi")

    assert records(caplog, "llm_retry")[0].exc_info is not None
    assert records(caplog, "llm_failed")[0].levelno == logging.ERROR
    assert records(caplog, "llm_failed")[0].exc_info is not None


def test_log_event_points_at_the_caller_and_json_has_ids(caplog):
    correlation_id.set("corr-1234567890")
    session_id.set("sess-1234567890")

    with caplog.at_level(logging.INFO, logger="agent"):
        log_event("something", answer=42)

    record = caplog.records[0]
    assert record.funcName == "test_log_event_points_at_the_caller_and_json_has_ids"
    assert record.filename == "test_logging.py"
    entry = json.loads(JsonFormatter().format(record))
    assert entry["function"] == record.funcName
    assert entry["file"].endswith("tests/test_logging.py")
    assert (entry["correlation_id"], entry["session_id"], entry["answer"]) == (
        "corr-1234567890",
        "sess-1234567890",
        42,
    )


def test_console_format_is_one_readable_line(caplog):
    correlation_id.set("corr-1234567890")
    session_id.set("sess-1234567890")

    with caplog.at_level(logging.INFO, logger="agent"):
        log_event("tool_call", name="get_portfolio", ms=3)

    line = ConsoleFormatter().format(caplog.records[0])
    assert "\n" not in line
    for part in (
        "INFO",
        "tool_call",
        "tests/test_logging.py:",
        "[corr-123 sess-123]",
        "name=get_portfolio",
        "ms=3",
    ):
        assert part in line


async def test_agent_sets_session_id_for_every_line(rig, caplog):
    r = rig([use(call("add", a=1, b=2)), say("ok")])

    with caplog.at_level(logging.INFO, logger="agent"):
        await r.agent.run_turn("my-session", "add?")

    assert session_id.get() == "my-session"
