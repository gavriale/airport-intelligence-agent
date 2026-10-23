"""Composition root: the only place that knows which adapter implements which port."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from adapters.anthropic_llm import AnthropicLLM
from adapters.llm_cache import CachingLLMProvider
from adapters.memory_session_store import MemorySessionStore
from adapters.postgres_repository import PostgresRepository
from app.settings import Settings
from core.agent import Agent
from core.interfaces import LLMProvider, SessionStore
from core.tools import ToolRegistry
from domain.repository import AirportRepository
from domain.tools import build_tools

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


async def build_container(
    settings: Settings,
    *,
    llm: LLMProvider | None = None,
    repository: AirportRepository | None = None,
) -> Container:
    """`llm` and `repository` can be overridden (tests, evals); defaults come from settings."""
    close = _noop
    if repository is None:
        postgres = await PostgresRepository.connect(settings.database_url)
        await postgres.load_snapshot(DATA_DIR / "schema.sql", DATA_DIR)
        repository, close = postgres, postgres.close
    if llm is None:
        llm = AnthropicLLM(settings.anthropic_api_key.get_secret_value(), settings.model)
        if settings.llm_cache:
            llm = CachingLLMProvider(llm, LLM_CACHE_DIR, settings.model)

    tools = ToolRegistry(build_tools(repository), timeout_s=settings.tool_timeout_s)
    sessions = MemorySessionStore()
    agent = Agent(
        llm,
        sessions,
        tools,
        (DOMAIN_DIR / "system_prompt.md").read_text(encoding="utf-8"),
        llm_timeout_s=settings.llm_timeout_s,
        max_iterations=settings.max_iterations,
    )
    return Container(agent=agent, sessions=sessions, close=close)
