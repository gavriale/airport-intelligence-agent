"""Search, distance profile and demand signals on small hand-made data."""

from datetime import date

import pytest

from adapters.faa_status import parse_status
from domain.live_status import LiveStatusUnavailable
from domain.metrics import demand_signals, distance_profile
from domain.repository import Airport, MonthlyTraffic
from domain.scoring import compute_kpis, make_windows
from domain.search import search_airports

ALIASES = {"la": ["LAX"], "nyc": ["JFK", "LGA"]}


def airport(iata, city, name, *, type="large_airport", traffic=True):
    return Airport(
        iata=iata, ident="K" + iata, name=name, city=city, state="CA", latitude=0, longitude=0,
        elevation_ft=0, type=type, scheduled_service=True, runway_count=1,
        longest_runway_ft=8000, has_traffic=traffic,
    )  # fmt: skip


AIRPORTS = [
    airport("LAX", "Los Angeles", "Los Angeles International Airport"),
    airport("SNA", "Santa Ana", "John Wayne Orange County International Airport"),
    airport("BUR", "Burbank", "Hollywood Burbank Airport", type="medium_airport"),
    airport("BOS", "Boston", "Boston Logan International Airport"),
    airport("XXX", "Boston", "Tiny Boston Strip", type="small_airport", traffic=False),
]


def test_search_resolves_a_common_name_through_the_alias():
    [(first, why), *_] = search_airports(AIRPORTS, "LA", ALIASES)

    assert (first.iata, why) == ("LAX", "common name")


def test_search_finds_a_city_and_an_iata_code_and_a_name():
    assert search_airports(AIRPORTS, "Santa Ana", ALIASES)[0][0].iata == "SNA"
    assert search_airports(AIRPORTS, "sna", ALIASES)[0][0].iata == "SNA"
    assert search_airports(AIRPORTS, "Orange County", ALIASES)[0][0].iata == "SNA"


def test_search_prefers_the_airport_with_traffic_data_when_matches_tie():
    iatas = [a.iata for a, _ in search_airports(AIRPORTS, "Boston", ALIASES)]

    assert iatas == ["BOS", "XXX"]


def test_search_returns_nothing_for_noise_or_unknown_text():
    assert search_airports(AIRPORTS, "airport", ALIASES) == []
    assert search_airports(AIRPORTS, "Atlantis", ALIASES) == []


# ---------- distance profile ----------


def traffic(day, **overrides):
    row = dict(
        iata="ANC", month=day, departures=100, passengers=1000, seats=10000,
        domestic_departures=80, international_departures=20, international_seats=40,
        avg_flight_distance_mi=1000.0, avg_domestic_distance_mi=500.0, freight_lbs=5000,
    )  # fmt: skip
    return MonthlyTraffic(**{**row, **overrides})


def test_distance_profile_matches_the_hand_calculation():
    rows = [traffic(date(2026, 3, 1)), traffic(date(2026, 4, 1))]

    p = distance_profile(rows, cargo_seat_threshold=20)

    assert p["departures"] == 200
    assert p["international_share_pct"] == pytest.approx(20)
    assert p["avg_flight_distance_mi"] == pytest.approx(1000)
    # total miles 1000*100 = domestic 500*80 + international x*20  ->  x = 3000
    assert p["avg_international_distance_mi"] == pytest.approx(3000)
    assert p["seats_per_international_departure"] == pytest.approx(2)  # 40 seats / 20 flights
    assert p["seats_per_domestic_departure"] == pytest.approx((10000 - 40) / 80)
    assert p["international_mostly_cargo"] is True
    assert p["freight_lbs"] == 10000


def test_international_flights_with_many_seats_are_not_flagged_as_cargo():
    rows = [traffic(date(2026, 4, 1), international_seats=3000)]  # 150 seats per flight

    assert distance_profile(rows, 20)["international_mostly_cargo"] is False


def test_distance_profile_of_an_airport_without_international_flights():
    rows = [traffic(date(2026, 4, 1), international_departures=0, domestic_departures=100)]

    p = distance_profile(rows, 20)

    assert p["international_share_pct"] == 0
    assert p["seats_per_international_departure"] is None
    assert p["international_mostly_cargo"] is False


# ---------- demand signals ----------

WINDOWS = make_windows(date(2026, 4, 1))


def history(current_lf_by_month, *, with_2019=True):
    """Current months get the given load factors (seats 1000); 2019 is 1000 pax, 1200 seats."""
    rows = []
    for day, lf in zip(WINDOWS.current, current_lf_by_month, strict=True):
        rows.append(traffic(day, passengers=int(lf * 10), seats=1000, departures=10))
    for day in WINDOWS.prior:
        rows.append(traffic(day, passengers=800, seats=1000, departures=10))
    if with_2019:
        rows += [
            traffic(date(2019, m, 1), passengers=1000, seats=1200, departures=10)
            for m in range(1, 13)
        ]
    return rows


def test_demand_signals_count_full_months_and_recovery_against_2019():
    lfs = [90, 90, 90, 80, 80, 80, 80, 80, 80, 80, 80, 95]  # three at 90, one at 95
    rows = history(lfs)
    airport_ = airport("SFO", "San Francisco", "San Francisco International Airport")
    kpis = compute_kpis(airport_, rows, WINDOWS)

    s = demand_signals(rows, kpis, WINDOWS, high_load_factor_pct=85)

    assert s["months_at_or_above_threshold"] == 4
    assert s["months_considered"] == 12
    assert s["peak_load_factor_pct"] == pytest.approx(95)
    assert s["peak_load_factor_month"] == "Apr 2026"
    # current passengers = (270+480+95*10... computed from the load factors, seats 12,000
    expected_pax = sum(int(lf * 10) for lf in lfs)
    assert s["recovery_vs_2019"]["passengers_pct_of_2019"] == pytest.approx(
        100 * expected_pax / 12000
    )
    assert s["recovery_vs_2019"]["seats_pct_of_2019"] == pytest.approx(100 * 12000 / 14400)


def test_recovery_is_withheld_when_the_2019_baseline_is_incomplete():
    rows = history([80] * 12, with_2019=False)
    kpis = compute_kpis(airport("SFO", "x", "x"), rows, WINDOWS)

    s = demand_signals(rows, kpis, WINDOWS, 85)

    assert s["recovery_vs_2019"] is None
    assert "incomplete" in s["recovery_note"]


# ---------- FAA feed ----------

FAA_XML = """<AIRPORT_STATUS_INFORMATION><Update_Time>Fri Oct 23 06:42:01 2026 GMT</Update_Time>
<Delay_type><Name>Ground Delay Programs</Name><Ground_Delay_List><Ground_Delay>
<ARPT>LAS</ARPT><Reason>rain</Reason><Avg>1 hour and 37 minutes</Avg>
</Ground_Delay></Ground_Delay_List></Delay_type>
<Delay_type><Name>Airport Closures</Name><Airport_Closure_List><Airport><ARPT>LAX</ARPT>
<Reason>!LAX AD AP CLSD TO NON SKED TRANSIENT GA ACFT</Reason></Airport></Airport_Closure_List>
</Delay_type></AIRPORT_STATUS_INFORMATION>"""


def test_faa_feed_is_parsed_into_events_per_airport():
    status = parse_status(FAA_XML)

    assert status.updated == "Fri Oct 23 06:42:01 2026 GMT"
    assert set(status.events) == {"LAS", "LAX"}
    assert status.events["LAS"][0].kind == "Ground Delay Programs"
    assert status.events["LAS"][0].details["Reason"] == "rain"
    assert "SFO" not in status.events  # absent means no active program


def test_a_broken_faa_feed_is_reported_as_unavailable():
    with pytest.raises(LiveStatusUnavailable):
        parse_status("<html>not the feed")
