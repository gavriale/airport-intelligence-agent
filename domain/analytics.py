"""The airport analyses behind the tools and the /ranking endpoint.

Reads the repository, applies the pure functions in scoring.py and metrics.py, and returns
plain dictionaries. Every result carries `as_of`, the data window and a list of caveats.
Nothing here calls a model.
"""

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from core.errors import ToolExecutionError
from domain.config import Config
from domain.live_status import LiveStatusProvider, LiveStatusUnavailable
from domain.metrics import demand_signals, distance_profile
from domain.repository import Airport, AirportRepository, MonthlyTraffic, SnapshotInfo
from domain.runways import RULE_TEXT
from domain.scoring import (
    COMPONENTS,
    Kpis,
    NationalScores,
    Windows,
    build_national_scores,
    compute_kpis,
    make_windows,
    month_label,
    normalize_weights,
    rank_airports,
    weighted_score,
    window_label,
)
from domain.search import search_airports

DAYS_PER_YEAR = 365
MAX_COMPARE = 5
SCORE_RANGE = "0 to 100"
CLOSURE_KIND = "Airport Closures"  # the FAA feed's name for closure notices
RATIO_METRICS = (
    "passengers",
    "departures_per_commercial_runway_per_day",
    "passengers_per_commercial_runway_per_day",
    "load_factor_pct",
    "peak_month_ratio",
)
DIFFERENCE_METRICS = ("passenger_growth_pct", "seat_growth_pct", "demand_gap_pts")


def _round(value: float | None, digits: int = 1) -> float | None:
    """Round for display; `+ 0.0` turns a negative zero into a plain zero."""
    return None if value is None else round(value, digits) + 0.0


@dataclass(frozen=True)
class _Snapshot:
    info: SnapshotInfo
    windows: Windows
    airports: dict[str, Airport]  # peer airports only
    traffic: dict[str, list[MonthlyTraffic]]
    kpis: dict[str, Kpis]
    national: NationalScores


class Analytics:
    def __init__(
        self, repository: AirportRepository, live_status: LiveStatusProvider, config: Config
    ) -> None:
        self._repository = repository
        self._live_status = live_status
        self._config = config
        self._snapshot: _Snapshot | None = None
        self._lock = asyncio.Lock()

    # ---------- loading ----------

    async def _load(self) -> _Snapshot:
        """The national KPI table is computed once; the snapshot does not change while running."""
        async with self._lock:
            if self._snapshot is None:
                info = await self._repository.get_snapshot_info()
                airports = {
                    a.iata: a for a in await self._repository.list_airports(peers_only=True)
                }
                traffic: dict[str, list[MonthlyTraffic]] = {}
                for row in await self._repository.get_traffic():
                    traffic.setdefault(row.iata, []).append(row)
                windows = make_windows(info.latest_period, self._config.scoring.window_months)
                kpis = {i: compute_kpis(a, traffic[i], windows) for i, a in airports.items()}
                national = build_national_scores(list(kpis.values()))
                self._snapshot = _Snapshot(info, windows, airports, traffic, kpis, national)
            return self._snapshot

    async def _airport(self, iata: str) -> Airport:
        found = await self._repository.list_airports(iatas=[iata.upper()])
        if not found:
            raise ToolExecutionError(
                "airport_not_found",
                f"No airport with IATA code {iata.upper()}. Use search_airports to find it.",
            )
        return found[0]

    async def _peer(self, iata: str) -> tuple[_Snapshot, Airport]:
        snap = await self._load()
        airport = await self._airport(iata)
        if airport.iata not in snap.airports:
            raise ToolExecutionError(
                "not_in_peer_set",
                f"{airport.iata} is not in the peer set (under "
                f"{snap.info.peer_min_annual_passengers:,} passengers in the last 12 months), "
                "so there is no traffic analysis for it.",
            )
        return snap, airport

    def _caveats(self, snap: _Snapshot, groups: Sequence[str], **fmt: Any) -> list[str]:
        texts = [t for g in groups for t in self._config.caveats[g]]
        return [t.format(as_of=month_label(snap.info.latest_period), **fmt) for t in texts]

    def _envelope(self, snap: _Snapshot, payload: dict, groups: Sequence[str], **fmt: Any) -> dict:
        return {
            "as_of": month_label(snap.info.latest_period),
            "data_period": {
                "current": window_label(snap.windows.current),
                "compared_with": window_label(snap.windows.prior),
            },
            **payload,
            "caveats": self._caveats(snap, groups, **fmt),
        }

    def _states(self, region: str | None, states: Sequence[str] | None) -> list[str] | None:
        if region:
            by_name = {name.lower(): codes for name, codes in self._config.regions.items()}
            if region.lower() not in by_name:
                raise ToolExecutionError(
                    "unknown_region",
                    f"Unknown region {region!r}. Known regions: {sorted(self._config.regions)}. "
                    "You can also pass state codes.",
                )
            return by_name[region.lower()]
        return [s.upper() for s in states] if states else None

    # ---------- shaping ----------

    @staticmethod
    def _airport_summary(a: Airport) -> dict:
        return {
            "iata": a.iata,
            "name": a.name,
            "city": a.city,
            "state": a.state,
            "in_peer_set": a.has_traffic,
        }

    @staticmethod
    def _kpi_summary(k: Kpis) -> dict:
        runway_days = (
            DAYS_PER_YEAR * k.commercial_runway_count if k.commercial_runway_count else None
        )
        return {
            "passengers": k.passengers,
            "departures": k.departures,
            "passengers_added": k.passengers_added,
            "passenger_growth_pct": _round(k.passenger_growth_pct),
            "seat_growth_pct": _round(k.seat_growth_pct),
            "demand_gap_pts": _round(k.demand_gap_pts),
            "load_factor_pct": _round(k.load_factor_pct),
            "runway_count": k.runway_count,
            "commercial_runway_count": k.commercial_runway_count,
            "passengers_per_commercial_runway": _round(k.passengers_per_runway, 0),
            "passengers_per_commercial_runway_per_day": (
                _round(k.passengers / runway_days, 0)
                if k.passengers is not None and runway_days
                else None
            ),
            "departures_per_commercial_runway_per_day": (
                _round(k.departures / runway_days, 1)
                if k.departures is not None and runway_days
                else None
            ),
            "peak_month_ratio": _round(k.peak_month_ratio, 2),
            "data_flags": k.flags,
        }

    @staticmethod
    def _live_label(events: Sequence[dict]) -> str:
        """Closure entries are NOTAM text (many only restrict general aviation), so an airport
        with only closure entries is not reported as having a delay program."""
        if not events:
            return "no_reported_programs"
        if any(e["kind"] != CLOSURE_KIND for e in events):
            return "delay_programs"
        return "closure_notices_only"

    @staticmethod
    def _runways(a: Airport) -> dict:
        return {
            "total": a.runway_count,
            "commercial": a.commercial_runway_count,
            "commercial_means": RULE_TEXT,
            "longest_ft": a.longest_runway_ft,
        }

    @staticmethod
    def _comparison(comparable: Mapping[str, dict]) -> dict:
        """Which airport is highest and lowest on each measure, and by how much. The ratio is
        highest divided by lowest (only for measures where a ratio is meaningful)."""
        out: dict[str, dict | None] = {}
        for metric in (*RATIO_METRICS, *DIFFERENCE_METRICS):
            values = {c: v[metric] for c, v in comparable.items() if v[metric] is not None}
            if len(values) < 2:
                out[metric] = None
                continue
            high, low = max(values.values()), min(values.values())
            highest = [c for c, v in values.items() if v == high]
            lowest = [c for c, v in values.items() if v == low]
            entry = {
                "highest": highest[0] if len(highest) == 1 else "tie",
                "lowest": lowest[0] if len(lowest) == 1 else "tie",
                "difference": _round(high - low, 2),
            }
            if metric in RATIO_METRICS and low > 0:
                entry["ratio_highest_to_lowest"] = _round(high / low, 2)
            out[metric] = entry
        return out

    @staticmethod
    def _components_out(components: Mapping, weights: Mapping[str, float]) -> dict:
        return {
            c: {
                "value": _round(components[c].value, 2),
                "percentile": _round(components[c].percentile),
                "weight": _round(weights[c], 3),
            }
            for c in COMPONENTS
        }

    @staticmethod
    def _points(components: Mapping, weights: Mapping[str, float]) -> dict:
        """What each component contributed to the score: weight x percentile. The points add up
        to the score (within rounding), and the largest one is the main driver."""
        points = {c: weights[c] * components[c].percentile for c in COMPONENTS}
        top = max(points.values())
        drivers = [c for c, v in points.items() if _round(v) == _round(top)]
        return {
            "points": {c: _round(v) for c, v in points.items()},
            "main_driver": drivers[0] if len(drivers) == 1 else "tie: " + ", ".join(drivers),
        }

    @staticmethod
    def _leaders(by_airport: Mapping[str, Mapping]) -> dict:
        """The airport with the highest value on each score component among those returned
        (all of them on a tie)."""
        out = {}
        for c in COMPONENTS:
            values = {i: comp[c].value for i, comp in by_airport.items()}
            top = max(values.values())
            winners = [i for i, v in values.items() if v == top]
            out[c] = {
                "leader": winners[0] if len(winners) == 1 else winners,
                "value": _round(top, 2),
            }
        return out

    @staticmethod
    def _spread(scores: Sequence[float]) -> dict:
        """Score range of the scale and the spread between the airports returned."""
        high, low = max(scores), min(scores)
        return {
            "score_range": SCORE_RANGE,
            "score_spread": {
                "highest": _round(high),
                "lowest": _round(low),
                "difference": _round(high - low),
            },
        }

    # ---------- analyses ----------

    async def search(
        self, query: str, region: str | None, states: Sequence[str] | None, limit: int
    ) -> dict:
        snap = await self._load()
        airports = await self._repository.list_airports(states=self._states(region, states))
        found = search_airports(airports, query, self._config.aliases, limit)
        return self._envelope(
            snap,
            {
                "query": query,
                "matches": [{**self._airport_summary(a), "matched_on": why} for a, why in found],
                "note": (
                    None
                    if found
                    else "No airport matched. Try a city, a full airport name or an IATA code."
                ),
            },
            [],
        )

    async def profile(self, iata: str) -> dict:
        snap = await self._load()
        airport = await self._airport(iata)
        facts = {
            **self._airport_summary(airport),
            "latitude": airport.latitude,
            "longitude": airport.longitude,
            "elevation_ft": airport.elevation_ft,
            "runways": self._runways(airport),
            "scheduled_service": airport.scheduled_service,
        }
        if airport.iata not in snap.airports:
            note = self._config.caveats["not_peer"][0].format(
                iata=airport.iata, minimum=snap.info.peer_min_annual_passengers
            )
            return self._envelope(
                snap, {"airport": facts, "traffic": None, "score": None, "note": note}, []
            )

        weights = normalize_weights(self._config.scoring.weights, None)
        scored = snap.national.components.get(airport.iata)
        score = (
            {
                "value": _round(weighted_score(scored, weights)),
                "score_range": SCORE_RANGE,
                "components": self._components_out(scored, weights),
                **self._points(scored, weights),
                "compared_with_airports": snap.national.reference_size,
                "compared_with": (
                    f"{snap.national.reference_size} scored peer airports nationally"
                ),
            }
            if scored
            else {"value": None, "not_scored_reasons": snap.national.not_scored[airport.iata]}
        )
        score = {"name": self._config.scoring.score_name, **score}
        return self._envelope(
            snap,
            {
                "airport": facts,
                "traffic": self._kpi_summary(snap.kpis[airport.iata]),
                "score": score,
            },
            ["data", "score"],
        )

    async def rank(
        self,
        region: str | None,
        states: Sequence[str] | None,
        top_n: int,
        weight_overrides: Mapping[str, float] | None,
    ) -> dict:
        snap = await self._load()
        try:
            weights = normalize_weights(self._config.scoring.weights, weight_overrides)
        except ValueError as exc:
            raise ToolExecutionError("invalid_weights", str(exc)) from exc
        scope_states = self._states(region, states)
        in_scope = [
            i for i, a in snap.airports.items() if scope_states is None or a.state in scope_states
        ]
        ranking, not_scored = rank_airports(snap.national, in_scope, weights)
        shown = [
            {
                "rank": r.rank,
                "score": _round(r.score),
                **self._airport_summary(snap.airports[r.iata]),
                "passengers": snap.kpis[r.iata].passengers,
                "passengers_added": snap.kpis[r.iata].passengers_added,
                "passenger_growth_pct": _round(snap.kpis[r.iata].passenger_growth_pct),
                "components": self._components_out(snap.national.components[r.iata], weights),
                **self._points(snap.national.components[r.iata], weights),
            }
            for r in ranking[:top_n]
        ]
        extras = (
            {
                "leaders_by_component": self._leaders(
                    {row["iata"]: snap.national.components[row["iata"]] for row in shown}
                ),
                **self._spread([row["score"] for row in shown]),
            }
            if shown
            else {}
        )
        return self._envelope(
            snap,
            {
                "score_name": self._config.scoring.score_name,
                "scope": region or (", ".join(scope_states) if scope_states else "national"),
                "scored_airports_in_scope": len(ranking),
                "ranking": shown,
                **extras,
                "not_scored": [
                    {**self._airport_summary(snap.airports[i]), "reasons": reasons}
                    for i, reasons in sorted(not_scored.items())
                ],
                "weights_used": {c: _round(w, 3) for c, w in weights.items()},
                "percentiles_are_against": (
                    f"{snap.national.reference_size} scored peer airports nationally"
                ),
            },
            ["data", "score"],
        )

    async def compare(self, iatas: Sequence[str]) -> dict:
        codes = list(dict.fromkeys(i.upper() for i in iatas))
        if not 2 <= len(codes) <= MAX_COMPARE:
            raise ToolExecutionError("invalid_arguments", f"Give 2 to {MAX_COMPARE} airports.")
        weights = normalize_weights(self._config.scoring.weights, None)
        snap = await self._load()
        rows, comparable, scored_components = [], {}, {}
        for code in codes:
            _, airport = await self._peer(code)
            kpis = snap.kpis[code]
            scored = snap.national.components.get(code)
            rows.append(
                {
                    **self._airport_summary(airport),
                    "runways": self._runways(airport),
                    **self._kpi_summary(kpis),
                    "score": _round(weighted_score(scored, weights)) if scored else None,
                    **(self._points(scored, weights) if scored else {}),
                }
            )
            if scored:
                scored_components[code] = scored
            comparable[code] = self._kpi_summary(kpis)
        return self._envelope(
            snap,
            {
                "score_name": self._config.scoring.score_name,
                "airports": rows,
                "comparison_by_metric": self._comparison(comparable),
                **(
                    {
                        "leaders_by_component": self._leaders(scored_components),
                        **self._spread([r["score"] for r in rows if r["score"] is not None]),
                    }
                    if len(scored_components) >= 2
                    else {}
                ),
            },
            ["data", "congestion", "cargo", "score"],
        )

    async def distance(self, iata: str) -> dict:
        snap, airport = await self._peer(iata)
        current = [r for r in snap.traffic[airport.iata] if r.month in set(snap.windows.current)]
        profile = distance_profile(current, self._config.scoring.cargo_seat_threshold)
        groups = ["data", "long_haul", "cargo"]
        fmt: dict[str, Any] = {}
        if profile["international_mostly_cargo"]:
            groups.append("cargo_international")
            fmt["seats"] = profile["seats_per_international_departure"]
        payload = {
            **self._airport_summary(airport),
            "long_haul_share_pct": None,
            "long_haul_share_status": (
                "not computable from public API data (no route-level distances)"
            ),
            "proxies": {
                "international_share_of_departures_pct": _round(profile["international_share_pct"]),
                "avg_flight_distance_mi": _round(profile["avg_flight_distance_mi"], 0),
                "avg_domestic_distance_mi": _round(profile["avg_domestic_distance_mi"], 0),
                "avg_international_distance_mi": _round(
                    profile["avg_international_distance_mi"], 0
                ),
            },
            "departures": profile["departures"],
            "domestic_departures": profile["domestic_departures"],
            "international_departures": profile["international_departures"],
            "seats_per_international_departure": _round(
                profile["seats_per_international_departure"]
            ),
            "seats_per_domestic_departure": _round(profile["seats_per_domestic_departure"]),
            "international_departures_mostly_cargo": profile["international_mostly_cargo"],
            "freight_lbs": profile["freight_lbs"],
            "months_used": len(current),
        }
        return self._envelope(snap, payload, groups, **fmt)

    async def demand(self, iata: str) -> dict:
        snap, airport = await self._peer(iata)
        kpis = snap.kpis[airport.iata]
        signals = demand_signals(
            snap.traffic[airport.iata],
            kpis,
            snap.windows,
            self._config.scoring.high_load_factor_pct,
        )
        summary = self._kpi_summary(kpis)
        recovery = signals["recovery_vs_2019"]
        notes = []
        if signals["months_considered"]:
            notes.append(
                f"Load factor was at or above {signals['high_load_factor_threshold_pct']:.0f}% in "
                f"{signals['months_at_or_above_threshold']} of {signals['months_considered']} "
                f"months (peak {signals['peak_load_factor_pct']:.1f}% in "
                f"{signals['peak_load_factor_month']})."
            )
        if kpis.demand_gap_pts is not None:
            notes.append(
                f"Passengers grew {kpis.passenger_growth_pct:.1f}% while seats grew "
                f"{kpis.seat_growth_pct:.1f}% "
                f"(demand gap {_round(kpis.demand_gap_pts):+.1f} points)."
            )
        if recovery and recovery["passengers_pct_of_2019"] is not None:
            notes.append(
                f"Passengers are at {recovery['passengers_pct_of_2019']:.0f}% of the 2019 level "
                f"and seats at {recovery['seats_pct_of_2019']:.0f}%."
            )
        payload = {
            **self._airport_summary(airport),
            "load_factor_pct": summary["load_factor_pct"],
            "passenger_growth_pct": summary["passenger_growth_pct"],
            "seat_growth_pct": summary["seat_growth_pct"],
            "demand_gap_pts": summary["demand_gap_pts"],
            "months_load_factor_at_or_above_threshold": {
                "threshold_pct": signals["high_load_factor_threshold_pct"],
                "count": signals["months_at_or_above_threshold"],
                "of_months": signals["months_considered"],
                "months": signals["months_at_or_above_threshold_list"],
            },
            "peak_load_factor": {
                "pct": _round(signals["peak_load_factor_pct"]),
                "month": signals["peak_load_factor_month"],
            },
            "recovery_vs_2019": (
                {k: _round(v) for k, v in recovery.items()}
                if recovery
                else signals["recovery_note"]
            ),
            "signals": notes,
            "data_flags": kpis.flags,
        }
        return self._envelope(snap, payload, ["data", "unmet_demand", "cargo"])

    async def live(self, iata: str) -> dict:
        snap = await self._load()
        airport = await self._airport(iata)
        try:
            status = await self._live_status.get_status()
        except LiveStatusUnavailable as exc:
            raise ToolExecutionError("live_status_unavailable", str(exc)) from exc
        events = [e.model_dump() for e in status.events.get(airport.iata, [])]
        return {
            "as_of": f"FAA feed updated {status.updated}",
            **self._airport_summary(airport),
            "live_status": self._live_label(events),
            "events": events,
            "caveats": self._caveats(snap, ["live"]),
        }

    async def methodology(self, topic: str) -> dict:
        snap = await self._load()
        scoring = self._config.scoring
        parts: dict[str, Any] = {
            # Always returned, whatever the topic, so an answer about the score can say what it
            # does not measure and have that grounded in a tool result.
            "does_not_measure": list(self._config.does_not_measure)
        }
        if topic in ("score", "all"):
            parts["score"] = {
                "name": "Expansion Pressure Score",
                "range": "0 to 100",
                "how": (
                    "Each airport gets a percentile (0 to 100) for each component, compared with "
                    "all scored peer airports nationally. The score is the weighted sum of those "
                    "percentiles. A regional ranking orders airports by this national score; it "
                    "does not recompute percentiles within the region."
                ),
                "percentile": "mid-rank: (airports below + half of the airports equal) / airports",
                "weights": scoring.weights,
                "windows": (
                    f"last {scoring.window_months} months compared with the "
                    f"{scoring.window_months} months before"
                ),
                "not_scored": (
                    "An airport with a missing month in either window, no commercial runway, or no "
                    "seats cannot have all components computed. It is listed as not scored with "
                    "the reasons; it is never scored on partial data."
                ),
            }
        if topic in ("metrics", "all"):
            parts["metrics"] = [m.model_dump() for m in self._config.metrics]
            parts["utilization_per_day"] = (
                "Departures or passengers per commercial runway per day = last-12-months total "
                f"/ commercial runways / {DAYS_PER_YEAR}. A commercial runway is {RULE_TEXT}."
            )
        if topic in ("limits", "all"):
            parts["limits"] = {
                name: self._caveats(snap, [name])
                for name in ("data", "score", "congestion", "unmet_demand", "long_haul", "cargo")
            }
        return self._envelope(snap, parts, [])
