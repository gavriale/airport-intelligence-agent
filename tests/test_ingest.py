"""The ingest transforms, on tiny fixtures (no network)."""

from datetime import date

from scripts.ingest import (
    match_by_icao,
    months_between,
    peer_codes,
    runways_for,
    traffic_row,
    us_airports_with_iata,
)


def airport(**overrides) -> dict[str, str]:
    row = {
        "ident": "KAAA", "type": "medium_airport", "name": "Alpha", "latitude_deg": "41.0",
        "longitude_deg": "-71.0", "elevation_ft": "10", "iso_country": "US",
        "iso_region": "US-MA", "municipality": "Alphaville", "scheduled_service": "yes",
        "iata_code": "AAA",
    }  # fmt: skip
    return {**row, **overrides}


def runway(**overrides) -> dict[str, str]:
    row = {
        "airport_ident": "KAAA", "length_ft": "7000", "width_ft": "150", "surface": "ASP",
        "lighted": "1", "closed": "0", "le_ident": "04", "he_ident": "22",
    }  # fmt: skip
    return {**row, **overrides}


def test_airports_keep_only_us_with_iata_and_not_closed():
    rows = [
        airport(),
        airport(ident="KBBB", iata_code="", name="No code"),
        airport(ident="CYYZ", iata_code="YYZ", iso_country="CA", iso_region="CA-ON"),
        airport(ident="KCCC", iata_code="CCC", type="closed"),
    ]

    result = us_airports_with_iata(rows)

    assert [a["iata"] for a in result] == ["AAA"]
    assert result[0]["state"] == "MA"
    assert result[0]["city"] == "Alphaville"
    assert result[0]["scheduled_service"] is True


def test_duplicate_iata_keeps_the_larger_airport():
    rows = [
        airport(ident="KSMALL", type="small_airport", name="Small"),
        airport(ident="KBIG", type="large_airport", name="Big"),
    ]

    [result] = us_airports_with_iata(rows)

    assert result["ident"] == "KBIG"


def test_icao_match_keeps_the_bts_code_for_a_renamed_iata():
    rows = [airport(ident="KPBI", iata_code="DJT", name="West Palm Beach")]

    [result] = match_by_icao(rows, ["PBI", "ZZZ"])

    assert (result["iata"], result["ident"]) == ("PBI", "KPBI")


def test_runways_skip_closed_and_unknown_airports_and_join_the_ends():
    airports = us_airports_with_iata([airport()])
    rows = [
        runway(),
        runway(closed="1", le_ident="09", he_ident="27"),
        runway(airport_ident="KZZZ"),
        runway(le_ident="H1", he_ident="", length_ft="", lighted="0"),
    ]

    result = runways_for(rows, airports)

    assert [r["runway"] for r in result] == ["04/22", "H1"]
    assert result[1]["length_ft"] == ""
    assert result[1]["lighted"] is False


def test_peers_need_the_passenger_threshold_and_a_known_airport():
    ltm = {"AAA": 150_000.0, "BBB": 99_999.0, "CCC": 500_000.0}

    assert peer_codes(ltm, {"AAA", "BBB"}, 100_000) == ["AAA"]


def test_traffic_row_converts_and_treats_missing_fields_as_zero():
    raw = {
        "origin_airport_code": "ANC",
        "reporting_month": "2024-07-01T00:00:00.000",
        "total_departures": "9535",
        "total_passengers": "300000.0",
        "total_seats": "469074",
        "domestic_departures": "8331",
        "outbound_international": "1204",
        "total_distance_flight_sm": "1695.41048767698",
        "total_freight_lbs": "479309751",
    }  # no outbound_international_seats and no domestic distance: Socrata omits nulls

    row = traffic_row(raw)

    assert row["month"] == "2024-07-01"
    assert row["departures"] == row["domestic_departures"] + row["international_departures"]
    assert row["international_seats"] == 0
    assert row["avg_flight_distance_mi"] == 1695.4
    assert row["avg_domestic_distance_mi"] == ""


def test_months_between_crosses_year_boundaries_and_includes_both_ends():
    months = months_between(date(2025, 11, 1), date(2026, 2, 1))

    assert months == [date(2025, 11, 1), date(2025, 12, 1), date(2026, 1, 1), date(2026, 2, 1)]
