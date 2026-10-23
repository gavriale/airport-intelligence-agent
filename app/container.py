"""Composition root: the only place that knows which adapter implements which port."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from adapters.anthropic_llm import AnthropicLLM
from adapters.faa_status import FaaStatusProvider
from adapters.llm_cache import CachingLLMProvider
from adapters.memory_repository import MemoryRepository
from adapters.memory_session_store import MemorySessionStore
from adapters.postgres_repository import PostgresRepository
from app.settings import Settings
from core.agent import Agent
from core.interfaces import LLMProvider, SessionStore
from core.tools import ToolRegistry
from domain.analytics import Analytics
from domain.config import load_config
from domain.live_status import LiveStatusProvider
from domain.repository import AirportRepository
from domain.tools import build_tools

DOMAIN_DIR = Path(__file__).resolve().parent.parent / "domain"
DATA_DIR = DOMAIN_DIR / "data"
LLM_CACHE_DIR = DOMAIN_DIR.parent / ".llm_cache"


@dataclass
class Container:
    agent: Agent | None  # None when no API key is set; GET /ranking still works
    sessions: SessionStore
    analytics: Analytics  # also serves GET /ranking, which needs no model
    close: Callable[[], Awaitable[None]]


async def _noop() -> None:
    return None


async def _build_repository(settings: Settings) -> tuple[AirportRepository, Callable]:
    if settings.data_backend == "memory":
        return MemoryRepository(DATA_DIR), _noop
    postgres = await PostgresRepository.connect(settings.database_url)
    await postgres.load_snapshot(DATA_DIR / "schema.sql", DATA_DIR)
    return postgres, postgres.close


async def build_container(
    settings: Settings,
    *,
    llm: LLMProvider | None = None,
    repository: AirportRepository | None = None,
    live_status: LiveStatusProvider | None = None,
) -> Container:
    """`llm`, `repository` and `live_status` can be overridden (tests, evals)."""
    close = _noop
    if repository is None:
        repository, close = await _build_repository(settings)
    api_key = settings.anthropic_api_key.get_secret_value().strip()
    if llm is None and api_key:
        llm = AnthropicLLM(api_key, settings.model)
        if settings.llm_cache:
            llm = CachingLLMProvider(llm, LLM_CACHE_DIR, settings.model)

    analytics = Analytics(
        repository, live_status or FaaStatusProvider(), load_config(DOMAIN_DIR / "config.yaml")
    )
    tools = ToolRegistry(build_tools(analytics), timeout_s=settings.tool_timeout_s)
    sessions = MemorySessionStore()
    agent = (
        Agent(
            llm,
            sessions,
            tools,
            (DOMAIN_DIR / "system_prompt.md").read_text(encoding="utf-8"),
            llm_timeout_s=settings.llm_timeout_s,
            max_iterations=settings.max_iterations,
        )
        if llm
        else None
    )
    return Container(agent=agent, sessions=sessions, analytics=analytics, close=close)
