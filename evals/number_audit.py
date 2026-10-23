"""Number audit: every number in an answer must come from a tool result.

A number passes if it
- matches a number in a tool result (within the rounding of how it was written: "36.6M" matches
  36,590,656; "96%" matches 95.6),
- matches a number the user wrote, a number the model passed to a tool, or a number defined in
  `domain/config.yaml` (default weights, thresholds), or
- is not a data number: a year, "12 months", a rank, a list or table index, the 0 to 100 range,
  or part of a name ("Lower 48", "T-100", "Boeing 737").

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
EPSILON = 1e-9


@dataclass(frozen=True)
class Found:
    raw: str  # as written, e.g. "36.6M"
    value: float  # absolute value, scaled (36,600,000)
    tolerance: float  # half a unit of the last digit written, scaled
    start: int
    end: int
    plain_integer: bool  # digits only: no sign, comma, decimals or scale word


def extract(text: str) -> list[Found]:
    text = text.replace("−", "-")  # unicode minus
    text = NAMES.sub(lambda m: " " * len(m.group(0)), text)  # same length: offsets stay valid
    found = []
    for m in NUMBER.finditer(text):
        digits = m.group(1).replace(",", "")
        decimals = len(digits.split(".")[1]) if "." in digits else 0
        scale = SCALES.get((m.group(2) or "").lower(), 1.0)
        found.append(
            Found(
                raw=m.group(0),
                value=abs(float(digits)) * scale,
                tolerance=0.5 * 10**-decimals * scale,
                start=m.start(),
                end=m.end(),
                plain_integer=m.group(0).isdigit(),
            )
        )
    return found


def _matches(f: Found, values: Iterable[float]) -> bool:
    return any(abs(f.value - v) <= f.tolerance + EPSILON for v in values)


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
