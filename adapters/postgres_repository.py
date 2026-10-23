from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import asyncpg

from adapters.snapshot_files import (
    AIRPORT_COLUMNS,
    RUNWAY_COLUMNS,
    TRAFFIC_COLUMNS,
    read_meta,
    read_records,
    snapshot_hash,
)
from domain.repository import Airport, MonthlyTraffic, SnapshotInfo
from domain.runways import RULE_TEXT, is_commercial_capable

LOAD_LOCK_ID = 42  # serializes loaders when several API replicas start together

_AIRPORTS_SQL = """
SELECT a.iata, a.ident, a.name, a.city, a.state, a.latitude, a.longitude, a.elevation_ft,
       a.type, a.scheduled_service,
       COALESCE(r.runway_count, 0) AS runway_count,
       COALESCE(r.commercial_runway_count, 0) AS commercial_runway_count,
       r.longest_runway_ft,
       EXISTS (SELECT 1 FROM airport_month m WHERE m.iata = a.iata) AS has_traffic
FROM airports a
LEFT JOIN (
    SELECT airport_iata, COUNT(*) AS runway_count,
           COUNT(*) FILTER (WHERE commercial_capable) AS commercial_runway_count,
           MAX(length_ft) AS longest_runway_ft
    FROM runways GROUP BY airport_iata
) r ON r.airport_iata = a.iata
WHERE ($1::text[] IS NULL OR a.state = ANY($1))
  AND ($2::text[] IS NULL OR a.iata = ANY($2))
  AND (NOT $3::boolean OR EXISTS (SELECT 1 FROM airport_month m WHERE m.iata = a.iata))
ORDER BY a.iata
"""

_TRAFFIC_SQL = """
SELECT iata, month, departures, passengers, seats, domestic_departures,
       international_departures, international_seats, avg_flight_distance_mi,
       avg_domestic_distance_mi, freight_lbs
FROM airport_month
WHERE $1::text[] IS NULL OR iata = ANY($1)
ORDER BY iata, month
"""


class PostgresRepository:
    """Reads the airport snapshot. All queries are parameterised."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @property
    def pool(self) -> asyncpg.Pool:
        """Shared with the session store, so the API holds one connection pool."""
        return self._pool

    @classmethod
    async def connect(cls, dsn: str) -> "PostgresRepository":
        return cls(await asyncpg.create_pool(dsn, min_size=1, max_size=10))

    async def close(self) -> None:
        await self._pool.close()

    async def load_snapshot(self, schema_path: Path, snapshot_dir: Path) -> bool:
        """Create the schema and replace the data with the committed snapshot.

        Idempotent: a snapshot that is already loaded (same hash) is skipped. The replacement
        runs in one transaction, so readers see the old data until the new data is complete.
        Returns True if data was loaded."""
        schema_sql = schema_path.read_text(encoding="utf-8")
        digest = snapshot_hash(snapshot_dir, (schema_sql + RULE_TEXT).encode())
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock($1)", LOAD_LOCK_ID)
            await conn.execute(schema_sql)
            stored = await conn.fetchval("SELECT value FROM snapshot_meta WHERE key = 'hash'")
            if stored == digest:
                return False

            await conn.execute("TRUNCATE airport_month, runways, airports")
            await _copy(conn, "airports", snapshot_dir / "airports.csv", AIRPORT_COLUMNS)
            await _copy_runways(conn, snapshot_dir / "runways.csv")
            await _copy(conn, "airport_month", snapshot_dir / "airport_month.csv", TRAFFIC_COLUMNS)
            await _store_meta(conn, snapshot_dir, digest)
        return True

    async def list_airports(
        self,
        *,
        states: Sequence[str] | None = None,
        iatas: Sequence[str] | None = None,
        peers_only: bool = False,
    ) -> list[Airport]:
        rows = await self._pool.fetch(
            _AIRPORTS_SQL,
            list(states) if states is not None else None,
            list(iatas) if iatas is not None else None,
            peers_only,
        )
        return [Airport(**row) for row in rows]

    async def get_traffic(self, iatas: Sequence[str] | None = None) -> list[MonthlyTraffic]:
        rows = await self._pool.fetch(_TRAFFIC_SQL, list(iatas) if iatas is not None else None)
        return [MonthlyTraffic(**row) for row in rows]

    async def get_snapshot_info(self) -> SnapshotInfo:
        rows = await self._pool.fetch("SELECT key, value FROM snapshot_meta")
        meta = {r["key"]: r["value"] for r in rows}
        return SnapshotInfo(
            latest_period=date.fromisoformat(meta["latest_period"]),
            fetched_at=meta["fetched_at"],
            airport_count=int(meta["airport_count"]),
            peer_count=int(meta["peer_count"]),
            peer_min_annual_passengers=int(meta["peer_min_annual_passengers"]),
        )


# ---------- snapshot loading helpers ----------


async def _copy(
    conn: asyncpg.Connection, table: str, path: Path, columns: dict[str, Callable[[str], Any]]
) -> None:
    records = read_records(path, columns)
    await conn.copy_records_to_table(table, records=records, columns=list(columns))


async def _copy_runways(conn: asyncpg.Connection, path: Path) -> None:
    """Runways get one computed column: whether the runway counts for per-runway metrics."""
    records = [
        (*record, is_commercial_capable(record[2], record[4]))  # length_ft, surface
        for record in read_records(path, RUNWAY_COLUMNS)
    ]
    await conn.copy_records_to_table(
        "runways", records=records, columns=[*RUNWAY_COLUMNS, "commercial_capable"]
    )


async def _store_meta(conn: asyncpg.Connection, snapshot_dir: Path, digest: str) -> None:
    meta = read_meta(snapshot_dir)
    values = {
        "hash": digest,
        "latest_period": meta["latest_period"],
        "fetched_at": meta["fetched_at"],
        "airport_count": str(meta["counts"]["airports"]),
        "peer_count": str(meta["counts"]["peers"]),
        "peer_min_annual_passengers": str(meta["peer_min_annual_passengers"]),
    }
    await conn.execute("DELETE FROM snapshot_meta")
    await conn.executemany(
        "INSERT INTO snapshot_meta (key, value) VALUES ($1, $2)", list(values.items())
    )
