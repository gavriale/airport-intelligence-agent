"""One contract, two implementations.

The in-memory repository always runs. The Postgres one runs when a database is reachable
(`docker compose up -d postgres`, with DATABASE_URL pointing at it) and is skipped otherwise.
"""

import os
import shutil
from pathlib import Path

import asyncpg
import pytest

from adapters.postgres_repository import PostgresRepository

DATA = Path(__file__).resolve().parent.parent / "domain" / "data"
SCHEMA = DATA / "schema.sql"
DSN = os.environ.get("DATABASE_URL", "postgresql://agent:agent@localhost:5432/agent")
NEW_ENGLAND = ["CT", "MA", "ME", "NH", "RI", "VT"]


async def connect_postgres() -> PostgresRepository:
    try:
        repository = await PostgresRepository.connect(DSN)
    except (OSError, asyncpg.PostgresError):
        pytest.skip("Postgres not available")
    await repository.load_snapshot(SCHEMA, DATA)  # leaves the real snapshot loaded
    return repository


@pytest.fixture
async def pg():
    repository = await connect_postgres()
    yield repository
    await repository.load_snapshot(SCHEMA, DATA)  # restore after tests that load another one
    await repository.close()


@pytest.fixture(params=["memory", "postgres"])
async def repo(request, memory_repo):
    if request.param == "memory":
        yield memory_repo
        return
    repository = await connect_postgres()
    yield repository
    await repository.close()


# ---------- the contract, for both implementations ----------


async def test_airports_come_with_runway_counts_and_traffic_flag(repo):
    anc, sfo = await repo.list_airports(iatas=["ANC", "SFO"])

    assert (anc.state, sfo.state) == ("AK", "CA")
    assert anc.runway_count >= 1
    assert sfo.runway_count >= 2
    assert 1 <= sfo.commercial_runway_count <= sfo.runway_count
    assert sfo.longest_runway_ft and sfo.longest_runway_ft > 10_000
    assert anc.has_traffic and sfo.has_traffic


async def test_filtering_by_state_and_peers_only(repo):
    everything = await repo.list_airports(states=NEW_ENGLAND)
    peers = await repo.list_airports(states=NEW_ENGLAND, peers_only=True)

    assert {a.state for a in everything} <= set(NEW_ENGLAND)
    assert {"BOS", "BDL", "PVD"} <= {a.iata for a in peers}
    assert len(peers) < len(everything)  # small fields without traffic data are excluded
    assert all(a.has_traffic for a in peers)


async def test_commercial_runways_exclude_short_strips(repo):
    bos, sna = await repo.list_airports(iatas=["SNA", "BOS"])  # ordered by code

    assert (sna.runway_count, sna.commercial_runway_count) == (2, 1)  # 2,886 ft strip left out
    assert bos.commercial_runway_count < bos.runway_count  # 2,557 ft strip left out


async def test_airports_are_ordered_by_code(repo):
    codes = [a.iata for a in await repo.list_airports(states=NEW_ENGLAND)]

    assert codes == sorted(codes)


async def test_traffic_is_ordered_and_complete_for_one_airport(repo):
    rows = await repo.get_traffic(["ANC"])
    months = [r.month for r in rows]

    assert months == sorted(months)
    assert len(months) == 88  # Jan 2019 to Apr 2026
    assert {r.iata for r in rows} == {"ANC"}


async def test_all_peers_are_returned_when_no_airport_is_given(repo):
    info = await repo.get_snapshot_info()

    rows = await repo.get_traffic()

    assert len({r.iata for r in rows}) == info.peer_count


async def test_snapshot_info_reports_the_period_and_counts(repo):
    info = await repo.get_snapshot_info()

    assert info.latest_period.isoformat() == "2026-04-01"
    assert info.peer_min_annual_passengers == 100_000
    assert info.airport_count > 1000


async def test_unknown_airport_returns_nothing(repo):
    assert await repo.list_airports(iatas=["ZZZ"]) == []
    assert await repo.get_traffic(["ZZZ"]) == []


async def test_both_repositories_return_identical_data(memory_repo, pg):
    assert await pg.list_airports() == await memory_repo.list_airports()
    assert await pg.get_traffic(["ANC", "SFO"]) == await memory_repo.get_traffic(["ANC", "SFO"])


# ---------- Postgres snapshot loading ----------


def tiny_snapshot(tmp_path: Path, *, passengers: str = "1000") -> Path:
    (tmp_path / "airports.csv").write_text(
        "iata,ident,name,city,state,latitude,longitude,elevation_ft,type,scheduled_service\n"
        "AAA,KAAA,Alpha,Alphaville,MA,41.0,-71.0,10,medium_airport,true\n",
        encoding="utf-8",
    )
    (tmp_path / "runways.csv").write_text(
        "airport_iata,runway,length_ft,width_ft,surface,lighted\nAAA,04/22,7000,150,ASP,true\n",
        encoding="utf-8",
    )
    (tmp_path / "airport_month.csv").write_text(
        "iata,month,departures,passengers,seats,domestic_departures,international_departures,"
        "international_seats,avg_flight_distance_mi,avg_domestic_distance_mi,freight_lbs\n"
        f"AAA,2026-04-01,10,{passengers},1500,10,0,0,500.0,500.0,0\n",
        encoding="utf-8",
    )
    shutil.copy(DATA / "snapshot_meta.json", tmp_path / "snapshot_meta.json")
    return tmp_path


async def test_loading_the_same_snapshot_again_is_skipped(pg):
    assert await pg.load_snapshot(SCHEMA, DATA) is False


async def test_a_different_snapshot_replaces_the_data_completely(pg, tmp_path):
    assert await pg.load_snapshot(SCHEMA, tiny_snapshot(tmp_path)) is True

    airports = await pg.list_airports()
    traffic = await pg.get_traffic()

    assert [a.iata for a in airports] == ["AAA"]
    assert [t.passengers for t in traffic] == [1000]


async def test_changed_values_are_picked_up_on_reload(pg, tmp_path):
    await pg.load_snapshot(SCHEMA, tiny_snapshot(tmp_path, passengers="1000"))
    await pg.load_snapshot(SCHEMA, tiny_snapshot(tmp_path, passengers="2000"))

    assert [t.passengers for t in await pg.get_traffic()] == [2000]
