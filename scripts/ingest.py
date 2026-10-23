"""Builds the committed data snapshot from public sources: `python -m scripts.ingest`.

Sources: BTS T-100 summary by origin airport (Socrata) and OurAirports (GitHub CSVs).
Output (domain/data/): airports.csv, runways.csv, airport_month.csv, snapshot_meta.json.

Peer airports are those with at least PEER_MIN_ANNUAL_PASSENGERS passengers in the latest
12 months; traffic is kept only for peers. Airport and runway rows cover every US airport
with an IATA code.
"""

import csv
import http.client
import json
import sys
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

BTS_URL = "https://data.bts.gov/resource/r495-tyji.json"
OURAIRPORTS_URL = "https://raw.githubusercontent.com/davidmegginson/ourairports-data/main"
OUT_DIR = Path(__file__).resolve().parent.parent / "domain" / "data"

PEER_MIN_ANNUAL_PASSENGERS = 100_000
HISTORY_START = date(2019, 1, 1)  # keeps a pre-pandemic baseline
PAGE_SIZE = 10_000  # smaller than the Socrata maximum (50,000): big pages get cut off mid-stream
HTTP_TIMEOUT_S = 120
HTTP_ATTEMPTS = 3
BTS_COLUMNS = (
    "origin_airport_code, reporting_month, total_departures, total_passengers, total_seats, "
    "domestic_departures, outbound_international, outbound_international_seats, "
    "total_distance_flight_sm, domestic_distance_flight, total_freight_lbs"
)

AIRPORT_FIELDS = [
    "iata", "ident", "name", "city", "state", "latitude", "longitude",
    "elevation_ft", "type", "scheduled_service",
]  # fmt: skip
RUNWAY_FIELDS = ["airport_iata", "runway", "length_ft", "width_ft", "surface", "lighted"]
TRAFFIC_FIELDS = [
    "iata", "month", "departures", "passengers", "seats", "domestic_departures",
    "international_departures", "international_seats", "avg_flight_distance_mi",
    "avg_domestic_distance_mi", "freight_lbs",
]  # fmt: skip
TYPE_RANK = {"large_airport": 0, "medium_airport": 1, "small_airport": 2}


# ---------- pure transforms (unit tested) ----------


def _airport_dict(row: dict[str, str], iata: str) -> dict[str, Any]:
    return {
        "iata": iata,
        "ident": row["ident"],
        "name": row["name"],
        "city": row["municipality"],
        "state": row["iso_region"].removeprefix("US-"),
        "latitude": row["latitude_deg"],
        "longitude": row["longitude_deg"],
        "elevation_ft": row["elevation_ft"],
        "type": row["type"],
        "scheduled_service": row["scheduled_service"] == "yes",
    }


def us_airports_with_iata(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    """One row per IATA code. If a code appears twice, the larger airport type wins."""
    best: dict[str, dict[str, str]] = {}
    for row in rows:
        iata = row["iata_code"].strip().upper()
        if row["iso_country"] != "US" or not iata or row["type"] == "closed":
            continue
        rank = TYPE_RANK.get(row["type"], 9)
        if iata not in best or rank < TYPE_RANK.get(best[iata]["type"], 9):
            best[iata] = row
    return [_airport_dict(row, iata) for iata, row in sorted(best.items())]


def match_by_icao(rows: list[dict[str, str]], codes: list[str]) -> list[dict[str, Any]]:
    """BTS keeps old IATA codes when OurAirports changes them (PBI is now DJT there).
    For such codes, find the airport by its US ICAO identifier (K + code) and keep the BTS code."""
    by_ident = {r["ident"]: r for r in rows if r["iso_country"] == "US" and r["type"] != "closed"}
    return [_airport_dict(by_ident["K" + c], c) for c in sorted(codes) if "K" + c in by_ident]


def runways_for(rows: list[dict[str, str]], airports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Open runways of the given airports. One OurAirports row is one physical runway."""
    iata_by_ident = {a["ident"]: a["iata"] for a in airports}
    out = []
    for row in rows:
        iata = iata_by_ident.get(row["airport_ident"])
        if iata is None or row["closed"] == "1":
            continue
        out.append(
            {
                "airport_iata": iata,
                "runway": f"{row['le_ident']}/{row['he_ident']}".strip("/"),
                "length_ft": row["length_ft"],
                "width_ft": row["width_ft"],
                "surface": row["surface"],
                "lighted": row["lighted"] == "1",
            }
        )
    return sorted(out, key=lambda r: (r["airport_iata"], r["runway"]))


def peer_codes(ltm_passengers: dict[str, float], known_iatas: set[str], minimum: int) -> list[str]:
    """Airports above the passenger threshold that also exist in OurAirports with an IATA code."""
    return sorted(c for c, pax in ltm_passengers.items() if pax >= minimum and c in known_iatas)


def _count(raw: dict[str, str], key: str) -> int:
    """Socrata leaves out fields that are null, so a missing count is zero."""
    return round(float(raw.get(key) or 0))


def _distance(raw: dict[str, str], key: str) -> float | str:
    """Average distances are blank (unknown) when there were no flights to average."""
    return round(float(raw[key]), 1) if raw.get(key) else ""


def traffic_row(raw: dict[str, str]) -> dict[str, Any]:
    """One BTS monthly row. `total` = domestic + outbound international (checked on ANC)."""
    return {
        "iata": raw["origin_airport_code"],
        "month": raw["reporting_month"][:10],
        "departures": _count(raw, "total_departures"),
        "passengers": _count(raw, "total_passengers"),
        "seats": _count(raw, "total_seats"),
        "domestic_departures": _count(raw, "domestic_departures"),
        "international_departures": _count(raw, "outbound_international"),
        "international_seats": _count(raw, "outbound_international_seats"),
        "avg_flight_distance_mi": _distance(raw, "total_distance_flight_sm"),
        "avg_domestic_distance_mi": _distance(raw, "domestic_distance_flight"),
        "freight_lbs": _count(raw, "total_freight_lbs"),
    }


def months_between(start: date, end: date) -> list[date]:
    months, current = [], date(start.year, start.month, 1)
    while current <= end:
        months.append(current)
        current = date(current.year + (current.month == 12), current.month % 12 + 1, 1)
    return months


# ---------- network ----------


def _get(url: str) -> bytes:
    """GET with a few attempts: public endpoints sometimes cut a response short."""
    request = urllib.request.Request(url, headers={"User-Agent": "airport-agent-ingest/1.0"})
    for attempt in range(1, HTTP_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_S) as response:
                return response.read()
        except (OSError, http.client.HTTPException):
            if attempt == HTTP_ATTEMPTS:
                raise
    raise AssertionError("unreachable")


def _soql(**params: Any) -> list[dict[str, str]]:
    return json.loads(_get(BTS_URL + "?" + urllib.parse.urlencode(params)))


def _csv_rows(name: str) -> list[dict[str, str]]:
    text = _get(f"{OURAIRPORTS_URL}/{name}").decode("utf-8")
    return list(csv.DictReader(text.splitlines()))


def fetch_bts_latest_month() -> date:
    [row] = _soql(**{"$select": "max(reporting_month) as latest"})
    return date.fromisoformat(row["latest"][:10])


def fetch_bts_ltm_passengers(latest: date) -> dict[str, float]:
    start = months_between(date(latest.year - 1, latest.month, 1), latest)[1]
    rows = _soql(
        **{
            "$select": "origin_airport_code, sum(total_passengers) as pax",
            "$where": f"reporting_month >= '{start.isoformat()}T00:00:00'",
            "$group": "origin_airport_code",
            "$limit": PAGE_SIZE,
        }
    )
    return {r["origin_airport_code"]: float(r["pax"]) for r in rows}


def fetch_bts_traffic(codes: list[str]) -> list[dict[str, str]]:
    quoted = ",".join(f"'{c}'" for c in codes)
    where = (
        f"origin_airport_code in ({quoted}) "
        f"and reporting_month >= '{HISTORY_START.isoformat()}T00:00:00'"
    )
    rows: list[dict[str, str]] = []
    while True:
        page = _soql(
            **{
                "$select": BTS_COLUMNS,
                "$where": where,
                "$order": "origin_airport_code, reporting_month",
                "$limit": PAGE_SIZE,
                "$offset": len(rows),
            }
        )
        rows += page
        if len(page) < PAGE_SIZE:
            return rows


# ---------- output ----------


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {k: ("true" if v is True else "false" if v is False else v) for k, v in row.items()}
            )


def main() -> None:
    print("Downloading OurAirports ...")
    airport_rows = _csv_rows("airports.csv")
    airports = us_airports_with_iata(airport_rows)

    print("Querying BTS T-100 ...")
    latest = fetch_bts_latest_month()
    ltm = fetch_bts_ltm_passengers(latest)
    big = [c for c, pax in ltm.items() if pax >= PEER_MIN_ANNUAL_PASSENGERS]
    known = {a["iata"] for a in airports}
    aliased = match_by_icao(airport_rows, [c for c in big if c not in known])
    replaced = {a["ident"] for a in aliased}  # the same airport under its new IATA code
    airports = sorted(
        [a for a in airports if a["ident"] not in replaced] + aliased, key=lambda a: a["iata"]
    )
    runways = runways_for(_csv_rows("runways.csv"), airports)
    peers = peer_codes(ltm, {a["iata"] for a in airports}, PEER_MIN_ANNUAL_PASSENGERS)
    unmatched = sorted(set(big) - set(peers))
    traffic = sorted(
        (traffic_row(r) for r in fetch_bts_traffic(peers)), key=lambda r: (r["iata"], r["month"])
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_csv(OUT_DIR / "airports.csv", AIRPORT_FIELDS, airports)
    _write_csv(OUT_DIR / "runways.csv", RUNWAY_FIELDS, runways)
    _write_csv(OUT_DIR / "airport_month.csv", TRAFFIC_FIELDS, traffic)

    expected = months_between(HISTORY_START, latest)
    present = defaultdict(set)
    for r in traffic:
        present[r["iata"]].add(r["month"])
    incomplete = {
        c: len(expected) - len(present[c]) for c in peers if len(present[c]) < len(expected)
    }
    meta = {
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "latest_period": latest.isoformat(),
        "history_start": HISTORY_START.isoformat(),
        "peer_min_annual_passengers": PEER_MIN_ANNUAL_PASSENGERS,
        "sources": {"bts_t100_origin_airport": BTS_URL, "ourairports": OURAIRPORTS_URL},
        "counts": {
            "airports": len(airports),
            "runways": len(runways),
            "peers": len(peers),
            "traffic_rows": len(traffic),
        },
        "peer_codes_matched_by_icao": [a["iata"] for a in aliased],
        "peers_missing_months": incomplete,
        "peers_without_ourairports_match": unmatched,
    }
    with (OUT_DIR / "snapshot_meta.json").open("w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(meta, indent=2) + "\n")

    print(f"Latest period {latest}; {len(airports)} airports, {len(runways)} runways.")
    print(
        f"{len(peers)} peers (>= {PEER_MIN_ANNUAL_PASSENGERS:,} passengers in the last 12 months),"
    )
    print(f"{len(traffic)} traffic rows. Peers with missing months: {len(incomplete)}.")
    if aliased:
        print(
            "Matched by ICAO code (IATA differs in OurAirports):",
            ", ".join(a["iata"] for a in aliased),
        )
    if unmatched:
        print("Peers dropped (not a US airport in OurAirports):", ", ".join(unmatched))
    print(Counter(a["state"] for a in airports).most_common(5))


if __name__ == "__main__":
    sys.exit(main())
