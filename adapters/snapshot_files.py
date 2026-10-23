"""Reading the committed snapshot files (domain/data/*.csv). Shared by both repositories."""

import csv
import hashlib
import json
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

SNAPSHOT_FILES = ("airports.csv", "runways.csv", "airport_month.csv", "snapshot_meta.json")


def _text(value: str) -> str | None:
    return value or None


def _int(value: str) -> int | None:
    return round(float(value)) if value else None


def _float(value: str) -> float | None:
    return float(value) if value else None


def _bool(value: str) -> bool:
    return value == "true"


# column name -> converter from the CSV text
AIRPORT_COLUMNS: dict[str, Callable[[str], Any]] = {
    "iata": str, "ident": str, "name": str, "city": _text, "state": str,
    "latitude": float, "longitude": float, "elevation_ft": _int, "type": str,
    "scheduled_service": _bool,
}  # fmt: skip
RUNWAY_COLUMNS: dict[str, Callable[[str], Any]] = {
    "airport_iata": str, "runway": str, "length_ft": _int, "width_ft": _int,
    "surface": _text, "lighted": _bool,
}  # fmt: skip
TRAFFIC_COLUMNS: dict[str, Callable[[str], Any]] = {
    "iata": str, "month": date.fromisoformat, "departures": int, "passengers": int,
    "seats": int, "domestic_departures": int, "international_departures": int,
    "international_seats": int, "avg_flight_distance_mi": _float,
    "avg_domestic_distance_mi": _float, "freight_lbs": int,
}  # fmt: skip


def read_records(path: Path, columns: dict[str, Callable[[str], Any]]) -> list[tuple]:
    """One typed tuple per CSV row, in the order of `columns`."""
    with path.open(encoding="utf-8", newline="") as f:
        return [
            tuple(convert(row[name]) for name, convert in columns.items())
            for row in csv.DictReader(f)
        ]


def read_meta(snapshot_dir: Path) -> dict[str, Any]:
    return json.loads((snapshot_dir / "snapshot_meta.json").read_text(encoding="utf-8"))


def snapshot_hash(snapshot_dir: Path, extra: bytes = b"") -> str:
    """Hash of the snapshot files plus `extra` (what else decides the loaded data: the schema and
    the runway rule), so changing those reloads the data too."""
    digest = hashlib.sha256(extra)
    for name in SNAPSHOT_FILES:
        digest.update(name.encode())
        # Line endings are normalised so the hash is the same on Windows and Linux checkouts.
        digest.update((snapshot_dir / name).read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()
