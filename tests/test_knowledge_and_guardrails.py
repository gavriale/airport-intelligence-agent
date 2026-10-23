import pytest

from adapters.bm25_index import BM25Index
from core.errors import PolicyViolation
from tests.conftest import DOMAIN


@pytest.mark.parametrize(
    "query,expected_doc",
    [
        ("what is the early withdrawal fee", "early_withdrawal_fee"),
        ("management fee for global equity fund", "fees"),
        ("how long does a withdrawal take", "withdrawal_rules"),
        ("when are human agents available", "contact_hours"),
    ],
)
async def test_bm25_returns_the_right_doc_first(query, expected_doc):
    hits = await BM25Index(DOMAIN / "knowledge").search(query)

    assert hits[0].doc_id == expected_doc


async def test_bm25_returns_nothing_for_unrelated_query():
    assert await BM25Index(DOMAIN / "knowledge").search("zxqv") == []


@pytest.mark.parametrize(
    "text",
    [
        "You should buy the Tel Aviv 35 fund.",
        "I recommend you sell your bond holdings.",
        "I suggest switching... actually I suggest you switch to equities.",
    ],
)
def test_advice_is_blocked(rig, text):
    with pytest.raises(PolicyViolation):
        rig([]).guardrails.check_output(text)


@pytest.mark.parametrize(
    "text",
    [
        "I can't tell you whether you should buy or sell; a licensed advisor can help.",
        "I recommend speaking with a licensed advisor.",
        "The Money Market Fund fee is 0.3% per year.",
    ],
)
def test_normal_and_refusal_text_passes(rig, text):
    rig([]).guardrails.check_output(text)
