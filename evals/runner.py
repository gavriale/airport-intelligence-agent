"""Runs domain/eval_cases.yaml against the live model: `python -m evals.runner`.

Per case: deterministic checks first (tools and arguments, required and forbidden text, answer
length, the ranking order, and a number audit), then an LLM-judge groundedness check where a case
asks for it. Safety cases run three times and must pass every time. This is the only code besides
the app that calls the live model, and it never uses the development cache.
"""

import asyncio
import json
import re
import statistics
import time
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Literal

import httpx
import yaml
from pydantic import BaseModel, Field

from adapters.anthropic_llm import AnthropicLLM
from adapters.memory_repository import MemoryRepository
from api.main import create_app
from app.container import DATA_DIR, DOMAIN_DIR, build_container
from app.settings import Settings
from core.agent import TurnResult
from core.interfaces import LLMProvider, LLMResponse, Message, ToolSpec
from domain.repository import AirportRepository
from evals.fakes import FailingRepository, ScriptedLiveStatus
from evals.judges import judge_majority
from evals.number_audit import audit

CONCURRENCY = 4
SAFETY_REPEATS = 3
JUDGE_VOTES = 3  # judge calls per judged answer; the majority decides
RANKING_TOP_N = 5
RESULTS_PATH = Path(__file__).resolve().parent / "latest_results.md"
TRANSCRIPTS_PATH = Path(__file__).resolve().parent / "latest_transcripts.md"

# USD per million tokens: (input, output). Cache reads cost 0.10x and cache writes 1.25x of input.
PRICES = {"claude-sonnet-5-5": (2.0, 10.0)}  # taken from the published price list; check it
CACHE_READ_FACTOR = 0.10
CACHE_WRITE_FACTOR = 1.25

# Next-step suggestions may describe the kind of data needed but may not name specific outside
# datasets, reports or companies. A heuristic list of the names the model used in the first run
# and the obvious neighbours; our own sources (BTS T-100, OurAirports, FAA) are fine to name.
EXTERNAL_SOURCES = [
    r"\b(DB1B|OAG|Cirium|FlightAware|FlightRadar24|OpenSky|Massport|Form 41)\b",
    r"\b(BTS|Airline|DOT) On-Time (Performance|Reporting)",  # the named dataset, not the idea
    r"\bsegment (file|data)\b",
]


class ToolArgCheck(BaseModel):
    """Some call to `tool` must satisfy exactly one of these conditions on argument `arg`."""

    tool: str
    arg: str
    equals: str | None = None
    equals_set: list[str] | None = None
    keys_subset_of: list[str] | None = None  # the argument is a mapping with only these keys


class RankingOrder(BaseModel):
    """The answer must list the top airports in the order of a reference ranking."""

    source: Literal["endpoint", "tool"]
    region: str | None = None  # for source "endpoint": GET /ranking?region=...


class Expect(BaseModel):
    tools_called: list[str] = []
    tools_not_called: list[str] = []
    tool_args: list[ToolArgCheck] = []
    answer_matches: list[str] = []
    answer_not_matches: list[str] = []
    max_words: int | None = None  # a failure: used by the style cases
    warn_max_words: int | None = None  # only a warning: length is style, not correctness
    ranking_order: RankingOrder | None = None
    no_numbers: bool = False  # the answer may contain no data numbers at all
    no_external_sources: bool = False  # the answer may not name datasets or sources we do not use
    judge_grounded: bool = False


class Case(BaseModel):
    id: str
    category: str
    turns: list[str]
    safety: bool = False  # run three times, must pass every time
    backend: Literal["normal", "failing"] = "normal"
    expect: Expect = Field(default_factory=Expect)


class Reference(BaseModel):
    """What the checks compare against, prepared once per run."""

    ranking: list[dict] | None = None  # expected top airports, best first
    allowed_texts: list[str] = []  # the user's messages and the config text


class RunResult(BaseModel):
    case_id: str
    category: str
    run: int
    passed: bool
    failures: list[str]
    warnings: list[str] = []
    judge_notes: list[str] = []  # when the three judge calls did not agree
    latencies_ms: list[float]
    transcript: str


def load_cases(path: Path) -> list[Case]:
    return [Case(**raw) for raw in yaml.safe_load(path.read_text(encoding="utf-8")) or []]


# ---------- deterministic checks ----------


def _tool_calls(results: list[TurnResult]):
    return [t for r in results for t in r.tool_calls]


def _arg_satisfies(check: ToolArgCheck, value) -> bool:
    if check.equals is not None:
        return value == check.equals
    if check.equals_set is not None:
        return isinstance(value, list) and {str(v).upper() for v in value} == set(check.equals_set)
    if check.keys_subset_of is not None:
        return isinstance(value, dict) and bool(value) and set(value) <= set(check.keys_subset_of)
    return False


def count_words(text: str) -> int:
    """Words as a reader counts them: table pipes and rules (| and ---) are not words."""
    return sum(1 for token in text.split() if re.search(r"\w", token))


def length_warnings(case: Case, results: list[TurnResult]) -> list[str]:
    limit = case.expect.warn_max_words
    words = count_words(results[-1].reply)
    return [f"answer has {words} words, aim for {limit}"] if limit and words > limit else []


def evidence_for(results: list[TurnResult]) -> list[str]:
    """What the judge may rely on: each tool call with its arguments and its result or error.
    The system prompt is deliberately not included."""
    return [
        f"{t.name}({json.dumps(t.arguments)}) -> {'ERROR ' if t.is_error else ''}{t.result}"
        for r in results
        for t in r.tool_calls
    ]


def _first_position(answer: str, tokens: list[str]) -> int | None:
    hits = [m.start() for t in tokens if (m := re.search(rf"\b{re.escape(t)}\b", answer, re.I))]
    return min(hits) if hits else None


def check_ranking_order(answer: str, expected: list[dict]) -> list[str]:
    """Each airport is found by its IATA code or city; they must appear in the expected order."""
    positions = [
        (a["iata"], _first_position(answer, [t for t in (a["iata"], a.get("city")) if t]))
        for a in expected
    ]
    missing = [iata for iata, pos in positions if pos is None]
    if missing:
        return [f"ranking: airports missing from the answer: {missing}"]
    order = [iata for iata, _ in sorted(positions, key=lambda p: p[1])]
    wanted = [a["iata"] for a in expected]
    return [] if order == wanted else [f"ranking order is {order}, expected {wanted}"]


def check_case(
    case: Case, results: list[TurnResult], reference: Reference | None = None
) -> list[str]:
    """Deterministic checks. Returns a list of failure descriptions (empty = pass)."""
    reference = reference or Reference()
    expect, failures = case.expect, []
    calls = _tool_calls(results)
    called = {t.name for t in calls}
    answer = results[-1].reply

    failures += [f"expected tool {n} not called" for n in expect.tools_called if n not in called]
    failures += [f"tool {n} must not be called" for n in expect.tools_not_called if n in called]
    for check in expect.tool_args:
        matching = any(
            t.name == check.tool and _arg_satisfies(check, t.arguments.get(check.arg))
            for t in calls
        )
        if not matching:
            failures.append(f"no {check.tool} call with a matching '{check.arg}' argument")
    for pattern in expect.answer_matches:
        if not re.search(pattern, answer, re.IGNORECASE | re.MULTILINE):
            failures.append(f"answer missing /{pattern}/")
    forbidden = [
        *expect.answer_not_matches,
        *(EXTERNAL_SOURCES if expect.no_external_sources else []),
    ]
    for pattern in forbidden:
        if re.search(pattern, answer, re.IGNORECASE | re.MULTILINE):
            failures.append(f"answer must not match /{pattern}/")
    if expect.max_words is not None and count_words(answer) > expect.max_words:
        failures.append(f"answer has {count_words(answer)} words, limit {expect.max_words}")
    if expect.ranking_order is not None:
        if reference.ranking:
            failures += check_ranking_order(answer, reference.ranking)
        else:
            failures.append("ranking: no reference ranking available to compare with")

    tool_texts = [t.result for t in calls] + [json.dumps(t.arguments) for t in calls]
    failures += audit(
        answer,
        [] if expect.no_numbers else tool_texts,
        [] if expect.no_numbers else reference.allowed_texts,
        strict=expect.no_numbers,
    )
    return failures


# ---------- running ----------


class UsageMeter:
    """Wraps the model and adds up the tokens of every call, the agent's and the judge's."""

    def __init__(self, inner: LLMProvider) -> None:
        self._inner = inner
        self.calls = self.input = self.output = self.cache_read = self.cache_write = 0

    async def complete(
        self, system: str, messages: list[Message], tools: list[ToolSpec]
    ) -> LLMResponse:
        response = await self._inner.complete(system, messages, tools)
        self.calls += 1
        self.input += response.input_tokens
        self.output += response.output_tokens
        self.cache_read += response.cache_read_tokens
        self.cache_write += response.cache_write_tokens
        return response

    def cost_usd(self, model: str) -> float | None:
        if model not in PRICES:
            return None
        price_in, price_out = PRICES[model]
        uncached = self.input - self.cache_read - self.cache_write
        return (
            uncached * price_in
            + self.cache_write * price_in * CACHE_WRITE_FACTOR
            + self.cache_read * price_in * CACHE_READ_FACTOR
            + self.output * price_out
        ) / 1e6


async def reference_for(
    case: Case, results: list[TurnResult], container, config_text: str
) -> Reference:
    order = case.expect.ranking_order
    ranking = None
    if order and order.source == "endpoint":
        transport = httpx.ASGITransport(app=create_app(container))
        async with httpx.AsyncClient(transport=transport, base_url="http://eval") as client:
            params = {"region": order.region, "top_n": RANKING_TOP_N}
            response = await client.get("/ranking", params=params)
        ranking = response.json()["ranking"]
    elif order and order.source == "tool":
        ranked = [t for t in _tool_calls(results) if t.name == "rank_airports" and not t.is_error]
        ranking = json.loads(ranked[-1].result)["ranking"][:RANKING_TOP_N] if ranked else None
    return Reference(ranking=ranking, allowed_texts=[*case.turns, config_text])


def _transcript(case: Case, run: int, results: list[TurnResult], failures: list[str]) -> str:
    lines = [f"## {case.id} (run {run}) {'PASS' if not failures else 'FAIL'}", ""]
    for question, result in zip(case.turns, results, strict=True):
        lines += [f"**User:** {question}", ""]
        for t in result.tool_calls:
            status = "error" if t.is_error else "ok"
            lines.append(f"- tool `{t.name}` {json.dumps(t.arguments)} -> {status}")
        lines += ["", result.reply, ""]
    lines += [f"Failures: {failures}" if failures else "No failures.", ""]
    return "\n".join(lines)


async def run_case_once(
    case: Case, run: int, settings: Settings, llm: LLMProvider, repository: AirportRepository
) -> RunResult:
    backend = FailingRepository() if case.backend == "failing" else repository
    container = await build_container(
        settings, llm=llm, repository=backend, live_status=ScriptedLiveStatus()
    )
    session_id = str(uuid.uuid4())
    results = [await container.agent.run_turn(session_id, text) for text in case.turns]

    config_text = (DOMAIN_DIR / "config.yaml").read_text(encoding="utf-8")
    reference = await reference_for(case, results, container, config_text)
    failures = check_case(case, results, reference)
    notes: list[str] = []
    if case.expect.judge_grounded:
        outcome = await judge_majority(llm, evidence_for(results), results[-1].reply, JUDGE_VOTES)
        if not outcome.grounded:
            reason = next(v.reason for v in outcome.verdicts if not v.grounded)
            failures.append(f"judge (majority): not grounded ({reason})")
        if note := outcome.disagreement():
            notes.append(note)
    return RunResult(
        case_id=case.id,
        category=case.category,
        run=run,
        passed=not failures,
        failures=failures,
        warnings=length_warnings(case, results),
        judge_notes=notes,
        latencies_ms=[r.latency_ms for r in results],
        transcript=_transcript(case, run, results, failures),
    )


# ---------- report ----------


def p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(0.95 * len(ordered)) - 1)]


def render(
    cases: list[Case],
    runs: list[RunResult],
    *,
    model: str,
    seconds: float,
    meter: UsageMeter | None = None,
) -> str:
    by_case: dict[str, list[RunResult]] = defaultdict(list)
    for r in runs:
        by_case[r.case_id].append(r)
    passed_case = {c.id: all(r.passed for r in by_case[c.id]) for c in cases}

    by_category: dict[str, list[Case]] = defaultdict(list)
    for c in cases:
        by_category[c.category].append(c)
    latencies = [ms for r in runs for ms in r.latencies_ms]
    total_passed = sum(passed_case.values())

    lines = [
        f"Model: `{model}`. {len(cases)} cases, {len(runs)} conversations.",
        "",
        "| Category | Passed | Total | Rate |",
        "|---|---|---|---|",
    ]
    for category, group in by_category.items():
        ok = sum(passed_case[c.id] for c in group)
        lines.append(f"| {category} | {ok} | {len(group)} | {ok / len(group):.0%} |")
    overall = f"{total_passed / len(cases):.0%}"
    lines += [
        f"| **overall** | **{total_passed}** | **{len(cases)}** | **{overall}** |",
        "",
        "| Case | Category | Result |",
        "|---|---|---|",
    ]
    for c in cases:
        wins = sum(r.passed for r in by_case[c.id])
        mark = "pass" if passed_case[c.id] else "FAIL"
        lines.append(f"| {c.id} | {c.category} | {mark} ({wins}/{len(by_case[c.id])}) |")
    lines += [
        "",
        f"Turn latency: avg {statistics.mean(latencies):.0f} ms, p95 {p95(latencies):.0f} ms "
        f"({len(latencies)} turns). Run time: {seconds:.0f} s.",
    ]
    if meter is not None:
        cost = meter.cost_usd(model)
        cost_text = f"${cost:.2f}" if cost is not None else "not computed (no price for this model)"
        lines.append(
            f"Tokens: {meter.input:,} in ({meter.cache_read:,} read from cache, "
            f"{meter.cache_write:,} written to cache), {meter.output:,} out, {meter.calls} model "
            f"calls (agent and judge). Estimated cost: {cost_text}."
        )
    failed = [r for r in runs if not r.passed]
    if failed:
        lines += ["", "Failures:", ""]
        for r in failed:
            lines.append(f"- `{r.case_id}` run {r.run}:")
            lines += [f"  - {f}" for f in r.failures]
    disagreed = [r for r in runs if r.judge_notes]
    judged_ids = {c.id for c in cases if c.expect.judge_grounded}
    judged = [r for r in runs if r.case_id in judged_ids]
    lines += [
        "",
        f"Judge: {JUDGE_VOTES} calls per judged answer, the majority decides. "
        f"The calls disagreed on {len(disagreed)} of {len(judged)} judged answers.",
    ]
    if disagreed:
        lines += [""]
        lines += [f"- `{r.case_id}` run {r.run}: {'; '.join(r.judge_notes)}" for r in disagreed]
    warned = [r for r in runs if r.warnings]
    if warned:
        lines += ["", "Warnings (style, not counted as failures):", ""]
        lines += [f"- `{r.case_id}` run {r.run}: {'; '.join(r.warnings)}" for r in warned]
    return "\n".join(lines)


async def main() -> None:
    settings = Settings()
    if settings.llm_cache:
        print("WARNING: LLM_CACHE is set but ignored: evals always call the live model.\n")
    cases = load_cases(DOMAIN_DIR / "eval_cases.yaml")
    if not cases:
        print("No eval cases yet (domain/eval_cases.yaml is empty).")
        return

    # Built directly (not via the container's default), so the dev cache can never apply.
    meter = UsageMeter(AnthropicLLM(settings.anthropic_api_key.get_secret_value(), settings.model))
    repository = MemoryRepository(DATA_DIR)
    gate = asyncio.Semaphore(CONCURRENCY)

    async def limited(case: Case, run: int) -> RunResult:
        async with gate:
            return await run_case_once(case, run, settings, meter, repository)

    started = time.perf_counter()
    jobs = [
        limited(case, run)
        for case in cases
        for run in range(1, (SAFETY_REPEATS if case.safety else 1) + 1)
    ]
    runs = list(await asyncio.gather(*jobs))
    report = render(
        cases, runs, model=settings.model, seconds=time.perf_counter() - started, meter=meter
    )
    RESULTS_PATH.write_text(report + "\n", encoding="utf-8")
    TRANSCRIPTS_PATH.write_text(
        "# Eval transcripts (latest run)\n\n" + "\n".join(r.transcript for r in runs),
        encoding="utf-8",
    )
    print(report)
    print(json.dumps({"passed": all(r.passed for r in runs)}))


if __name__ == "__main__":
    asyncio.run(main())
