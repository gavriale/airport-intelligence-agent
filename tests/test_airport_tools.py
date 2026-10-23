"""The airport tools through the real registry: argument validation and error codes."""

import json

import pytest

from core.tools import ToolRegistry
from domain.tools import build_tools
from tests.conftest import call

EXPECTED_TOOLS = {
    "search_airports", "get_airport_profile", "rank_airports", "compare_airports",
    "get_distance_profile", "demand_pressure", "get_live_status", "get_methodology",
}  # fmt: skip


def registry(analytics) -> ToolRegistry:
    return ToolRegistry(build_tools(analytics), timeout_s=5)


async def run(analytics, name, **arguments):
    result = await registry(analytics).execute(call(name, "t1", **arguments))
    return result, json.loads(result.content)


def test_the_assignment_tools_are_registered_with_descriptions(analytics):
    specs = registry(analytics).specs()

    assert {s.name for s in specs} == EXPECTED_TOOLS
    assert all(len(s.description) > 40 for s in specs)


async def test_rank_airports_returns_the_deterministic_ranking(analytics):
    result, body = await run(analytics, "rank_airports", region="New England", top_n=3)

    assert not result.is_error
    assert [r["rank"] for r in body["ranking"]] == [1, 2, 3]
    assert body["as_of"] == "Apr 2026"
    assert body["caveats"]


async def test_rank_airports_accepts_partial_weights(analytics):
    result, body = await run(
        analytics, "rank_airports", region="New England", weights={"growth": 0.6}
    )

    assert not result.is_error
    assert body["weights_used"]["growth"] == 0.6
    assert sum(body["weights_used"].values()) == pytest.approx(1, abs=0.002)


async def test_bad_arguments_are_rejected_before_any_analysis(analytics):
    too_many, too_many_body = await run(analytics, "rank_airports", top_n=500)
    bad_code, bad_code_body = await run(analytics, "get_distance_profile", iata="ANCHORAGE")
    one, one_body = await run(analytics, "compare_airports", iatas=["LAX"])

    for result, body in ((too_many, too_many_body), (bad_code, bad_code_body), (one, one_body)):
        assert result.is_error
        assert body["error"]["code"] == "invalid_arguments"


async def test_lowercase_iata_codes_work(analytics):
    result, body = await run(analytics, "get_distance_profile", iata="anc")

    assert not result.is_error
    assert body["iata"] == "ANC"


async def test_domain_errors_reach_the_model_with_their_code_and_advice(analytics):
    result, body = await run(analytics, "demand_pressure", iata="ZZZ")

    assert result.is_error
    assert body["error"]["code"] == "airport_not_found"
    assert "search_airports" in body["error"]["message"]


async def test_anchorage_distance_result_keeps_the_cargo_warning_in_the_json(analytics):
    _, body = await run(analytics, "get_distance_profile", iata="ANC")

    assert body["international_departures_mostly_cargo"] is True
    assert body["long_haul_share_pct"] is None
    assert any("mostly all-cargo" in c for c in body["caveats"])


async def test_methodology_tool_works_without_arguments(analytics):
    result, body = await run(analytics, "get_methodology")

    assert not result.is_error
    assert "score" in body and "metrics" in body and "limits" in body
