"""Composition root: the only place that knows which adapter implements which port."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

import yaml

from adapters.anthropic_llm import AnthropicLLM
from adapters.bm25_index import BM25Index
from adapters.fake_repository import FakeRepository
from adapters.llm_cache import CachingLLMProvider
from adapters.memory_session_store import MemorySessionStore
from adapters.postgres_repository import PostgresRepository
from app.settings import Settings
from core.agent import Agent
from core.guardrails import GuardrailConfig, Guardrails
from core.interfaces import LLMProvider, SessionStore
from core.tools import ToolRegistry
from domain.tools import AccountRepository, build_tools

DOMAIN_DIR = Path(__file__).resolve().parent.parent / "domain"
DATA_DIR = DOMAIN_DIR / "data"
LLM_CACHE_DIR = DOMAIN_DIR.parent / ".llm_cache"


@dataclass
class Container:
    agent: Agent
    sessions: SessionStore
    close: Callable[[], Awaitable[None]]


async def _noop() -> None:
    return None


async def build_repository(
    settings: Settings,
) -> tuple[AccountRepository, Callable[[], Awaitable[None]]]:
    if settings.data_backend == "fake":
        return FakeRepository(DATA_DIR / "seed.json"), _noop
    repo = await PostgresRepository.connect(settings.database_url)
    await repo.init_schema_and_seed(DATA_DIR / "schema.sql", DATA_DIR / "seed.json")
    return repo, repo.close


async def build_container(
    settings: Settings,
    *,
    llm: LLMProvider | None = None,
    repository: AccountRepository | None = None,
) -> Container:
    """`llm` and `repository` can be overridden (tests, evals); defaults come from settings."""
    close = _noop
    if repository is None:
        repository, close = await build_repository(settings)
    if llm is None:
        llm = AnthropicLLM(settings.anthropic_api_key.get_secret_value(), settings.model)
        if settings.llm_cache:
            llm = CachingLLMProvider(llm, LLM_CACHE_DIR, settings.model)

    config = yaml.safe_load((DOMAIN_DIR / "config.yaml").read_text(encoding="utf-8"))
    guardrails = Guardrails(GuardrailConfig(**config["guardrails"]))
    tools = ToolRegistry(
        build_tools(repository, BM25Index(DOMAIN_DIR / "knowledge"), guardrails),
        timeout_s=settings.tool_timeout_s,
    )
    sessions = MemorySessionStore()
    agent = Agent(
        llm,
        sessions,
        tools,
        guardrails,
        (DOMAIN_DIR / "system_prompt.md").read_text(encoding="utf-8"),
        llm_timeout_s=settings.llm_timeout_s,
        max_iterations=settings.max_iterations,
    )
    return Container(agent=agent, sessions=sessions, close=close)
