"""What the airport tools need from the data store, and the records it returns."""

from collections.abc import Sequence
from datetime import date
from typing import Protocol

from pydantic import BaseModel


class Airport(BaseModel):
    iata: str
    ident: str
    name: str
    city: str | None
    state: str
    latitude: float
    longitude: float
    elevation_ft: int | None
    type: str
    scheduled_service: bool
    runway_count: int  # every open runway
    commercial_runway_count: int  # open, paved, at least 5,000 ft: used for per-runway metrics
    longest_runway_ft: int | None
    has_traffic: bool  # True for peer airports: only they have monthly traffic rows


class MonthlyTraffic(BaseModel):
    """One airport, one month, counted by origin airport (departures and boardings)."""

    iata: str
    month: date
    departures: int  # all departures, including all-cargo flights
    passengers: int
    seats: int
    domestic_departures: int
    international_departures: int
    international_seats: int
    avg_flight_distance_mi: float | None
    avg_domestic_distance_mi: float | None
    freight_lbs: int


class SnapshotInfo(BaseModel):
    latest_period: date
    fetched_at: str
    airport_count: int
    peer_count: int
    peer_min_annual_passengers: int


class AirportRepository(Protocol):
    async def list_airports(
        self,
        *,
        states: Sequence[str] | None = None,
        iatas: Sequence[str] | None = None,
        peers_only: bool = False,
    ) -> list[Airport]: ...

    async def get_traffic(self, iatas: Sequence[str] | None = None) -> list[MonthlyTraffic]:
        """Monthly rows ordered by airport then month. None means every peer airport."""
        ...

    async def get_snapshot_info(self) -> SnapshotInfo: ...
