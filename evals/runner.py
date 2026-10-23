"""Runs domain/eval_cases.yaml against the live model: `python -m evals.runner`.

Deterministic checks first (tools, regexes, escalation flag, side effects), then one LLM-judge
groundedness check where a case asks for it. This is the only code that calls the live model.
"""

import asyncio
import json
import re
import statistics
import uuid
from collections import defaultdict
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from adapters.anthropic_llm import AnthropicLLM
from adapters.fake_repository import FailingRepository, FakeRepository
from app.container import DATA_DIR, DOMAIN_DIR, build_container
from app.settings import Settings
from core.agent import TurnResult
from core.interfaces import LLMProvider
from evals.judges import judge_groundedness

CONCURRENCY = 4
RESULTS_PATH = Path(__file__).resolve().parent / "latest_results.md"


class Expect(BaseModel):
    tools_called: list[str] = []
    tools_not_called: list[str] = []
    answer_matches: list[str] = []
    answer_not_matches: list[str] = []
    escalated: bool | None = None
    withdrawals_created: int | None = None
    judge_grounded: bool = False


class Case(BaseModel):
    id: str
    category: str
    turns: list[str]
    verified_as: str | None = None
    backend: str = "fake"
    expect: Expect = Field(default_factory=Expect)


class CaseResult(BaseModel):
    id: str
    category: str
    passed: bool
    failures: list[str]
    latencies_ms: list[float]


def load_cases(path: Path) -> list[Case]:
    return [Case(**raw) for raw in yaml.safe_load(path.read_text(encoding="utf-8"))]


def check_case(case: Case, results: list[TurnResult], withdrawals_created: int) -> list[str]:
    """Deterministic checks. Returns a list of failure descriptions (empty = pass)."""
    expect, failures = case.expect, []
    called = {t.name for r in results for t in r.tool_calls}
    answer = results[-1].reply

    failures += [f"expected tool {n} not called" for n in expect.tools_called if n not in called]
    failures += [f"tool {n} must not be called" for n in expect.tools_not_called if n in called]
    for pattern in expect.answer_matches:
        if not re.search(pattern, answer, re.IGNORECASE | re.MULTILINE):
            failures.append(f"answer missing /{pattern}/")
    for pattern in expect.answer_not_matches:
        if re.search(pattern, answer, re.IGNORECASE | re.MULTILINE):
            failures.append(f"answer must not match /{pattern}/")
    if expect.escalated is not None and results[-1].escalated != expect.escalated:
        failures.append(f"escalated was {results[-1].escalated}, expected {expect.escalated}")
    wanted = expect.withdrawals_created
    if wanted is not None and withdrawals_created != wanted:
        failures.append(f"{withdrawals_created} withdrawals created, expected {wanted}")
    return failures


async def run_case(case: Case, settings: Settings, llm: LLMProvider) -> CaseResult:
    repo_class = FailingRepository if case.backend == "failing" else FakeRepository
    repo = repo_class(DATA_DIR / "seed.json")
    baseline = len(repo.withdrawals)
    container = await build_container(settings, llm=llm, repository=repo)

    session_id = str(uuid.uuid4())
    if case.verified_as:
        session = await container.sessions.get_or_create(session_id)
        session.verified_customer_id = case.verified_as

    results = [await container.agent.run_turn(session_id, text) for text in case.turns]

    failures = check_case(case, results, len(repo.withdrawals) - baseline)
    if case.expect.judge_grounded:
        evidence = [t.result for r in results for t in r.tool_calls]
        verdict = await judge_groundedness(llm, evidence, results[-1].reply)
        if not verdict.grounded:
            failures.append(f"judge: not grounded ({verdict.reason})")
    return CaseResult(
        id=case.id,
        category=case.category,
        passed=not failures,
        failures=failures,
        latencies_ms=[r.latency_ms for r in results],
    )


def p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(0.95 * len(ordered)) - 1)]


def render(results: list[CaseResult], model: str) -> str:
    by_category: dict[str, list[CaseResult]] = defaultdict(list)
    for r in results:
        by_category[r.category].append(r)
    latencies = [ms for r in results for ms in r.latencies_ms]
    passed = sum(r.passed for r in results)

    lines = [
        f"Model: `{model}`. {len(results)} cases.",
        "",
        "| Category | Passed | Total | Rate |",
        "|---|---|---|---|",
    ]
    for category, rs in by_category.items():
        ok = sum(r.passed for r in rs)
        lines.append(f"| {category} | {ok} | {len(rs)} | {ok / len(rs):.0%} |")
    lines += [
        f"| **overall** | **{passed}** | **{len(results)}** | **{passed / len(results):.0%}** |",
        "",
        f"Turn latency: avg {statistics.mean(latencies):.0f} ms, p95 {p95(latencies):.0f} ms "
        f"({len(latencies)} turns).",
    ]
    failed = [r for r in results if not r.passed]
    if failed:
        lines += ["", "Failures:", ""]
        lines += [f"- `{r.id}`: {'; '.join(r.failures)}" for r in failed]
    return "\n".join(lines)


async def main() -> None:
    settings = Settings()
    if settings.llm_cache:
        print("WARNING: LLM_CACHE is set but ignored: evals always call the live model.\n")
    # Built directly (not via the container's default), so the dev cache can never apply.
    llm = AnthropicLLM(settings.anthropic_api_key.get_secret_value(), settings.model)
    cases = load_cases(DOMAIN_DIR / "eval_cases.yaml")
    gate = asyncio.Semaphore(CONCURRENCY)

    async def limited(case: Case) -> CaseResult:
        async with gate:
            return await run_case(case, settings, llm)

    results = await asyncio.gather(*(limited(c) for c in cases))
    report = render(list(results), settings.model)
    RESULTS_PATH.write_text(report + "\n", encoding="utf-8")
    print(report)
    print(json.dumps({"passed": all(r.passed for r in results)}))


if __name__ == "__main__":
    asyncio.run(main())
