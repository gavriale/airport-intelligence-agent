"""The eval machinery itself (scoring, judge parsing, case file) - no live model involved."""

import pytest

from core.agent import ToolCallRecord, TurnResult
from evals.judges import _parse
from evals.runner import Case, CaseResult, Expect, check_case, load_cases, p95, render
from tests.conftest import DOMAIN


def turn(reply: str, tools=(), escalated=False) -> TurnResult:
    records = [
        ToolCallRecord(name=n, arguments={}, result="{}", is_error=False, ms=1) for n in tools
    ]
    return TurnResult(reply=reply, tool_calls=records, escalated=escalated)


def case(**expect) -> Case:
    return Case(id="c", category="x", turns=["hi"], expect=Expect(**expect))


def test_passing_case_has_no_failures():
    c = case(tools_called=["get_portfolio"], answer_matches=["125,?400"], escalated=False)

    assert check_case(c, [turn("You have 125,400 NIS", ["get_portfolio"])], 0) == []


def test_each_kind_of_failure_is_reported():
    c = case(
        tools_called=["get_portfolio"],
        tools_not_called=["request_withdrawal"],
        answer_matches=["125,?400"],
        answer_not_matches=["secret"],
        escalated=True,
        withdrawals_created=0,
    )

    failures = check_case(c, [turn("secret", ["request_withdrawal"])], 1)

    assert len(failures) == 6


def test_tools_are_collected_across_turns_and_answer_is_the_last_reply():
    c = case(tools_called=["a", "b"], answer_matches=["done"])

    assert check_case(c, [turn("x", ["a"]), turn("done", ["b"])], 0) == []


def test_judge_parse_accepts_fenced_json_and_fails_closed():
    assert _parse('```json\n{"grounded": true, "reason": "ok"}\n```').grounded
    assert not _parse("I think it is fine").grounded


def test_p95_and_report():
    assert p95([100.0] * 19 + [900.0]) == 100.0
    results = [
        CaseResult(id="a", category="k", passed=True, failures=[], latencies_ms=[100.0]),
        CaseResult(id="b", category="k", passed=False, failures=["boom"], latencies_ms=[300.0]),
    ]

    report = render(results, "m")

    assert "| k | 1 | 2 | 50% |" in report
    assert "`b`: boom" in report


@pytest.mark.parametrize("path", [DOMAIN / "eval_cases.yaml"])
def test_eval_case_file_is_valid_and_covers_every_category(path):
    cases = load_cases(path)

    assert 15 <= len(cases) <= 20
    assert len({c.id for c in cases}) == len(cases)
    assert {c.category for c in cases} >= {
        "happy_path",
        "knowledge",
        "identity_gate",
        "write_action",
        "advice_refusal",
        "escalation",
        "out_of_scope",
        "injection",
        "multi_turn",
        "tool_failure",
    }
