"""Analytics on the committed snapshot (in-memory repository, fake live feed)."""

import pytest

from core.errors import ToolExecutionError
from tests.conftest import FakeLiveStatus

NEW_ENGLAND = {"CT", "MA", "ME", "NH", "RI", "VT"}


async def test_new_england_ranking_is_sorted_scoped_and_labelled(analytics):
    result = await analytics.rank("New England", None, 20, None)

    scores = [r["score"] for r in result["ranking"]]
    assert scores == sorted(scores, reverse=True)
    assert [r["rank"] for r in result["ranking"]] == list(range(1, len(scores) + 1))
    assert {r["state"] for r in result["ranking"]} <= NEW_ENGLAND
    assert {"BOS", "BDL", "PVD", "MHT", "PWM", "BTV"} <= {r["iata"] for r in result["ranking"]}
    assert all(0 <= s <= 100 for s in scores)
    assert result["as_of"] == "Apr 2026"
    assert result["data_period"]["current"] == "May 2025 to Apr 2026"
    assert any("not physical terminal capacity" in c for c in result["caveats"])


async def test_regional_scores_equal_the_national_scores(analytics):
    regional = await analytics.rank("New England", None, 20, None)
    national = await analytics.rank(None, None, 300, None)
    national_scores = {r["iata"]: r["score"] for r in national["ranking"]}

    for row in regional["ranking"]:
        assert row["score"] == national_scores[row["iata"]]


async def test_components_show_value_percentile_and_weight(analytics):
    result = await analytics.rank("New England", None, 1, None)

    components = result["ranking"][0]["components"]

    assert set(components) == {
        "growth", "load_factor", "pax_per_runway", "demand_gap", "scale", "peak"
    }  # fmt: skip
    assert set(components["growth"]) == {"value", "percentile", "weight"}
    assert sum(c["weight"] for c in components.values()) == pytest.approx(1, abs=0.01)


async def test_reweighting_changes_the_weights_used_and_can_change_the_order(analytics):
    base = await analytics.rank("New England", None, 8, None)
    scale_only = await analytics.rank(
        "New England", None, 8,
        {"growth": 0, "load_factor": 0, "pax_per_runway": 0, "demand_gap": 0, "peak": 0},
    )  # fmt: skip

    assert scale_only["weights_used"]["scale"] == 1
    assert scale_only["ranking"][0]["iata"] == "BOS"  # biggest airport in New England
    assert [r["iata"] for r in base["ranking"]] != [r["iata"] for r in scale_only["ranking"]]


async def test_states_can_be_used_instead_of_a_region(analytics):
    result = await analytics.rank(None, ["ma"], 50, None)

    assert {r["state"] for r in result["ranking"]} == {"MA"}


async def test_unknown_region_and_bad_weights_are_clear_errors(analytics):
    with pytest.raises(ToolExecutionError) as region:
        await analytics.rank("Narnia", None, 5, None)
    with pytest.raises(ToolExecutionError) as weights:
        await analytics.rank(None, None, 5, {"speed": 1})

    assert region.value.code == "unknown_region"
    assert "New England" in region.value.message
    assert weights.value.code == "invalid_weights"


async def test_compare_lax_and_sna_reports_utilization_and_who_is_highest(analytics):
    result = await analytics.compare(["LAX", "SNA"])

    lax, sna = result["airports"]
    assert (lax["iata"], sna["iata"]) == ("LAX", "SNA")
    assert lax["runways"]["commercial"] > sna["runways"]["commercial"] >= 1
    comparison = result["comparison_by_metric"]
    assert comparison["departures_per_commercial_runway_per_day"]["highest"] == "LAX"
    assert comparison["passengers_per_commercial_runway_per_day"]["highest"] == "LAX"
    assert any("No delay history" in c for c in result["caveats"])
    assert any("all-cargo" in c for c in result["caveats"])


async def test_compare_needs_two_to_five_peer_airports(analytics):
    with pytest.raises(ToolExecutionError) as one:
        await analytics.compare(["LAX"])
    with pytest.raises(ToolExecutionError) as unknown:
        await analytics.compare(["LAX", "ZZZ"])

    assert one.value.code == "invalid_arguments"
    assert unknown.value.code == "airport_not_found"


async def test_distance_profile_for_anchorage_surfaces_that_international_flights_are_cargo(
    analytics,
):
    result = await analytics.distance("ANC")

    assert result["long_haul_share_pct"] is None
    assert "not computable" in result["long_haul_share_status"]
    assert result["international_departures_mostly_cargo"] is True
    assert result["seats_per_international_departure"] < 10  # about 4 seats: cargo
    assert result["proxies"]["international_share_of_departures_pct"] > 10
    assert any("mostly all-cargo flights" in c for c in result["caveats"])
    assert any("route-level" in c for c in result["caveats"])


async def test_distance_profile_for_a_passenger_airport_has_no_cargo_warning(analytics):
    result = await analytics.distance("BOS")

    assert result["international_departures_mostly_cargo"] is False
    assert not any("mostly all-cargo" in c for c in result["caveats"])


async def test_demand_pressure_for_sfo_has_signals_recovery_and_the_unmet_demand_caveat(analytics):
    result = await analytics.demand("SFO")

    assert result["months_load_factor_at_or_above_threshold"]["of_months"] == 12
    assert result["recovery_vs_2019"]["passengers_pct_of_2019"] > 0
    assert result["signals"] and all(isinstance(s, str) for s in result["signals"])
    assert any("Unmet demand is not measured" in c for c in result["caveats"])


async def test_profile_of_a_peer_has_traffic_and_score_and_of_a_small_airport_does_not(
    analytics, memory_repo
):
    small = next(a for a in await memory_repo.list_airports() if not a.has_traffic)

    peer = await analytics.profile("SFO")
    other = await analytics.profile(small.iata)

    assert peer["traffic"]["passengers"] > 0
    assert 0 <= peer["score"]["value"] <= 100
    assert other["traffic"] is None
    assert other["score"] is None
    assert "not in the peer set" in other["note"]


async def test_unknown_and_non_peer_airports_give_distinct_errors(analytics, memory_repo):
    small = next(a for a in await memory_repo.list_airports() if not a.has_traffic)

    with pytest.raises(ToolExecutionError) as unknown:
        await analytics.distance("ZZZ")
    with pytest.raises(ToolExecutionError) as non_peer:
        await analytics.demand(small.iata)

    assert unknown.value.code == "airport_not_found"
    assert non_peer.value.code == "not_in_peer_set"


async def test_search_resolves_the_names_in_the_assignment_questions(analytics):
    la = await analytics.search("LA", None, None, 3)
    santa_ana = await analytics.search("Santa Ana", None, None, 3)
    nowhere = await analytics.search("Atlantis", None, None, 3)

    assert la["matches"][0]["iata"] == "LAX"
    assert santa_ana["matches"][0]["iata"] == "SNA"
    assert nowhere["matches"] == [] and nowhere["note"]


async def test_live_status_distinguishes_active_programs_from_none_reported(analytics):
    delayed = await analytics.live("LAX")
    quiet = await analytics.live("SFO")

    assert delayed["live_status"] == "delay_programs"
    assert delayed["events"][0]["kind"] == "Ground Delay Programs"
    assert quiet["live_status"] == "no_reported_programs"
    assert quiet["events"] == []
    assert "FAA feed updated" in quiet["as_of"]
    assert any("not missing data" in c for c in quiet["caveats"])


async def test_a_closure_notice_alone_is_not_reported_as_a_delay_program(analytics):
    result = await analytics.live("BOS")

    assert result["live_status"] == "closure_notices_only"
    assert result["events"][0]["kind"] == "Airport Closures"
    assert any("no delay program" in c for c in result["caveats"])


async def test_live_status_failure_is_a_clean_tool_error(memory_repo):
    from domain.analytics import Analytics
    from domain.config import load_config
    from tests.conftest import DOMAIN

    broken = Analytics(memory_repo, FakeLiveStatus(fail=True), load_config(DOMAIN / "config.yaml"))

    with pytest.raises(ToolExecutionError) as error:
        await broken.live("LAX")

    assert error.value.code == "live_status_unavailable"


async def test_methodology_lists_weights_definitions_and_limits(analytics):
    everything = analytics.methodology("all")

    assert everything["score"]["weights"]["growth"] == 0.25
    assert {m["key"] for m in everything["metrics"]} >= {"growth", "demand_gap", "peak"}
    assert "long_haul" in everything["limits"]
    assert set(analytics.methodology("score")) == {"score"}


async def test_every_data_result_has_as_of_data_period_and_caveats(analytics):
    results = [
        await analytics.rank("New England", None, 3, None),
        await analytics.profile("BOS"),
        await analytics.compare(["BOS", "PVD"]),
        await analytics.distance("BOS"),
        await analytics.demand("BOS"),
        await analytics.search("Boston", None, None, 3),
    ]

    for result in results:
        assert result["as_of"] == "Apr 2026"
        assert result["data_period"]["current"] == "May 2025 to Apr 2026"
    for result in results[:5]:
        assert result["caveats"]
