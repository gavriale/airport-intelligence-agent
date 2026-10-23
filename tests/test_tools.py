"""Registry behavior: schemas, validation, error results, timeout and retry."""

import json

from tests.conftest import call


async def run(r, name: str, **arguments):
    result = await r.tools.execute(call(name, "t1", **arguments))
    return result, json.loads(result.content)


async def test_specs_come_from_the_pydantic_models(rig):
    specs = {s.name: s for s in rig([]).tools.specs()}

    assert set(specs["add"].input_schema["properties"]) == {"a", "b"}
    assert specs["add"].description == "Add two integers."


async def test_successful_call_returns_json_and_is_not_an_error(rig):
    result, body = await run(rig([]), "add", a=2, b=3)

    assert body == {"sum": 5}
    assert not result.is_error
    assert result.tool_call_id == "t1"


async def test_unknown_tool_returns_a_structured_error(rig):
    result, body = await run(rig([]), "nope")

    assert result.is_error
    assert body["error"]["code"] == "unknown_tool"


async def test_invalid_arguments_name_the_bad_field(rig):
    result, body = await run(rig([]), "add", a="x")

    assert result.is_error
    assert body["error"]["code"] == "invalid_arguments"
    assert "a:" in body["error"]["message"]
    assert "b:" in body["error"]["message"]  # missing field is reported too


async def test_expected_error_keeps_its_code_and_message_and_is_not_retried(rig):
    r = rig([])

    result, body = await run(r, "refuse")

    assert body["error"] == {"code": "not_found", "message": "No such airport."}
    assert r.calls["refuse"] == 1


async def test_unexpected_exception_becomes_internal_error_without_details(rig):
    r = rig([])

    result, body = await run(r, "boom")

    assert result.is_error
    assert body["error"]["code"] == "internal_error"
    assert "secret internals" not in result.content
    assert r.calls["boom"] == 2  # tried once more


async def test_one_transient_failure_is_retried_and_succeeds(rig):
    r = rig([])

    result, body = await run(r, "flaky")

    assert body == {"ok": True}
    assert not result.is_error
    assert r.calls["flaky"] == 2


async def test_slow_tool_times_out_into_internal_error(rig):
    r = rig([], tool_timeout_s=0.01)

    result, body = await run(r, "slow", delay=1)

    assert body["error"]["code"] == "internal_error"
