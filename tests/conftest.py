from pathlib import Path

import pytest
import yaml

from adapters.bm25_index import BM25Index
from adapters.fake_llm import FakeLLMProvider
from adapters.fake_repository import FakeRepository
from adapters.memory_session_store import MemorySessionStore
from core.agent import Agent
from core.guardrails import GuardrailConfig, Guardrails
from core.interfaces import LLMResponse, ToolCall
from core.tools import ToolRegistry
from domain.tools import build_tools

DOMAIN = Path(__file__).resolve().parent.parent / "domain"


def say(text: str) -> LLMResponse:
    return LLMResponse(text=text)


def call(name: str, call_id: str = "t1", **arguments) -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=arguments)


def use(*calls: ToolCall) -> LLMResponse:
    return LLMResponse(tool_calls=list(calls))


class Rig:
    """A fully wired agent with a scripted LLM and in-memory data."""

    def __init__(self, script, repo=None, **agent_kwargs) -> None:
        config = yaml.safe_load((DOMAIN / "config.yaml").read_text(encoding="utf-8"))
        self.guardrails = Guardrails(GuardrailConfig(**config["guardrails"]))
        self.repo = repo or FakeRepository(DOMAIN / "data" / "seed.json")
        self.llm = FakeLLMProvider(script)
        self.sessions = MemorySessionStore()
        self.tools = ToolRegistry(
            build_tools(self.repo, BM25Index(DOMAIN / "knowledge"), self.guardrails),
            timeout_s=agent_kwargs.pop("tool_timeout_s", 1),
        )
        kwargs = {"llm_timeout_s": 1, "retry_backoff_s": 0, **agent_kwargs}
        self.agent = Agent(self.llm, self.sessions, self.tools, self.guardrails, "SYSTEM", **kwargs)

    async def verify(self, customer_id: str = "C001") -> None:
        session = await self.sessions.get_or_create("s1")
        session.verified_customer_id = customer_id


@pytest.fixture
def rig():
    def make(script, **kwargs) -> Rig:
        return Rig(script, **kwargs)

    return make
