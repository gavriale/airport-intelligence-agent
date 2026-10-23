"""Ratios, commercial runways, passengers added and weight overrides in the analytics results."""

import pytest


async def test_compare_returns_the_ratios_so_the_model_does_not_compute_them(analytics):
    result = await analytics.compare(["LAX", "SNA"])
    lax, sna = result["airports"]
    per_day = result["comparison_by_metric"]["passengers_per_commercial_runway_per_day"]

    assert per_day["highest"] == "LAX" and per_day["lowest"] == "SNA"
    assert per_day["ratio_highest_to_lowest"] == pytest.approx(
        lax["passengers_per_commercial_runway_per_day"]
        / sna["passengers_per_commercial_runway_per_day"],
        abs=0.01,
    )
    growth = result["comparison_by_metric"]["passenger_growth_pct"]
    assert "ratio_highest_to_lowest" not in growth  # a ratio of growth rates means nothing
    assert growth["highest"] == "SNA" and growth["difference"] > 0


async def test_santa_ana_counts_one_commercial_runway_not_two(analytics):
    sna = (await analytics.profile("SNA"))["airport"]["runways"]

    assert sna["total"] == 2  # the second runway is a short general-aviation strip
    assert sna["commercial"] == 1
    assert sna["commercial_means"] == "open, paved, at least 5,000 ft long"
    assert sna["longest_ft"] == 5700


async def test_profiles_report_total_and_commercial_runways(analytics):
    bos = (await analytics.profile("BOS"))["airport"]["runways"]

    assert bos["total"] > bos["commercial"] >= 1


async def test_per_runway_figures_use_commercial_runways(analytics):
    sna = (await analytics.compare(["LAX", "SNA"]))["airports"][1]

    assert sna["commercial_runway_count"] == 1
    assert sna["passengers_per_commercial_runway"] == sna["passengers"]  # one runway


async def test_passengers_added_is_shown_beside_growth_but_is_not_in_the_score(analytics):
    ranking = (await analytics.rank("New England", None, 3, None))["ranking"]
    profile = await analytics.profile("BOS")
    compare = await analytics.compare(["LAX", "SNA"])
    lax, sna = compare["airports"]

    for row in ranking:
        assert isinstance(row["passengers_added"], int)
        assert "passengers_added" not in row["components"]
    assert profile["traffic"]["passengers_added"] is not None
    assert lax["passengers_added"] < 0 < sna["passengers_added"]


async def test_results_name_the_score_so_an_answer_can_use_the_name(analytics):
    ranking = await analytics.rank("New England", None, 3, None)
    profile = await analytics.profile("SFO")
    compare = await analytics.compare(["LAX", "SNA"])

    assert ranking["score_name"] == "Expansion Pressure Score"
    assert compare["score_name"] == "Expansion Pressure Score"
    assert profile["score"]["name"] == "Expansion Pressure Score"


async def test_the_profile_says_what_its_percentiles_are_compared_with(analytics):
    score = (await analytics.profile("SFO"))["score"]

    assert score["compared_with"] == "228 scored peer airports nationally"
    assert score["compared_with_airports"] == 228


async def test_a_partial_weight_override_is_applied_and_reported_by_the_code(analytics):
    result = await analytics.rank("New England", None, 3, {"growth": 0.6})

    used = result["weights_used"]
    assert used["growth"] == 0.6
    assert sum(used.values()) == pytest.approx(1, abs=0.002)
    assert used["load_factor"] == pytest.approx(0.25 / 0.75 * 0.4, abs=0.001)
