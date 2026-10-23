"""Distance profile and demand-pressure signals for one airport. Pure functions."""

from collections.abc import Sequence
from datetime import date

from domain.repository import MonthlyTraffic
from domain.scoring import Kpis, Windows, month_label, monthly_load_factor

BASELINE_YEAR = 2019


def _weighted_average(pairs: Sequence[tuple[float, float]]) -> float | None:
    """Average of (value, weight) pairs; None if there is no weight."""
    total = sum(w for _, w in pairs)
    return sum(v * w for v, w in pairs) / total if total > 0 else None


def distance_profile(rows: Sequence[MonthlyTraffic], cargo_seat_threshold: float) -> dict:
    """Average distances and the domestic/international split over the given months.

    Averages are weighted by departures. The exact long-haul share cannot be computed because
    only averages per airport-month exist, so this reports proxies."""
    departures = sum(r.departures for r in rows)
    domestic = sum(r.domestic_departures for r in rows)
    international = sum(r.international_departures for r in rows)
    international_seats = sum(r.international_seats for r in rows)
    all_seats = sum(r.seats for r in rows)

    with_distance = [r for r in rows if r.avg_flight_distance_mi is not None]
    average = _weighted_average([(r.avg_flight_distance_mi, r.departures) for r in with_distance])
    domestic_average = _weighted_average(
        [
            (r.avg_domestic_distance_mi, r.domestic_departures)
            for r in rows
            if r.avg_domestic_distance_mi is not None
        ]
    )
    # total distance flown = domestic distance + international distance, so the international
    # average follows from the other two (months with both averages only).
    both = [r for r in with_distance if r.avg_domestic_distance_mi is not None]
    international_miles = sum(
        r.avg_flight_distance_mi * r.departures - r.avg_domestic_distance_mi * r.domestic_departures
        for r in both
    )
    both_international = sum(r.international_departures for r in both)
    international_average = (
        international_miles / both_international if both_international > 0 else None
    )

    seats_per_international = international_seats / international if international else None
    return {
        "departures": departures,
        "domestic_departures": domestic,
        "international_departures": international,
        "international_share_pct": 100 * international / departures if departures else None,
        "avg_flight_distance_mi": average,
        "avg_domestic_distance_mi": domestic_average,
        "avg_international_distance_mi": international_average,
        "seats_per_international_departure": seats_per_international,
        "seats_per_domestic_departure": (
            (all_seats - international_seats) / domestic if domestic else None
        ),
        "international_mostly_cargo": (
            seats_per_international is not None and seats_per_international < cargo_seat_threshold
        ),
        "freight_lbs": sum(r.freight_lbs for r in rows),
    }


def demand_signals(
    rows: Sequence[MonthlyTraffic], kpis: Kpis, windows: Windows, high_load_factor_pct: float
) -> dict:
    """Signals that demand may exceed capacity, with recovery against 2019.

    These are signals, not a measure of unmet demand."""
    by_month = {r.month: r for r in rows}
    current = [by_month[m] for m in windows.current if m in by_month]
    monthly = [(r.month, monthly_load_factor(r)) for r in current]
    defined = [(m, lf) for m, lf in monthly if lf is not None]
    full_months = [m for m, lf in defined if lf >= high_load_factor_pct]
    peak_month, peak_lf = max(defined, key=lambda p: p[1]) if defined else (None, None)

    baseline = [by_month.get(date(BASELINE_YEAR, m, 1)) for m in range(1, 13)]
    baseline_complete = all(r is not None for r in baseline)
    recovery = None
    if baseline_complete and kpis.passengers is not None:
        pax_2019 = sum(r.passengers for r in baseline)
        seats_2019 = sum(r.seats for r in baseline)
        deps_2019 = sum(r.departures for r in baseline)
        recovery = {
            "passengers_pct_of_2019": 100 * kpis.passengers / pax_2019 if pax_2019 else None,
            "seats_pct_of_2019": 100 * kpis.seats / seats_2019 if seats_2019 else None,
            "departures_pct_of_2019": (
                100 * kpis.departures / deps_2019 if deps_2019 and kpis.departures else None
            ),
        }

    return {
        "months_considered": len(defined),
        "months_at_or_above_threshold": len(full_months),
        "high_load_factor_threshold_pct": high_load_factor_pct,
        "months_at_or_above_threshold_list": [month_label(m) for m in full_months],
        "peak_load_factor_pct": peak_lf,
        "peak_load_factor_month": month_label(peak_month) if peak_month else None,
        "recovery_vs_2019": recovery,
        "recovery_note": None
        if baseline_complete
        else "2019 baseline is incomplete for this airport",
    }
