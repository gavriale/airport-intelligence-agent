"""Scoring on three tiny airports whose KPIs and scores are worked out by hand.

Each airport has constant monthly values, so everything below is simple arithmetic.

                 prior (pax/mo, seats/mo)   current (pax/mo, seats/mo)   runways
    A            100, 150                   120, 150                     2
    B            200, 250                   220, 275                     1
    C             50, 100                    50, 100                     1

Last 12 months: A 1,440 pax, B 2,640, C 600.
  growth %        A 20   B 10   C 0          seat growth %   A 0   B 10   C 0
  demand gap      A 20   B 0    C 0          load factor %   A 80  B 80   C 50
  pax per runway  A 720  B 2640 C 600        peak ratio      all 1.0 (constant months)
Mid-rank percentiles with 3 airports: lowest 16.67, middle 50, highest 83.33, ties share.
  A: growth 83.33, LF 66.67, ppr 50, gap 83.33, scale 50, peak 50
  B: growth 50,    LF 66.67, ppr 83.33, gap 33.33, scale 83.33, peak 50
  C: growth 16.67, LF 16.67, ppr 16.67, gap 33.33, scale 16.67, peak 50
Weights .25 .25 .20 .15 .10 .05 give A = 67.5, B = 61.6667, C = 20.8333.
"""

from datetime import date

import pytest

from domain.repository import Airport, MonthlyTraffic
from domain.scoring import (
    COMPONENTS,
    build_national_scores,
    compute_kpis,
    make_windows,
    monthly_load_factor,
    normalize_weights,
    percentile,
    rank_airports,
    shift_month,
    weighted_score,
    window_label,
)

AS_OF = date(2026, 4, 1)
WINDOWS = make_windows(AS_OF)
WEIGHTS = {
    "growth": 0.25,
    "load_factor": 0.25,
    "pax_per_runway": 0.20,
    "demand_gap": 0.15,
    "scale": 0.10,
    "peak": 0.05,
}


def airport(iata: str, runways: int = 1) -> Airport:
    return Airport(
        iata=iata, ident="K" + iata, name=iata, city=iata, state="MA", latitude=0, longitude=0,
        elevation_ft=0, type="large_airport", scheduled_service=True, runway_count=runways,
        longest_runway_ft=9000 if runways else None, has_traffic=True,
    )  # fmt: skip


def month(iata: str, day: date, pax: int, seats: int) -> MonthlyTraffic:
    return MonthlyTraffic(
        iata=iata, month=day, departures=10, passengers=pax, seats=seats,
        domestic_departures=10, international_departures=0, international_seats=0,
        avg_flight_distance_mi=500.0, avg_domestic_distance_mi=500.0, freight_lbs=0,
    )  # fmt: skip


def series(iata, prior, current, *, skip=(), override=None):
    """24 months; `skip` removes months, `override` replaces a month's (pax, seats)."""
    rows = []
    for months, (pax, seats) in ((WINDOWS.prior, prior), (WINDOWS.current, current)):
        for day in months:
            if day in skip:
                continue
            p, s = (override or {}).get(day, (pax, seats))
            rows.append(month(iata, day, p, s))
    return rows


def kpis_for(iata, runways, prior, current, **kw):
    return compute_kpis(airport(iata, runways), series(iata, prior, current, **kw), WINDOWS)


@pytest.fixture
def three():
    return [
        kpis_for("A", 2, (100, 150), (120, 150)),
        kpis_for("B", 1, (200, 250), (220, 275)),
        kpis_for("C", 1, (50, 100), (50, 100)),
    ]


def test_windows_are_the_last_12_months_and_the_12_before():
    assert window_label(WINDOWS.current) == "May 2025 to Apr 2026"
    assert window_label(WINDOWS.prior) == "May 2024 to Apr 2025"
    assert len(WINDOWS.current) == len(WINDOWS.prior) == 12
    assert shift_month(date(2026, 1, 1), -1) == date(2025, 12, 1)


def test_kpis_match_the_hand_calculation(three):
    a = three[0]

    assert a.passengers == 1440
    assert a.passenger_growth_pct == pytest.approx(20)
    assert a.seat_growth_pct == pytest.approx(0)
    assert a.demand_gap_pts == pytest.approx(20)
    assert a.load_factor_pct == pytest.approx(80)
    assert a.passengers_per_runway == pytest.approx(720)
    assert a.peak_month_ratio == pytest.approx(1.0)
    assert a.flags == []


def test_percentile_uses_mid_rank_and_shares_ties():
    assert percentile(1, [1, 2, 3]) == pytest.approx(100 / 6)
    assert percentile(2, [1, 2, 3]) == pytest.approx(50)
    assert percentile(3, [1, 2, 3]) == pytest.approx(500 / 6)
    assert percentile(5, [5, 5, 1]) == pytest.approx((1 + 1) / 3 * 100)  # one below, two equal


def test_scores_match_the_hand_calculation(three):
    national = build_national_scores(three)

    scores = {i: weighted_score(c, WEIGHTS) for i, c in national.components.items()}

    assert scores["A"] == pytest.approx(67.5)
    assert scores["B"] == pytest.approx(61.6667, abs=1e-3)
    assert scores["C"] == pytest.approx(20.8333, abs=1e-3)
    assert national.reference_size == 3
    assert national.components["A"]["growth"].percentile == pytest.approx(83.3333, abs=1e-3)


def test_ranking_orders_by_score_and_numbers_the_ranks(three):
    ranking, not_scored = rank_airports(build_national_scores(three), ["C", "A", "B"], WEIGHTS)

    assert [(r.rank, r.iata) for r in ranking] == [(1, "A"), (2, "B"), (3, "C")]
    assert not_scored == {}


def test_regional_ranking_keeps_the_national_percentiles(three):
    national = build_national_scores(three)

    regional, _ = rank_airports(national, ["B", "C"], WEIGHTS)

    # If percentiles were recomputed inside {B, C}, B would score higher than 61.67.
    assert regional[0].iata == "B"
    assert regional[0].score == pytest.approx(61.6667, abs=1e-3)


def test_reweighting_changes_the_order_but_not_the_percentiles(three):
    national = build_national_scores(three)
    only_scale = normalize_weights(WEIGHTS, {c: 0 for c in COMPONENTS} | {"scale": 1})
    only_load_factor = normalize_weights(WEIGHTS, {c: 0 for c in COMPONENTS} | {"load_factor": 1})

    by_scale, _ = rank_airports(national, ["A", "B", "C"], only_scale)
    by_load, _ = rank_airports(national, ["A", "B", "C"], only_load_factor)

    assert [r.iata for r in by_scale] == ["B", "A", "C"]
    assert [r.iata for r in by_load] == ["B", "A", "C"]  # A and B tie; B has more passengers


def test_missing_month_in_the_prior_window_excludes_growth_and_flags_it():
    skipped = WINDOWS.prior[3]
    d = kpis_for("D", 1, (100, 150), (120, 150), skip={skipped})

    assert d.passenger_growth_pct is None
    assert d.seat_growth_pct is None
    assert d.demand_gap_pts is None
    assert d.passengers == 1440  # the current window is complete
    assert d.flags == ["missing_months_prior:1"]


def test_missing_month_in_the_current_window_excludes_full_year_metrics():
    d = kpis_for("D", 1, (100, 150), (120, 150), skip={WINDOWS.current[0]})

    assert d.passengers is None
    assert d.passengers_per_runway is None
    assert d.peak_month_ratio is None
    assert d.passenger_growth_pct is None
    assert "missing_months_current:1" in d.flags


def test_airports_with_missing_months_are_not_scored_and_do_not_change_other_scores(three):
    d = kpis_for("D", 1, (100, 150), (120, 150), skip={WINDOWS.prior[0]})

    national = build_national_scores([*three, d])

    assert "D" not in national.components
    assert "growth unavailable" in national.not_scored["D"]
    assert "missing_months_prior:1" in national.not_scored["D"]
    assert weighted_score(national.components["A"], WEIGHTS) == pytest.approx(67.5)
    ranking, not_scored = rank_airports(national, ["A", "D"], WEIGHTS)
    assert [r.iata for r in ranking] == ["A"]
    assert list(not_scored) == ["D"]


def test_zero_seat_month_is_undefined_not_zero():
    zero_month = WINDOWS.current[5]
    row = month("E", zero_month, 0, 0)
    e = kpis_for("E", 1, (100, 150), (120, 150), override={zero_month: (0, 0)})

    assert monthly_load_factor(row) is None
    assert e.load_factor_pct == pytest.approx(80)  # the other 11 months; not dragged toward 0
    assert "zero_seat_months:1" in e.flags


def test_airport_with_no_seats_at_all_has_no_load_factor_and_is_not_scored():
    f = kpis_for("F", 1, (100, 150), (0, 0))

    assert f.load_factor_pct is None
    assert "load_factor unavailable" in build_national_scores([f]).not_scored["F"]


def test_airport_without_runway_data_has_no_per_runway_metric():
    g = kpis_for("G", 0, (100, 150), (120, 150))

    assert g.passengers_per_runway is None
    assert "no_runway_data" in g.flags
    assert "G" not in build_national_scores([g]).components


def test_normalize_weights_rescales_overrides_to_sum_to_one():
    weights = normalize_weights(WEIGHTS, {"growth": 0.5})

    assert sum(weights.values()) == pytest.approx(1)
    assert weights["growth"] == pytest.approx(0.5 / 1.25)


@pytest.mark.parametrize("bad", [{"nope": 1.0}, {"growth": -1.0}])
def test_normalize_weights_rejects_unknown_or_negative(bad):
    with pytest.raises(ValueError):
        normalize_weights(WEIGHTS, bad)
