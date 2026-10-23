"""Registry gates: identity, argument validation, error handling, write confirmation."""

import asyncio
import json

from adapters.fake_repository import FailingRepository
from core.session import Session
from tests.conftest import DOMAIN, call


async def run(r, session: Session, name: str, call_id: str = "t1", **arguments):
    result = await r.tools.execute(call(name, call_id, **arguments), session)
    return result, json.loads(result.content)


def verified(customer_id="C001", turn=1) -> Session:
    return Session(id="s1", verified_customer_id=customer_id, turn=turn)


async def test_identity_gate_blocks_data_tools_in_code(rig):
    r = rig([])
    session = Session(id="s1")

    for name in ("get_portfolio", "get_recent_transactions", "get_withdrawal_status"):
        result, body = await run(r, session, name)
        assert result.is_error
        assert body["error"]["code"] == "identity_not_verified"


async def test_tools_use_session_customer_not_model_arguments(rig):
    r = rig([])

    result, body = await run(r, verified("C001"), "get_portfolio", customer_id="C007")

    assert body["total_value_nis"] == 125400.0  # C001's, extra argument ignored


async def test_verify_success_marks_session(rig):
    r = rig([])
    session = Session(id="s1")

    _, body = await run(r, session, "verify_identity", customer_id="C001", phone_last4="4412")

    assert body == {"verified": True}
    assert session.verified_customer_id == "C001"


async def test_two_failed_verifications_escalate(rig):
    r = rig([])
    session = Session(id="s1")

    _, first = await run(r, session, "verify_identity", customer_id="C001", phone_last4="0000")
    _, second = await run(r, session, "verify_identity", customer_id="C001", phone_last4="1111")

    assert first == {"verified": False, "escalated": False}
    assert second == {"verified": False, "escalated": True}
    assert session.escalated
    assert session.handoff.reason == "identity_verification_failed"
    assert session.verified_customer_id is None


async def test_unknown_customer_looks_like_wrong_digits(rig):
    r = rig([])

    _, body = await run(
        r, Session(id="s1"), "verify_identity", customer_id="C999", phone_last4="4412"
    )

    assert body == {"verified": False, "escalated": False}


async def test_cannot_switch_customer_after_verification(rig):
    r = rig([])
    session = verified("C001")

    result, body = await run(r, session, "verify_identity", customer_id="C002", phone_last4="9087")

    assert result.is_error
    assert body["error"]["code"] == "already_verified"
    assert session.verified_customer_id == "C001"


async def test_invalid_arguments_return_structured_error(rig):
    r = rig([])

    result, body = await run(r, Session(id="s1"), "verify_identity", customer_id="C001")

    assert result.is_error
    assert body["error"]["code"] == "invalid_arguments"


async def test_backend_failure_becomes_internal_error_without_details(rig):
    r = rig([], repo=FailingRepository(DOMAIN / "data" / "seed.json"))
    r.tools._timeout_s = 1

    result, body = await run(r, verified(), "get_portfolio")

    assert result.is_error
    assert body["error"]["code"] == "internal_error"
    assert "backend down" not in result.content


async def test_slow_tool_times_out(rig):
    r = rig([], tool_timeout_s=0.01)

    async def slow(customer_id):
        await asyncio.sleep(1)

    r.repo.get_portfolio = slow

    result, body = await run(r, verified(), "get_portfolio")

    assert body["error"]["code"] == "internal_error"


async def test_write_first_call_only_proposes(rig):
    r = rig([])
    session = verified(turn=1)

    _, body = await run(r, session, "request_withdrawal", amount_nis=5000)

    assert body["status"] == "confirmation_required"
    assert len(r.repo.withdrawals) == 3  # unchanged seed rows
    assert session.pending_action is not None


async def test_write_cannot_be_confirmed_in_the_same_turn(rig):
    r = rig([])
    session = verified(turn=1)

    await run(r, session, "request_withdrawal", amount_nis=5000)
    _, body = await run(r, session, "request_withdrawal", amount_nis=5000)

    assert body["status"] == "confirmation_required"
    assert len(r.repo.withdrawals) == 3


async def test_write_executes_after_confirmation_on_a_later_turn(rig):
    r = rig([])
    session = verified(turn=1)
    await run(r, session, "request_withdrawal", amount_nis=5000)
    session.turn = 2

    _, body = await run(r, session, "request_withdrawal", amount_nis=5000)

    assert body["executed"] is True
    assert body["withdrawal_request"]["status"] == "pending"
    assert len(r.repo.withdrawals) == 4
    assert session.pending_action is None


async def test_changed_amount_needs_new_confirmation(rig):
    r = rig([])
    session = verified(turn=1)
    await run(r, session, "request_withdrawal", amount_nis=5000)
    session.turn = 2

    _, body = await run(r, session, "request_withdrawal", amount_nis=9000)

    assert body["status"] == "confirmation_required"
    assert len(r.repo.withdrawals) == 3


async def test_repository_idempotency_key_prevents_duplicates(rig):
    r = rig([])

    first = await r.repo.create_withdrawal("C001", 100.0, "key-1")
    second = await r.repo.create_withdrawal("C001", 100.0, "key-1")

    assert first == second
    assert len(r.repo.withdrawals) == 4


async def test_withdrawal_above_balance_is_refused(rig):
    r = rig([])
    session = verified(turn=1)
    await run(r, session, "request_withdrawal", amount_nis=999999)
    session.turn = 2

    result, body = await run(r, session, "request_withdrawal", amount_nis=999999)

    assert body["error"]["code"] == "insufficient_balance"
    assert len(r.repo.withdrawals) == 3
