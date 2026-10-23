"""The airport tools. Each one is a thin wrapper: validate arguments, call `Analytics`.

The model chooses a tool and explains the result; every number comes from `Analytics`.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

from core.tools import Tool
from domain.analytics import MAX_COMPARE, Analytics

IATA_PATTERN = r"^[A-Za-z]{3}$"
MAX_TOP_N = 15


class SearchArgs(BaseModel):
    query: str = Field(min_length=2, description="Name, city, IATA code or common name")
    region: str | None = Field(default=None, description="Limit to a region, e.g. 'New England'")
    state: str | None = Field(
        default=None, pattern=r"^[A-Za-z]{2}$", description="Two-letter state"
    )
    limit: int = Field(default=5, ge=1, le=10)


class AirportArgs(BaseModel):
    iata: str = Field(pattern=IATA_PATTERN, description="Three-letter IATA code, e.g. SFO")


class RankArgs(BaseModel):
    region: str | None = Field(default=None, description="Named region, e.g. 'New England'")
    states: list[str] | None = Field(default=None, description="Two-letter state codes instead")
    top_n: int = Field(default=5, ge=1, le=MAX_TOP_N)
    weights: dict[str, float] | None = Field(
        default=None,
        description=(
            "Optional weight overrides by component (growth, load_factor, pax_per_runway, "
            'demand_gap, scale, peak), for example {"growth": 0.6}. Each named component gets '
            "exactly that weight; the other components share the rest in proportion to their "
            "default weights. Never compute weights yourself: pass only what the user asked for "
            "and read the weights actually used from weights_used in the result."
        ),
    )


class CompareArgs(BaseModel):
    iatas: list[str] = Field(min_length=2, max_length=MAX_COMPARE, description="IATA codes")


class MethodologyArgs(BaseModel):
    topic: Literal["score", "metrics", "limits", "all"] = "all"


def build_tools(analytics: Analytics) -> list[Tool]:
    async def search_airports(args: SearchArgs) -> dict[str, Any]:
        states = [args.state] if args.state else None
        return await analytics.search(args.query, args.region, states, args.limit)

    async def get_airport_profile(args: AirportArgs) -> dict[str, Any]:
        return await analytics.profile(args.iata)

    async def rank_airports(args: RankArgs) -> dict[str, Any]:
        return await analytics.rank(args.region, args.states, args.top_n, args.weights)

    async def compare_airports(args: CompareArgs) -> dict[str, Any]:
        return await analytics.compare(args.iatas)

    async def get_distance_profile(args: AirportArgs) -> dict[str, Any]:
        return await analytics.distance(args.iata)

    async def demand_pressure(args: AirportArgs) -> dict[str, Any]:
        return await analytics.demand(args.iata)

    async def get_live_status(args: AirportArgs) -> dict[str, Any]:
        return await analytics.live(args.iata)

    async def get_methodology(args: MethodologyArgs) -> dict[str, Any]:
        return await analytics.methodology(args.topic)

    return [
        Tool(
            "search_airports",
            "Find US airports by name, city, IATA code or a common name such as 'LA' or "
            "'Santa Ana'. Use this first whenever the user names an airport or city, to get the "
            "IATA code. Each match says whether the airport is in the analysed peer set. If one "
            "match is clearly the main commercial airport for the name, use it and say which one; "
            "if several are plausible, ask the user.",
            SearchArgs,
            search_airports,
        ),
        Tool(
            "get_airport_profile",
            "Facts about one airport (location, runways) and, for peer airports, its "
            "last-12-months traffic indicators and its Expansion Pressure Score with the "
            "component breakdown.",
            AirportArgs,
            get_airport_profile,
        ),
        Tool(
            "rank_airports",
            "Rank airports by the deterministic Expansion Pressure Score (0 to 100), which "
            "estimates demand pressure on terminals. Use it for 'best candidates', 'strong "
            "candidates for expansion' and similar. Pass a region (for example 'New England') or "
            "state codes, or neither for a national ranking. Percentiles are always national. "
            "Airports that cannot be scored are listed in not_scored with the reasons. Optional "
            "weights change the emphasis. Each airport has points (weight x percentile per "
            "component, adding up to the score) and main_driver; leaders_by_component names the "
            "top airport per component and score_spread the gap between the airports returned. "
            "Use only these fields for superlatives and for why one airport outranks another.",
            RankArgs,
            rank_airports,
        ),
        Tool(
            "compare_airports",
            "Compare 2 to 5 airports side by side: passengers, growth, load factor, runways, "
            "passengers and departures per runway per day, peak-month ratio and score. Use it for "
            "'compare X and Y' and for congestion comparisons. comparison_by_metric gives the "
            "highest, lowest, difference and ratio for each measure; points, main_driver, "
            "leaders_by_component and score_spread explain the score. Use only these fields for "
            "superlatives and for explanations.",
            CompareArgs,
            compare_airports,
        ),
        Tool(
            "get_distance_profile",
            "Average flight distance and the domestic/international split of departures at one "
            "airport. Use it for long-haul questions. The exact long-haul share cannot be "
            "computed, so this returns proxies; check international_departures_mostly_cargo.",
            AirportArgs,
            get_distance_profile,
        ),
        Tool(
            "demand_pressure",
            "Signals that demand may exceed capacity at one airport: months with load factor at "
            "or above the threshold, passenger vs seat growth, and recovery vs 2019. Use it for "
            "unmet-demand questions. It does not measure unmet demand; any explanation of why is "
            "a hypothesis.",
            AirportArgs,
            demand_pressure,
        ),
        Tool(
            "get_live_status",
            "Current FAA delay programs and closures for one airport. Live snapshot only, no "
            "history.",
            AirportArgs,
            get_live_status,
        ),
        Tool(
            "get_methodology",
            "How the score, the metrics and the time windows are defined, with the weights and "
            "the known limits of the data. Use it when asked how the ranking works or what a "
            "metric means.",
            MethodologyArgs,
            get_methodology,
        ),
    ]
