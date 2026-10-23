from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from adapters.snapshot_files import (
    AIRPORT_COLUMNS,
    RUNWAY_COLUMNS,
    TRAFFIC_COLUMNS,
    read_meta,
    read_records,
)
from domain.repository import Airport, MonthlyTraffic, SnapshotInfo


class MemoryRepository:
    """Serves the same snapshot files from memory: for unit tests, the CLI and evals without
    Docker. It follows the same contract as `PostgresRepository` (the tests run both)."""

    def __init__(self, snapshot_dir: Path) -> None:
        runways: dict[str, list[int | None]] = defaultdict(list)
        for iata, _runway, length_ft, *_ in read_records(
            snapshot_dir / "runways.csv", RUNWAY_COLUMNS
        ):
            runways[iata].append(length_ft)

        self._traffic: dict[str, list[MonthlyTraffic]] = defaultdict(list)
        for record in read_records(snapshot_dir / "airport_month.csv", TRAFFIC_COLUMNS):
            row = MonthlyTraffic(**dict(zip(TRAFFIC_COLUMNS, record, strict=True)))
            self._traffic[row.iata].append(row)
        for rows in self._traffic.values():
            rows.sort(key=lambda r: r.month)

        self._airports: list[Airport] = []
        for record in read_records(snapshot_dir / "airports.csv", AIRPORT_COLUMNS):
            fields = dict(zip(AIRPORT_COLUMNS, record, strict=True))
            lengths = [n for n in runways[fields["iata"]] if n is not None]
            self._airports.append(
                Airport(
                    **fields,
                    runway_count=len(runways[fields["iata"]]),
                    longest_runway_ft=max(lengths) if lengths else None,
                    has_traffic=fields["iata"] in self._traffic,
                )
            )
        self._airports.sort(key=lambda a: a.iata)
        self._meta = read_meta(snapshot_dir)

    async def list_airports(
        self,
        *,
        states: Sequence[str] | None = None,
        iatas: Sequence[str] | None = None,
        peers_only: bool = False,
    ) -> list[Airport]:
        return [
            a
            for a in self._airports
            if (states is None or a.state in states)
            and (iatas is None or a.iata in iatas)
            and (not peers_only or a.has_traffic)
        ]

    async def get_traffic(self, iatas: Sequence[str] | None = None) -> list[MonthlyTraffic]:
        codes = sorted(self._traffic) if iatas is None else sorted(set(iatas) & set(self._traffic))
        return [row for code in codes for row in self._traffic[code]]

    async def get_snapshot_info(self) -> SnapshotInfo:
        return SnapshotInfo(
            latest_period=date.fromisoformat(self._meta["latest_period"]),
            fetched_at=self._meta["fetched_at"],
            airport_count=self._meta["counts"]["airports"],
            peer_count=self._meta["counts"]["peers"],
            peer_min_annual_passengers=self._meta["peer_min_annual_passengers"],
        )
