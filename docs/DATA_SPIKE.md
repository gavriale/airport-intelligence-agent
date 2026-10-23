# Data spike

Run on 2026-10-23 from the developer machine, before any code for the airport assignment. Nothing here is guessed: where a check was not completed it says so.

## Summary

| # | Source | Works? | Auth | Latest period | Usable for |
|---|---|---|---|---|---|
| 1 | BTS T-100 summary by origin airport (Socrata `r495-tyji`) | yes | none | **April 2026** (monthly, back to Jan 2014) | traffic, load factor, growth, average stage length, domestic vs international departures |
| 2 | Route-level or carrier-by-airport T-100 | **not found** (see below) | n/a | n/a | long-haul share and carrier concentration cannot be computed exactly |
| 3 | OurAirports `airports.csv`, `runways.csv` | reachable, contents **not verified** | none | rolling | state, coordinates, IATA, runways (to confirm at ingest) |
| 4 | OpenSky departures (PANC) | partly | anonymous: last ~6 h only | live | not usable |
| 5 | FAA NAS airport status | yes | none | live snapshot | current delay programs and closures only |

## 1. BTS T-100 summary by origin airport

- Endpoint: `https://data.bts.gov/resource/r495-tyji.json` (Socrata). No key; I sent no app token and saw no throttling.
- 131,739 rows, 2,091 airports, one row per airport per month, 2014-01 to **2026-04**. Maximum 50,000 rows per request.
- Sample, April 2026:
  - ANC: 5,412 departures, 166,273 passengers, 240,245 seats, 69.2% load factor, 1,999 mi average flight distance.
  - SFO: 15,753 departures, 2,147,010 passengers, 2,669,813 seats, 80.4% load factor, 1,881 mi.
- The filtered query for SFO, LAX, SNA, ANC, BOS returned 20 months each (Sep 2024 to Apr 2026). The cutoff date I used was 4 months too late; 24 months is `2024-05` to `2026-04`. Values for LAX, SNA and BOS were not printed.
- **`total_distance_flight_sm` is an average per departure, not a sum.** The column descriptions in the metadata are empty, so this is inferred from the data:
  - The `*_flight` columns equal totals divided by departures. SFO April 2026: 2,147,010 / 15,753 = 136.29, which is exactly `total_passengers_flight`. Seats work the same way.
  - A row with 1 departure and a row with 2 departures both show 30 mi.
  - `total_distance_passenger` is the average distance per passenger.
- Includes international traffic: the `domestic_*` columns are a subset of the `total_*` columns, and `outbound_international_*` / `inbound_international_*` exist.
- **Includes cargo (inferred, to be confirmed at ingest).** 2024 sums for ANC: 93,961 departures, 2.74 M passengers and 5.77 billion lb of freight. That freight volume cannot be carried in passenger bellies. See "Cargo" below.

## 2. Carrier or route-level data

Searched the data.bts.gov catalog (39 datasets matched for T-100, segment, market, carrier, origin destination, airline).

- `q4tb-tbff` (T100 Segment Summary By Carrier) has a `carrier` field but is nationwide, not per airport.
- `bu82-4pwz`, `jqx4-4iha`, `56rv-9p75` are national, monthly or by-country aggregates.
- `33as-hyfa` has origin, destination, carrier and flight counts, but only Jan to Mar 2022 (31,740 rows) and no distance.
- **ArcGIS NTAD service** (`services.arcgis.com/xOi1kZaI0eWDREZv/.../T100_Domestic_Market_and_Segment_Data/FeatureServer`), checked after the first report: a single table (id 1, 1,279 rows) with one row per origin airport for **2024 only**: `year, origin, enplanements, passengers, departures, arrivals, freight, mail`. **No destination and no distance, so it is not route-level.** Its domestic departures match the Socrata domestic departures closely (SFO 138,571 vs 138,828; LAX 206,637 vs 208,824; ANC 71,765 vs 79,667), which suggests it is the domestic slice of the same data. Useful only as a cross-check.
- Not used, by decision: the BTS On-Time Reporting Carrier files (`transtats.bts.gov/PREZIP/...`). They exist as monthly ZIPs of about 27 to 33 MB, latest **August 2026** (published 2026-10-19), and are a **bulk download, not an API**. Not downloaded or parsed here. Decision: out of scope, because they cover domestic passenger carriers only and ANC's long-haul traffic is mostly international cargo.

**Consequence.** The exact share of long-haul flights out of ANC cannot be computed. We can report a lower bound from international departures plus the average stage length, and say so.

## 3. OurAirports

- `https://raw.githubusercontent.com/davidmegginson/ourairports-data/main/airports.csv` (12.75 MB) and `runways.csv` (3.97 MB): both HTTP 200, no auth.
- **Not verified:** a download I started was stopped, so I did not read the contents. From the published format I expect `iata_code`, `iso_region` (US state), `latitude_deg`, `longitude_deg`, `type`, `scheduled_service` in airports and `airport_ident`, `length_ft`, `closed` in runways. Confirm at ingest.

## 4. OpenSky (PANC departures)

- Anonymous requests work for the **last ~6 hours only**. Windows of 12, 24 and 48 hours return 403 "You cannot access historical flights".
- Rate limit: `X-Rate-Limit-Remaining: 399` after a few calls, so about 400 credits a day anonymously.
- Destination airport: **mostly empty**. Last 6 hours at PANC: 19 departures, 1 with a destination (5%).
- Historical access needs an account (OAuth2). The auth server responds; an authenticated call was not tested.
- Verdict: not usable for this assignment.

## 5. FAA airport status (live delays)

- `https://nasstatus.faa.gov/api/airport-status-information`: HTTP 200, XML, no auth, about 1.8 KB at the time.
- It lists **only airports with an active program** (ground delay, closure). At the check it showed LAS (rain, ground delay) and two closures (ALO, and a general-aviation-only restriction at LAX). **An airport missing from the list means no reported delay, not missing data.**
- Live snapshot only, no history.
- A second FAA endpoint (`soa.smext.faa.gov/asws/...`) did not resolve from this machine.

## Cargo

The T-100 summary appears to include all-cargo flights (ANC freight is 5.77 billion lb a year). To be confirmed during ingest and stated in the docs. How each planned metric treats cargo:

| Metric | Cargo effect |
|---|---|
| Passengers, growth in passengers | none: cargo flights carry no passengers |
| Load factor (passengers / seats) | none: cargo flights add no seats |
| Seats, seat growth | none |
| Departures, departures per runway | **included**: cargo flights use runways, so this is the right measure of runway pressure, but it overstates passenger-service activity |
| Average seats per departure | **biased low** at cargo hubs (ANC) |
| Average flight distance, international share | **dominated by cargo** at ANC: these describe all departures, not passenger flights |

## Decisions taken after the spike

1. No On-Time ingest. Long-haul share is a **lower bound**: international departures divided by total departures, with the average stage length alongside. Assumption: every international departure from ANC is long-haul (Canadian departures are the exception). Domestic flights over 3,000 mi are unknown.
2. A snapshot of the data is loaded into Postgres at startup (filtered to peer airports so it is small enough to commit), and `make ingest` refreshes it from the APIs.
3. Escalation is removed entirely.
4. Percentiles are computed against national peers. Regional queries rank within the region using those national percentiles.
5. Demand gap = passenger growth minus seat growth. Weights: growth 0.25, load factor 0.25, pax per runway 0.20, demand gap 0.15, scale 0.10, peak 0.05. They live in config.
6. `search_knowledge` is replaced by `get_methodology`, which returns definitions and weights from config. The BM25 index is removed.
