"""The number audit: what counts as grounded, what is allowed, what is reported."""

import pytest

from evals.number_audit import audit, extract


def failures(answer, tool="", allowed="", strict=False):
    return audit(answer, [tool], [allowed], strict=strict)


@pytest.mark.parametrize(
    "answer,tool",
    [
        ("LAX has 36.6M passengers", '{"passengers": 36590656}'),  # millions, rounded
        ("441,517 passengers", '{"passengers": 441517}'),  # thousands separator, exact
        ("about 96% of 2019", '{"passengers_pct_of_2019": 95.6}'),  # rounded to a whole number
        ("growth of 12.8%", '{"passenger_growth_pct": 12.81}'),
        ("a ratio of 1.64 times", '{"ratio_highest_to_lowest": 1.64}'),
        ("down 3.3%", '{"passenger_growth_pct": -3.3}'),  # the sign is not compared
        ("5.8 billion lb of freight", '{"freight_lbs": 5772333133}'),
        ("the 88.8th percentile", '{"percentile": 88.8}'),
    ],
)
def test_numbers_that_match_a_tool_result_within_rounding_pass(answer, tool):
    assert failures(answer, tool) == []


@pytest.mark.parametrize(
    "answer,tool",
    [
        ("about 94% of 2019", '{"x": 95.6}'),  # off by more than rounding
        ("growth of 12.7%", '{"x": 12.81}'),
        ("5.7 billion lb of freight", '{"x": 5772333133}'),  # 5.77 rounds to 5.8, not 5.7
        ("1,500 flights", '{"x": 86373}'),
        ("the 91st percentile", '{"x": 50.0}'),  # a percentile is data, not a rank
    ],
)
def test_numbers_that_are_not_in_the_tool_results_are_reported(answer, tool):
    result = failures(answer, tool)

    assert len(result) == 1 and "ungrounded number" in result[0]


def test_the_report_quotes_the_number_and_its_surroundings():
    [message] = failures("SFO handled 1,500 flights", '{"x": 1}')

    assert "'1,500'" in message and "SFO handled" in message


@pytest.mark.parametrize(
    "answer",
    [
        "Data covers May 2025 to Apr 2026, compared with May 2024 to Apr 2025.",  # years
        "over the last 12 months and the 24-month history",
        "| 1 | Bangor | 70.6 |",  # table index (70.6 is checked separately)
        "1. First point\n2. Second point",  # list numbering
        "Boston moved from 4th to 5th place",  # ordinals are ranks
        "the top 5 airports and rank 1",
        "scored from 0 to 100",
    ],
)
def test_non_data_numbers_are_allowed(answer):
    audited = [f for f in failures(answer, "") if "70.6" not in f]

    assert audited == []


def test_zero_and_one_hundred_are_only_allowed_as_the_score_range():
    assert failures("a score of 100", "")  # flagged: no "0 to 100" in the text
    assert failures("scores run from 0 to 100", "") == []


def test_numbers_the_user_or_the_config_gave_are_allowed():
    assert failures("You asked about Terminal 2", "", allowed="How many gates in Terminal 2?") == []
    assert failures("the default weight is 0.25", "", allowed="weights:\n  growth: 0.25") == []
    assert failures("the default weight is 0.30", "", allowed="weights:\n  growth: 0.25")


def test_strict_mode_allows_no_data_numbers_at_all():
    answer = "In 2026 there are 3 airports, ranked 1st"

    result = failures(answer, tool='{"x": 3}', allowed="3", strict=True)

    assert len(result) == 1 and "'3'" in result[0]  # the year and the ordinal are still fine


def test_identifiers_with_digits_are_not_numbers():
    assert extract("a B737 or an H1 helipad") == []


@pytest.mark.parametrize(
    "answer",
    [
        "flights to the Lower 48",
        "BTS T-100 data",
        "a Boeing 737 or an Airbus A320 or Airbus 320",
        "form F-35 and U-2",
    ],
)
def test_names_that_contain_digits_are_not_numbers(answer):
    assert failures(answer, "") == []


def test_a_standalone_number_next_to_such_a_name_is_still_checked():
    result = failures("48 flights to the Lower 48 on T-100 data", "")

    assert len(result) == 1 and "'48'" in result[0]
    assert failures("100 routes in BTS T-100 data", "")  # the bare 100 is still ungrounded


def test_extraction_reads_scale_words_and_tolerance():
    [m] = extract("36.6M passengers")

    assert m.value == pytest.approx(36_600_000)
    assert m.tolerance == pytest.approx(50_000)
