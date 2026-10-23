"""Deterministic KPIs and the Expansion Pressure Score. Pure functions: no database, no model.

An airport is scored only when all six components can be computed from complete data. Anything
else is listed as not scored, with the reasons, and is never scored silently.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from pydantic import BaseModel

from domain.repository import Airport, MonthlyTraffic

COMPONENTS = ("growth", "load_factor", "pax_per_runway", "demand_gap", "scale", "peak")


@dataclass(frozen=True)
class Windows:
    """The trailing window and the one before it, as lists of first-of-month dates."""

    as_of: date
    current: tuple[date, ...]
    prior: tuple[date, ...]


def shift_month(day: date, months: int) -> date:
    index = day.year * 12 + (day.month - 1) + months
    return date(index // 12, index % 12 + 1, 1)


def make_windows(as_of: date, months: int = 12) -> Windows:
    """as_of is the first day of the latest month. With 12 months and Apr 2026:
    current = May 2025..Apr 2026, prior = May 2024..Apr 2025."""
    ends = [shift_month(as_of, -offset) for offset in range(2 * months - 1, -1, -1)]
    return Windows(as_of=as_of, current=tuple(ends[months:]), prior=tuple(ends[:months]))


def month_label(day: date) -> str:
    return f"{day:%b %Y}"


def window_label(months: Sequence[date]) -> str:
    return f"{month_label(months[0])} to {month_label(months[-1])}"


class Kpis(BaseModel):
    """KPIs of one airport. None means the value could not be computed; `flags` say why."""

    iata: str
    runway_count: int
    passengers: int | None  # last 12 months; None if any month is missing
    seats: int | None
    departures: int | None
    prior_passengers: int | None
    passenger_growth_pct: float | None
    seat_growth_pct: float | None
    demand_gap_pts: float | None
    load_factor_pct: float | None
    passengers_per_runway: float | None
    peak_month_ratio: float | None
    flags: list[str]


def monthly_load_factor(row: MonthlyTraffic) -> float | None:
    """Percent. Undefined (None), not zero, when the month had no seats."""
    return 100 * row.passengers / row.seats if row.seats > 0 else None


def _pct_change(current: int | None, prior: int | None) -> float | None:
    if current is None or prior is None or prior <= 0:
        return None
    return 100 * (current / prior - 1)


def compute_kpis(airport: Airport, rows: Sequence[MonthlyTraffic], windows: Windows) -> Kpis:
    by_month = {r.month: r for r in rows}
    current = [by_month[m] for m in windows.current if m in by_month]
    prior = [by_month[m] for m in windows.prior if m in by_month]
    current_complete = len(current) == len(windows.current)
    prior_complete = len(prior) == len(windows.prior)

    flags: list[str] = []
    if not current_complete:
        flags.append(f"missing_months_current:{len(windows.current) - len(current)}")
    if not prior_complete:
        flags.append(f"missing_months_prior:{len(windows.prior) - len(prior)}")
    if airport.runway_count == 0:
        flags.append("no_runway_data")

    passengers = sum(r.passengers for r in current) if current_complete else None
    seats = sum(r.seats for r in current) if current_complete else None
    prior_passengers = sum(r.passengers for r in prior) if prior_complete else None
    prior_seats = sum(r.seats for r in prior) if prior_complete else None

    growth = _pct_change(passengers, prior_passengers)
    seat_growth = _pct_change(seats, prior_seats)
    gap = growth - seat_growth if growth is not None and seat_growth is not None else None

    with_seats = [r for r in current if r.seats > 0]
    if len(with_seats) < len(current):
        flags.append(f"zero_seat_months:{len(current) - len(with_seats)}")
    load_factor = (
        100 * sum(r.passengers for r in with_seats) / sum(r.seats for r in with_seats)
        if with_seats
        else None
    )

    per_runway = (
        passengers / airport.runway_count
        if passengers is not None and airport.runway_count > 0
        else None
    )
    peak = (
        max(r.passengers for r in current) / (passengers / len(current))
        if current_complete and passengers
        else None
    )
    return Kpis(
        iata=airport.iata,
        runway_count=airport.runway_count,
        passengers=passengers,
        seats=seats,
        departures=sum(r.departures for r in current) if current_complete else None,
        prior_passengers=prior_passengers,
        passenger_growth_pct=growth,
        seat_growth_pct=seat_growth,
        demand_gap_pts=gap,
        load_factor_pct=load_factor,
        passengers_per_runway=per_runway,
        peak_month_ratio=peak,
        flags=flags,
    )


def component_values(kpis: Kpis) -> dict[str, float | None]:
    return {
        "growth": kpis.passenger_growth_pct,
        "load_factor": kpis.load_factor_pct,
        "pax_per_runway": kpis.passengers_per_runway,
        "demand_gap": kpis.demand_gap_pts,
        "scale": None if kpis.passengers is None else float(kpis.passengers),
        "peak": kpis.peak_month_ratio,
    }


def percentile(value: float, reference: Sequence[float]) -> float:
    """Mid-rank percentile, 0 to 100: (values below + half of the values equal) / count."""
    below = sum(1 for x in reference if x < value)
    equal = sum(1 for x in reference if x == value)
    return 100 * (below + 0.5 * equal) / len(reference)


@dataclass(frozen=True)
class Component:
    value: float
    percentile: float


@dataclass(frozen=True)
class NationalScores:
    """National percentiles for every scorable airport, plus who could not be scored.

    Percentiles do not depend on the weights, so a re-weighted ranking reuses them."""

    components: dict[str, dict[str, Component]]  # iata -> component -> value and percentile
    not_scored: dict[str, list[str]]  # iata -> reasons
    reference_size: int


def build_national_scores(all_kpis: Sequence[Kpis]) -> NationalScores:
    values = {k.iata: component_values(k) for k in all_kpis}
    scorable = {i: v for i, v in values.items() if all(x is not None for x in v.values())}
    reference = {c: [v[c] for v in scorable.values()] for c in COMPONENTS}
    components = {
        iata: {c: Component(v[c], percentile(v[c], reference[c])) for c in COMPONENTS}
        for iata, v in scorable.items()
    }
    flags = {k.iata: k.flags for k in all_kpis}
    not_scored = {
        iata: [f"{c} unavailable" for c in COMPONENTS if v[c] is None] + flags[iata]
        for iata, v in values.items()
        if iata not in scorable
    }
    return NationalScores(components, not_scored, len(scorable))


def normalize_weights(base: Mapping[str, float], overrides: Mapping[str, float] | None) -> dict:
    """Apply overrides to the base weights and scale so they sum to 1."""
    merged = {**base, **(overrides or {})}
    unknown = set(merged) - set(COMPONENTS)
    if unknown:
        raise ValueError(f"unknown weight(s): {sorted(unknown)}; valid: {list(COMPONENTS)}")
    if any(w < 0 for w in merged.values()) or sum(merged.values()) <= 0:
        raise ValueError("weights must be non-negative and not all zero")
    total = sum(merged.values())
    return {c: merged[c] / total for c in COMPONENTS}


def weighted_score(components: Mapping[str, Component], weights: Mapping[str, float]) -> float:
    """0 to 100: the weighted sum of the component percentiles."""
    return sum(weights[c] * components[c].percentile for c in COMPONENTS)


class Ranked(BaseModel):
    rank: int
    iata: str
    score: float
    components: dict[str, dict[str, float]]  # component -> {"value", "percentile", "weight"}


def rank_airports(
    national: NationalScores, iatas: Sequence[str], weights: Mapping[str, float]
) -> tuple[list[Ranked], dict[str, list[str]]]:
    """Rank the given airports by score using national percentiles.

    Returns the ranking (best first; ties broken by passengers, then code) and, for the airports
    that could not be scored, the reasons."""
    scored = [(i, national.components[i]) for i in iatas if i in national.components]
    scored.sort(key=lambda p: (-weighted_score(p[1], weights), -p[1]["scale"].value, p[0]))
    ranking = [
        Ranked(
            rank=position,
            iata=iata,
            score=weighted_score(components, weights),
            components={
                c: {
                    "value": components[c].value,
                    "percentile": components[c].percentile,
                    "weight": weights[c],
                }
                for c in COMPONENTS
            },
        )
        for position, (iata, components) in enumerate(scored, start=1)
    ]
    not_scored = {i: national.not_scored[i] for i in iatas if i in national.not_scored}
    return ranking, not_scored
