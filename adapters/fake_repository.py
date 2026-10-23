import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from core.errors import ToolExecutionError


class FakeRepository:
    """In-memory backend loaded from the same seed JSON as Postgres. For tests and evals."""

    def __init__(self, seed_path: Path) -> None:
        seed = json.loads(seed_path.read_text(encoding="utf-8"))
        self._products = {p["product_id"]: p for p in seed["products"]}
        self._customers = {c["customer_id"]: c for c in seed["customers"]}
        self._holdings = deepcopy(seed["holdings"])
        self._transactions = deepcopy(seed["transactions"])
        self.withdrawals: list[dict[str, Any]] = deepcopy(seed["withdrawal_requests"])

    async def verify_identity(self, customer_id: str, secret: str) -> bool:
        customer = self._customers.get(customer_id)
        return customer is not None and customer["phone_last4"] == secret

    async def get_portfolio(self, customer_id: str) -> dict[str, Any]:
        holdings = [
            {
                "product": self._products[h["product_id"]]["name"],
                "units": h["units"],
                "value_nis": h["value_nis"],
            }
            for h in self._holdings
            if h["customer_id"] == customer_id
        ]
        return {"holdings": holdings, "total_value_nis": sum(h["value_nis"] for h in holdings)}

    async def get_transactions(self, customer_id: str, limit: int) -> list[dict[str, Any]]:
        rows = [t for t in self._transactions if t["customer_id"] == customer_id]
        rows.sort(key=lambda t: t["booked_on"], reverse=True)
        return [
            {
                "date": t["booked_on"],
                "kind": t["kind"],
                "product": self._products[t["product_id"]]["name"] if t["product_id"] else None,
                "amount_nis": t["amount_nis"],
            }
            for t in rows[:limit]
        ]

    async def get_withdrawals(
        self, customer_id: str, request_id: str | None
    ) -> list[dict[str, Any]]:
        return [
            self._public_withdrawal(w)
            for w in self.withdrawals
            if w["customer_id"] == customer_id and request_id in (None, w["request_id"])
        ]

    async def create_withdrawal(
        self, customer_id: str, amount_nis: float, idempotency_key: str
    ) -> dict[str, Any]:
        for existing in self.withdrawals:
            if existing["idempotency_key"] == idempotency_key:
                return self._public_withdrawal(existing)
        row = {
            "request_id": f"W-{1001 + len(self.withdrawals)}",
            "customer_id": customer_id,
            "amount_nis": amount_nis,
            "status": "pending",
            "created_on": "today",
            "idempotency_key": idempotency_key,
        }
        self.withdrawals.append(row)
        return self._public_withdrawal(row)

    @staticmethod
    def _public_withdrawal(row: dict[str, Any]) -> dict[str, Any]:
        return {k: row[k] for k in ("request_id", "amount_nis", "status", "created_on")}


class FailingRepository(FakeRepository):
    """Every data call raises, to test graceful degradation when the backend is down."""

    async def get_portfolio(self, customer_id: str) -> dict[str, Any]:
        raise ConnectionError("backend down")

    async def get_transactions(self, customer_id: str, limit: int) -> list[dict[str, Any]]:
        raise ConnectionError("backend down")

    async def get_withdrawals(self, customer_id: str, request_id: str | None) -> list:
        raise ConnectionError("backend down")

    async def create_withdrawal(self, customer_id: str, amount_nis: float, key: str) -> dict:
        raise ToolExecutionError("backend_down", "The backend is unavailable.")
