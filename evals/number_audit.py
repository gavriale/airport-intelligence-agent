"""Number audit: every number in an answer must come from a tool result.

A number passes if it
- matches a number in a tool result (within the rounding of how it was written: "36.6M" matches
  36,590,656; "96%" matches 95.6),
- matches a number the user wrote, a number the model passed to a tool, or a number defined in
  `domain/config.yaml` (default weights, thresholds), or
- is not a data number: a year, "12 months", a rank, a list or table index, the 0 to 100 range
  ("0 to 100", "out of 100"), or part of a name ("Lower 48", "T-100", "Boeing 737").

Rounding is read generously in two ways that are real formats, not guesses: a whole number with
thousands separators that ends in zeros ("442,000") is read as rounded to the thousand at most,
and a percentage matches the same value as a fraction ("25%" for 0.25).

Anything else is reported. The audit cannot tell a number that is wrong from a number that
happens to equal another value in the tool results, so it is a strong check, not a proof.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass

NUMBER = re.compile(
    r"(?<![\w.])(-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?)"
    r"(?: ?(%|percent\b|billion\b|million\b|thousand\b|bn\b|[KMB]\b))?",
    re.IGNORECASE,
)
SCALES = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9}
# Names that contain digits. They are blanked out before numbers are looked for, so "Lower 48",
# "T-100" and "Boeing 737" are never read as data.
NAMES = re.compile(r"\bLower 48\b|\b[A-Za-z]-\d+\b|\b(?:Boeing|Airbus)\s+[A-Z]?\d{3,4}\b")
YEARS = range(1990, 2101)
MAX_RANK = 20
MAX_ROUNDED_ZEROS = 3  # "442,000" may be a rounding to the thousand; "100,000" is not read looser
EPSILON = 1e-9


@dataclass(frozen=True)
class Found:
    raw: str  # as written, e.g. "36.6M"
    value: float  # absolute value, scaled (36,600,000)
    tolerance: float  # half a unit of the last digit written, scaled
    start: int
    end: int
    plain_integer: bool  # digits only: no sign, comma, decimals or scale word
    percent: bool  # written with % or "percent"


def _tolerance(grouped: str, digits: str, scale: float) -> float:
    """Half a unit of the last digit written. A comma-grouped whole number that ends in zeros
    ("442,000") is read as rounded to its last nonzero digit, but only up to the thousands."""
    if "." in digits:
        return 0.5 * 10 ** -len(digits.split(".")[1]) * scale
    if "," in grouped:
        zeros = len(digits) - len(digits.rstrip("0"))
        return 0.5 * 10 ** min(zeros, MAX_ROUNDED_ZEROS) * scale
    return 0.5 * scale


def extract(text: str) -> list[Found]:
    text = text.replace("−", "-")  # unicode minus
    text = NAMES.sub(lambda m: " " * len(m.group(0)), text)  # same length: offsets stay valid
    found = []
    for m in NUMBER.finditer(text):
        digits = m.group(1).replace(",", "")
        suffix = (m.group(2) or "").lower()
        scale = SCALES.get(suffix, 1.0)
        found.append(
            Found(
                raw=m.group(0),
                value=abs(float(digits)) * scale,
                tolerance=_tolerance(m.group(1), digits, scale),
                start=m.start(),
                end=m.end(),
                plain_integer=m.group(0).isdigit(),
                percent=suffix in ("%", "percent"),
            )
        )
    return found


def _matches(f: Found, values: Iterable[float]) -> bool:
    """Within rounding of a known value. A percentage also matches a 0 to 1 value times 100
    (the answer says 25% where the tool says 0.25)."""
    values = list(values)
    if any(abs(f.value - v) <= f.tolerance + EPSILON for v in values):
        return True
    return f.percent and any(abs(f.value / 100 - v) <= f.tolerance / 100 + EPSILON for v in values)


def _is_structural(text: str, f: Found) -> bool:
    """Numbers that are not claims about the data."""
    text = text.replace("−", "-")
    before = text[max(0, f.start - 14) : f.start].lower()
    after = text[f.end : f.end + 16].lower()
    small = f.plain_integer and f.value <= MAX_RANK
    line_start = text.rfind("\n", 0, f.start) + 1
    prefix = text[line_start : f.start]

    if f.plain_integer and f.value in YEARS:
        return True
    if re.match(r"[\s-]*months?\b", after):  # "12 months", "24-month"
        return True
    if small and re.match(r"\s*\|", after) and re.fullmatch(r"\s*\|\s*", prefix):  # table index
        return True
    if small and after.startswith(". ") and not prefix.strip():  # "1. " list item
        return True
    if small and re.match(r"(st|nd|rd|th)\b", after) and "percentile" not in after:  # 2nd, 5th
        return True
    if small and re.search(r"(top|rank|ranked|#|no\.)\s*$", before):  # top 5, rank 1
        return True
    if (
        f.plain_integer and f.value == 100 and re.search(r"(out of|/)\s*$", before)
    ):  # 77.4 out of 100
        return True
    if f.plain_integer and f.value in (0, 100):  # the score scale "0 to 100"
        return bool(re.search(r"\b0\s*(?:–|-|to)\s*100\b", text))
    return False


def audit(
    answer: str,
    tool_texts: Iterable[str],
    allowed_texts: Iterable[str] = (),
    *,
    strict: bool = False,
) -> list[str]:
    """Descriptions of every number in `answer` that is not grounded. Empty means it passed.

    `tool_texts`: tool results and the arguments the model passed. `allowed_texts`: the user's
    messages and the config. With `strict`, no data numbers are allowed at all."""
    grounded = (
        [] if strict else [f.value for t in (*tool_texts, *allowed_texts) for f in extract(t)]
    )
    failures = []
    for f in extract(answer):
        if _is_structural(answer, f) or _matches(f, grounded):
            continue
        around = answer[max(0, f.start - 30) : f.end + 30].replace("\n", " ")
        failures.append(f"ungrounded number {f.raw!r} in '...{around}...'")
    return failures
