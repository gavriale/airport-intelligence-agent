"""The eval machinery itself (scoring, judge parsing, case file) - no live model involved."""

from pathlib import Path

from core.agent import ToolCallRecord, TurnResult
from evals.judges import _parse
from evals.runner import Case, CaseResult, Expect, check_case, load_cases, p95, render

CASES_FILE = Path(__file__).resolve().parent.parent / "domain" / "eval_cases.yaml"


def turn(reply: str, tools=()) -> TurnResult:
    records = [
        ToolCallRecord(name=n, arguments={}, result="{}", is_error=False, ms=1) for n in tools
    ]
    return TurnResult(reply=reply, tool_calls=records)


def case(**expect) -> Case:
    return Case(id="c", category="x", turns=["hi"], expect=Expect(**expect))


def test_passing_case_has_no_failures():
    c = case(tools_called=["rank_airports"], answer_matches=["April 2026"])

    assert check_case(c, [turn("As of April 2026, BOS leads", ["rank_airports"])]) == []


def test_each_kind_of_failure_is_reported():
    c = case(
        tools_called=["rank_airports"],
        tools_not_called=["get_live_status"],
        answer_matches=["April 2026"],
        answer_not_matches=["secret"],
    )

    failures = check_case(c, [turn("secret", ["get_live_status"])])

    assert len(failures) == 4


def test_tools_are_collected_across_turns_and_answer_is_the_last_reply():
    c = case(tools_called=["a", "b"], answer_matches=["done"])

    assert check_case(c, [turn("x", ["a"]), turn("done", ["b"])]) == []


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


def test_eval_case_file_loads_and_ids_are_unique():
    cases = load_cases(CASES_FILE)  # empty until the evals stage

    assert len({c.id for c in cases}) == len(cases)
