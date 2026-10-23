import json
from datetime import date
from pathlib import Path
from typing import Any

import asyncpg


def _num(value: Any) -> float:
    return float(value)


class PostgresRepository:
    """Simulated client backend. All queries are parameterised."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, dsn: str) -> "PostgresRepository":
        return cls(await asyncpg.create_pool(dsn, min_size=1, max_size=10))

    async def close(self) -> None:
        await self._pool.close()

    async def init_schema_and_seed(self, schema_path: Path, seed_path: Path) -> None:
        """Idempotent: CREATE ... IF NOT EXISTS and INSERT ... ON CONFLICT DO NOTHING."""
        seed = json.loads(seed_path.read_text(encoding="utf-8"))
        async with self._pool.acquire() as conn, conn.transaction():
            # Serialise concurrent starts (several replicas booting at once).
            await conn.execute("SELECT pg_advisory_xact_lock(42)")
            await conn.execute(schema_path.read_text(encoding="utf-8"))
            await self._seed(conn, seed)

    @staticmethod
    async def _seed(conn: asyncpg.Connection, seed: dict[str, list[dict[str, Any]]]) -> None:
        def d(value: str) -> date:
            return date.fromisoformat(value)

        await conn.executemany(
            "INSERT INTO products VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
            [(p["product_id"], p["name"], p["kind"]) for p in seed["products"]],
        )
        await conn.executemany(
            "INSERT INTO customers VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
            [(c["customer_id"], c["name"], c["phone_last4"]) for c in seed["customers"]],
        )
        await conn.executemany(
            "INSERT INTO holdings VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING",
            [
                (h["customer_id"], h["product_id"], h["units"], h["value_nis"])
                for h in seed["holdings"]
            ],
        )
        await conn.executemany(
            "INSERT INTO transactions VALUES ($1, $2, $3, $4, $5, $6) ON CONFLICT DO NOTHING",
            [
                (
                    t["id"],
                    t["customer_id"],
                    d(t["booked_on"]),
                    t["kind"],
                    t["product_id"],
                    t["amount_nis"],
                )
                for t in seed["transactions"]
            ],
        )
        await conn.executemany(
            "INSERT INTO withdrawal_requests"
            " (request_id, customer_id, amount_nis, status, created_on, idempotency_key)"
            " VALUES ($1, $2, $3, $4, $5, $6) ON CONFLICT DO NOTHING",
            [
                (
                    w["request_id"],
                    w["customer_id"],
                    w["amount_nis"],
                    w["status"],
                    d(w["created_on"]),
                    w["idempotency_key"],
                )
                for w in seed["withdrawal_requests"]
            ],
        )

    async def verify_identity(self, customer_id: str, secret: str) -> bool:
        row = await self._pool.fetchrow(
            "SELECT 1 FROM customers WHERE customer_id = $1 AND phone_last4 = $2",
            customer_id,
            secret,
        )
        return row is not None

    async def get_portfolio(self, customer_id: str) -> dict[str, Any]:
        rows = await self._pool.fetch(
            "SELECT p.name AS product, h.units, h.value_nis FROM holdings h"
            " JOIN products p USING (product_id) WHERE h.customer_id = $1 ORDER BY p.name",
            customer_id,
        )
        holdings = [
            {"product": r["product"], "units": _num(r["units"]), "value_nis": _num(r["value_nis"])}
            for r in rows
        ]
        return {"holdings": holdings, "total_value_nis": sum(h["value_nis"] for h in holdings)}

    async def get_transactions(self, customer_id: str, limit: int) -> list[dict[str, Any]]:
        rows = await self._pool.fetch(
            "SELECT t.booked_on, t.kind, p.name AS product, t.amount_nis FROM transactions t"
            " LEFT JOIN products p USING (product_id) WHERE t.customer_id = $1"
            " ORDER BY t.booked_on DESC, t.id DESC LIMIT $2",
            customer_id,
            limit,
        )
        return [
            {
                "date": r["booked_on"].isoformat(),
                "kind": r["kind"],
                "product": r["product"],
                "amount_nis": _num(r["amount_nis"]),
            }
            for r in rows
        ]

    async def get_withdrawals(
        self, customer_id: str, request_id: str | None
    ) -> list[dict[str, Any]]:
        rows = await self._pool.fetch(
            "SELECT request_id, amount_nis, status, created_on FROM withdrawal_requests"
            " WHERE customer_id = $1 AND ($2::text IS NULL OR request_id = $2)"
            " ORDER BY created_on DESC, request_id DESC",
            customer_id,
            request_id,
        )
        return [_withdrawal(r) for r in rows]

    async def create_withdrawal(
        self, customer_id: str, amount_nis: float, idempotency_key: str
    ) -> dict[str, Any]:
        """A repeated idempotency key returns the original row instead of inserting again."""
        row = await self._pool.fetchrow(
            "INSERT INTO withdrawal_requests (request_id, customer_id, amount_nis, status,"
            " idempotency_key) VALUES ('W-' || nextval('withdrawal_seq'), $1, $2, 'pending', $3)"
            " ON CONFLICT (idempotency_key) DO NOTHING"
            " RETURNING request_id, amount_nis, status, created_on",
            customer_id,
            amount_nis,
            idempotency_key,
        )
        if row is None:
            row = await self._pool.fetchrow(
                "SELECT request_id, amount_nis, status, created_on FROM withdrawal_requests"
                " WHERE idempotency_key = $1",
                idempotency_key,
            )
        return _withdrawal(row)


def _withdrawal(row: asyncpg.Record) -> dict[str, Any]:
    return {
        "request_id": row["request_id"],
        "amount_nis": _num(row["amount_nis"]),
        "status": row["status"],
        "created_on": row["created_on"].isoformat(),
    }
