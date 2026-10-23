"""Sanity checks on the committed snapshot files (no database, no network)."""

import csv
import json
from collections import Counter
from datetime import date
from pathlib import Path

import pytest

from scripts.ingest import months_between

DATA = Path(__file__).resolve().parent.parent / "domain" / "data"
KEY_AIRPORTS = {"ANC": "AK", "SFO": "CA", "LAX": "CA", "SNA": "CA", "BOS": "MA"}
NEW_ENGLAND_STATES = {"CT", "MA", "ME", "NH", "RI", "VT"}


def read(name: str) -> list[dict[str, str]]:
    with (DATA / name).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="module")
def meta():
    return json.loads((DATA / "snapshot_meta.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def airports():
    return {r["iata"]: r for r in read("airports.csv")}


@pytest.fixture(scope="module")
def traffic():
    return read("airport_month.csv")


def test_meta_counts_match_the_files(meta, airports, traffic):
    assert meta["counts"]["airports"] == len(airports)
    assert meta["counts"]["runways"] == len(read("runways.csv"))
    assert meta["counts"]["traffic_rows"] == len(traffic)
    assert meta["counts"]["peers"] == len({r["iata"] for r in traffic})


def test_key_airports_are_present_in_the_right_state(airports):
    for iata, state in KEY_AIRPORTS.items():
        assert airports[iata]["state"] == state


def test_renamed_iata_airport_is_present_under_the_bts_code(airports, meta):
    assert "PBI" in airports
    assert meta["peer_codes_matched_by_icao"] == ["PBI"]
    assert "DJT" not in airports  # same airport, not listed twice


def test_new_england_has_its_main_airports(airports):
    peers = {r["iata"] for r in read("airport_month.csv")}
    assert {"BOS", "BDL", "PVD", "MHT", "PWM", "BTV"} <= peers
    assert {airports[c]["state"] for c in ("BOS", "BDL", "PVD", "MHT", "PWM", "BTV")} <= (
        NEW_ENGLAND_STATES
    )


def test_traffic_keys_are_unique_and_every_airport_exists(airports, traffic):
    keys = [(r["iata"], r["month"]) for r in traffic]

    assert len(keys) == len(set(keys))
    assert {r["iata"] for r in traffic} <= set(airports)


def test_traffic_months_are_within_the_snapshot_window(meta, traffic):
    latest = date.fromisoformat(meta["latest_period"])
    start = date.fromisoformat(meta["history_start"])

    months = {date.fromisoformat(r["month"]) for r in traffic}

    assert max(months) == latest
    assert min(months) >= start


def test_key_airports_have_every_month(meta, traffic):
    expected = {
        m.isoformat()
        for m in months_between(
            date.fromisoformat(meta["history_start"]), date.fromisoformat(meta["latest_period"])
        )
    }
    seen: dict[str, set[str]] = {}
    for r in traffic:
        seen.setdefault(r["iata"], set()).add(r["month"])

    for iata in KEY_AIRPORTS:
        assert seen[iata] == expected


def test_departures_equal_domestic_plus_international_on_every_row(traffic):
    bad = [
        r
        for r in traffic
        if int(r["departures"])
        != int(r["domestic_departures"]) + int(r["international_departures"])
    ]

    assert bad == []


def test_peers_meet_the_passenger_threshold(meta, traffic):
    latest = date.fromisoformat(meta["latest_period"])
    ltm_start = date(latest.year - 1, latest.month, 1)
    ltm: Counter = Counter()
    for r in traffic:
        if date.fromisoformat(r["month"]) > ltm_start:
            ltm[r["iata"]] += int(r["passengers"])

    assert min(ltm.values()) >= meta["peer_min_annual_passengers"]


def test_key_airports_have_runways():
    runway_counts = Counter(r["airport_iata"] for r in read("runways.csv"))

    for iata in KEY_AIRPORTS:
        assert runway_counts[iata] >= 1


def test_anchorage_international_departures_are_mostly_cargo(traffic):
    """Documents the cargo caveat: ANC international flights carry very few seats."""
    anc = [r for r in traffic if r["iata"] == "ANC" and r["month"] >= "2025-05-01"]
    intl_departures = sum(int(r["international_departures"]) for r in anc)
    intl_seats = sum(int(r["international_seats"]) for r in anc)

    assert intl_departures > 5_000
    assert intl_seats / intl_departures < 10  # a passenger jet has well over 100 seats
