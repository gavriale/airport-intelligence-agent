"""Runs against a real Postgres (`docker compose up postgres`); skipped when unreachable."""

import os

import asyncpg
import pytest

from adapters.postgres_repository import PostgresRepository
from tests.conftest import DOMAIN

DSN = os.environ.get("DATABASE_URL", "postgresql://agent:agent@localhost:5432/agent")


@pytest.fixture
async def repo():
    try:
        repository = await PostgresRepository.connect(DSN)
    except (OSError, asyncpg.PostgresError):
        pytest.skip("Postgres not available")
    await repository.init_schema_and_seed(
        DOMAIN / "data" / "schema.sql", DOMAIN / "data" / "seed.json"
    )
    yield repository
    await repository.close()


async def test_seed_is_idempotent(repo):
    await repo.init_schema_and_seed(DOMAIN / "data" / "schema.sql", DOMAIN / "data" / "seed.json")

    portfolio = await repo.get_portfolio("C001")

    assert portfolio["total_value_nis"] == 125400.0
    assert len(portfolio["holdings"]) == 2


async def test_verify_identity(repo):
    assert await repo.verify_identity("C001", "4412")
    assert not await repo.verify_identity("C001", "0000")


async def test_transactions_newest_first_and_limited(repo):
    rows = await repo.get_transactions("C001", 2)

    assert [r["date"] for r in rows] == ["2025-10-10", "2025-10-01"]


async def test_withdrawal_idempotency(repo):
    first = await repo.create_withdrawal("C004", 123.0, "test-key-idem")
    second = await repo.create_withdrawal("C004", 123.0, "test-key-idem")

    assert first["request_id"] == second["request_id"]
