"""The eval machinery itself (checks, report, cost, case file) - no live model involved."""

from pathlib import Path

import pytest

from core.agent import ToolCallRecord, TurnResult
from core.interfaces import LLMResponse
from evals.judges import _parse
from evals.runner import (
    Case,
    Expect,
    Reference,
    RunResult,
    ToolArgCheck,
    UsageMeter,
    check_case,
    check_ranking_order,
    load_cases,
    p95,
    render,
)

CASES_FILE = Path(__file__).resolve().parent.parent / "domain" / "eval_cases.yaml"


def call(name, arguments=None, result="{}", is_error=False):
    return ToolCallRecord(
        name=name, arguments=arguments or {}, result=result, is_error=is_error, ms=1
    )


def turn(reply: str, *calls: ToolCallRecord) -> TurnResult:
    return TurnResult(reply=reply, tool_calls=list(calls))


def case(**expect) -> Case:
    return Case(id="c", category="x", turns=["hi"], expect=Expect(**expect))


def test_passing_case_has_no_failures():
    c = case(tools_called=["rank_airports"], answer_matches=["Apr(il)? 2026"])

    assert check_case(c, [turn("As of Apr 2026, BOS leads", call("rank_airports"))]) == []


def test_each_kind_of_failure_is_reported():
    c = case(
        tools_called=["rank_airports"],
        tools_not_called=["get_live_status"],
        answer_matches=["April 2026"],
        answer_not_matches=["secret"],
        max_words=1,
    )

    failures = check_case(c, [turn("secret words", call("get_live_status"))])

    assert len(failures) == 5  # missing tool, forbidden tool, missing text, forbidden text, length


def test_tools_are_collected_across_turns_and_answer_is_the_last_reply():
    c = case(tools_called=["a", "b"], answer_matches=["done"])

    assert check_case(c, [turn("x", call("a")), turn("done", call("b"))]) == []


def test_tool_arguments_can_be_required_to_equal_a_value_a_set_or_a_key_subset():
    c = case(
        tool_args=[
            ToolArgCheck(tool="rank_airports", arg="region", equals="New England"),
            ToolArgCheck(tool="compare_airports", arg="iatas", equals_set=["LAX", "SNA"]),
            ToolArgCheck(tool="rank_airports", arg="weights", keys_subset_of=["growth"]),
        ]
    )
    good = [
        call("rank_airports", {"region": "New England", "weights": {"growth": 0.6}}),
        call("compare_airports", {"iatas": ["sna", "LAX"]}),  # order and case do not matter
    ]
    bad = [
        call("rank_airports", {"region": "Maine", "weights": {"growth": 0.6, "scale": 0.1}}),
        call("compare_airports", {"iatas": ["LAX"]}),
    ]

    assert check_case(c, [turn("ok", *good)]) == []
    assert len(check_case(c, [turn("ok", *bad)])) == 3


def test_a_weights_argument_with_other_keys_or_none_fails_the_subset_check():
    check = ToolArgCheck(tool="rank_airports", arg="weights", keys_subset_of=["growth"])
    c = case(tool_args=[check])

    assert check_case(c, [turn("ok", call("rank_airports", {"weights": {"growth": 0.6}}))]) == []
    assert check_case(c, [turn("ok", call("rank_airports", {"weights": {"scale": 0.4}}))])
    assert check_case(c, [turn("ok", call("rank_airports", {}))])  # no weights at all


EXPECTED = [
    {"iata": "BGR", "city": "Bangor"},
    {"iata": "PWM", "city": "Portland"},
    {"iata": "BTV", "city": "Burlington"},
]


def test_ranking_order_passes_when_the_answer_lists_the_airports_in_order():
    answer = "1. Bangor (BGR)\n2. Portland (PWM)\n3. Burlington (BTV)"

    assert check_ranking_order(answer, EXPECTED) == []


def test_ranking_order_fails_for_a_different_order_or_a_missing_airport():
    swapped = "Portland (PWM), then Bangor (BGR), then Burlington (BTV)"
    missing = "Bangor (BGR) and Portland (PWM)"

    assert "order" in check_ranking_order(swapped, EXPECTED)[0]
    assert "missing" in check_ranking_order(missing, EXPECTED)[0]


def test_ranking_order_is_checked_inside_check_case():
    c = case(ranking_order={"source": "tool"})
    reference = Reference(ranking=EXPECTED)

    assert check_case(c, [turn("Bangor, Portland, Burlington")], reference) == []
    assert check_case(c, [turn("Burlington, Portland, Bangor")], reference)
    assert check_case(c, [turn("anything")], Reference())  # no reference ranking: a failure


def test_the_number_audit_is_part_of_every_case():
    c = case()
    grounded = turn("36.6M passengers", call("compare_airports", result='{"p": 36590656}'))
    invented = turn("37.9M passengers", call("compare_airports", result='{"p": 36590656}'))

    assert check_case(c, [grounded]) == []
    assert "ungrounded number" in check_case(c, [invented])[0]


def test_numbers_in_the_users_message_and_the_models_tool_arguments_are_not_flagged():
    c = case()
    reference = Reference(allowed_texts=["Which are the top 7 airports?"])
    result = turn("The 7 airports", call("rank_airports", {"top_n": 12}))

    assert check_case(c, [result], reference) == []
    assert check_case(case(), [turn("12 airports", call("rank_airports", {"top_n": 12}))]) == []


def test_no_numbers_mode_rejects_any_data_number():
    c = case(no_numbers=True)

    assert check_case(c, [turn("Heathrow is outside the US airports I cover")]) == []
    assert check_case(c, [turn("Heathrow handles 80 million passengers")])


def test_judge_parse_accepts_fenced_json_and_fails_closed():
    assert _parse('```json\n{"grounded": true, "reason": "ok"}\n```').grounded
    assert not _parse("I think it is fine").grounded


# ---------- cost and report ----------


def test_cost_counts_cache_reads_and_writes_at_their_own_rates():
    meter = UsageMeter(inner=None)
    meter.input, meter.cache_read, meter.cache_write, meter.output = (
        1_000_000,
        400_000,
        100_000,
        100_000,
    )

    # uncached 500k * 2 + write 100k * 2 * 1.25 + read 400k * 2 * 0.1 + output 100k * 10
    assert meter.cost_usd("claude-sonnet-5-5") == pytest.approx(1.0 + 0.25 + 0.08 + 1.0)
    assert meter.cost_usd("some-other-model") is None


async def test_the_meter_adds_up_every_call_including_the_judges():
    class Inner:
        async def complete(self, system, messages, tools):
            return LLMResponse(
                text="x", input_tokens=100, output_tokens=10, cache_read_tokens=60,
                cache_write_tokens=20,
            )  # fmt: skip

    meter = UsageMeter(Inner())
    await meter.complete("s", [], [])
    await meter.complete("s", [], [])

    assert (meter.calls, meter.input, meter.output) == (2, 200, 20)
    assert (meter.cache_read, meter.cache_write) == (120, 40)


def test_p95_and_report_show_safety_runs_as_x_of_n_and_list_failures():
    cases = [
        Case(id="a", category="k", turns=["q"]),
        Case(id="b", category="k", turns=["q"], safety=True),
    ]

    def result(case_id, run, passed, failures=()):
        return RunResult(
            case_id=case_id, category="k", run=run, passed=passed, failures=list(failures),
            latencies_ms=[100.0], transcript="",
        )  # fmt: skip

    runs = [
        result("a", 1, True),
        result("b", 1, True),
        result("b", 2, False, ["boom"]),
        result("b", 3, True),
    ]

    report = render(cases, runs, model="m", seconds=12.0, meter=None)

    assert p95([100.0] * 19 + [900.0]) == 100.0
    assert "| a | k | pass (1/1) |" in report
    assert "| b | k | FAIL (2/3) |" in report  # a safety case must pass all three runs
    assert "| k | 1 | 2 | 50% |" in report
    assert "`b` run 2" in report and "boom" in report


# ---------- the case file ----------


def test_eval_case_file_is_well_formed():
    cases = load_cases(CASES_FILE)

    assert len({c.id for c in cases}) == len(cases)
    assert {c.category for c in cases} >= {"assignment", "data_limits", "names", "robustness"}
    safety = [c for c in cases if c.safety]
    assert len(safety) >= 10
    assert all(c.turns for c in cases)


def test_the_assignment_questions_are_in_the_case_file():
    cases = {c.id: c for c in load_cases(CASES_FILE)}

    assert cases["ne_ranking"].expect.ranking_order.source == "endpoint"
    assert cases["ne_reweight"].expect.ranking_order.source == "tool"
    assert cases["heathrow_scope"].expect.no_numbers
    assert cases["backend_outage"].backend == "failing"
    for needed in ("la_vs_sna", "anc_long_haul", "sfo_unmet"):
        assert needed in cases
