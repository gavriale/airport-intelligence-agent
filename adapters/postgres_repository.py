import csv
import hashlib
import json
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import asyncpg

from domain.repository import Airport, MonthlyTraffic, SnapshotInfo

SNAPSHOT_FILES = ("airports.csv", "runways.csv", "airport_month.csv", "snapshot_meta.json")
LOAD_LOCK_ID = 42  # serializes loaders when several API replicas start together

_AIRPORTS_SQL = """
SELECT a.iata, a.ident, a.name, a.city, a.state, a.latitude, a.longitude, a.elevation_ft,
       a.type, a.scheduled_service,
       COALESCE(r.runway_count, 0) AS runway_count,
       r.longest_runway_ft,
       EXISTS (SELECT 1 FROM airport_month m WHERE m.iata = a.iata) AS has_traffic
FROM airports a
LEFT JOIN (
    SELECT airport_iata, COUNT(*) AS runway_count, MAX(length_ft) AS longest_runway_ft
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
        digest = _snapshot_hash(snapshot_dir)
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock($1)", LOAD_LOCK_ID)
            await conn.execute(schema_path.read_text(encoding="utf-8"))
            stored = await conn.fetchval("SELECT value FROM snapshot_meta WHERE key = 'hash'")
            if stored == digest:
                return False

            await conn.execute("TRUNCATE airport_month, runways, airports")
            await _copy(conn, "airports", snapshot_dir / "airports.csv", _AIRPORT_COLUMNS)
            await _copy(conn, "runways", snapshot_dir / "runways.csv", _RUNWAY_COLUMNS)
            await _copy(conn, "airport_month", snapshot_dir / "airport_month.csv", _TRAFFIC_COLUMNS)
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


def _text(value: str) -> str | None:
    return value or None


def _int(value: str) -> int | None:
    return round(float(value)) if value else None


def _float(value: str) -> float | None:
    return float(value) if value else None


def _bool(value: str) -> bool:
    return value == "true"


# column name -> converter from the CSV text
_AIRPORT_COLUMNS: dict[str, Callable[[str], Any]] = {
    "iata": str, "ident": str, "name": str, "city": _text, "state": str,
    "latitude": float, "longitude": float, "elevation_ft": _int, "type": str,
    "scheduled_service": _bool,
}  # fmt: skip
_RUNWAY_COLUMNS: dict[str, Callable[[str], Any]] = {
    "airport_iata": str, "runway": str, "length_ft": _int, "width_ft": _int,
    "surface": _text, "lighted": _bool,
}  # fmt: skip
_TRAFFIC_COLUMNS: dict[str, Callable[[str], Any]] = {
    "iata": str, "month": date.fromisoformat, "departures": int, "passengers": int,
    "seats": int, "domestic_departures": int, "international_departures": int,
    "international_seats": int, "avg_flight_distance_mi": _float,
    "avg_domestic_distance_mi": _float, "freight_lbs": int,
}  # fmt: skip


async def _copy(
    conn: asyncpg.Connection, table: str, path: Path, columns: dict[str, Callable[[str], Any]]
) -> None:
    with path.open(encoding="utf-8", newline="") as f:
        records = [
            tuple(convert(row[name]) for name, convert in columns.items())
            for row in csv.DictReader(f)
        ]
    await conn.copy_records_to_table(table, records=records, columns=list(columns))


async def _store_meta(conn: asyncpg.Connection, snapshot_dir: Path, digest: str) -> None:
    meta = json.loads((snapshot_dir / "snapshot_meta.json").read_text(encoding="utf-8"))
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


def _snapshot_hash(snapshot_dir: Path) -> str:
    digest = hashlib.sha256()
    for name in SNAPSHOT_FILES:
        digest.update(name.encode())
        # Line endings are normalised so the hash is the same on Windows and Linux checkouts.
        digest.update((snapshot_dir / name).read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()
