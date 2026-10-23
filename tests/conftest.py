import asyncio
from pathlib import Path

import pytest
from pydantic import BaseModel

from adapters.fake_llm import FakeLLMProvider
from adapters.memory_repository import MemoryRepository
from adapters.memory_session_store import MemorySessionStore
from core.agent import Agent
from core.errors import ToolExecutionError
from core.interfaces import LLMResponse, ToolCall
from core.tools import Tool, ToolRegistry
from domain.analytics import Analytics
from domain.config import load_config
from domain.live_status import LiveEvent, LiveStatus, LiveStatusUnavailable

DOMAIN = Path(__file__).resolve().parent.parent / "domain"
DATA = DOMAIN / "data"


def say(text: str) -> LLMResponse:
    return LLMResponse(text=text)


def call(name: str, call_id: str = "t1", **arguments) -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=arguments)


def use(*calls: ToolCall) -> LLMResponse:
    return LLMResponse(tool_calls=list(calls))


class AddArgs(BaseModel):
    a: int
    b: int


class SlowArgs(BaseModel):
    delay: float = 0.15


class NoArgs(BaseModel):
    pass


class Rig:
    """A fully wired agent with a scripted LLM and small generic test tools.

    Tools: add (works), slow (sleeps), boom (unexpected exception), refuse (expected error),
    flaky (fails on the first call only). `calls` counts how often each handler ran."""

    def __init__(self, script, **agent_kwargs) -> None:
        self.calls: dict[str, int] = {}
        self.llm = FakeLLMProvider(script)
        self.sessions = MemorySessionStore()
        self.tools = ToolRegistry(self._tools(), timeout_s=agent_kwargs.pop("tool_timeout_s", 1))
        kwargs = {"llm_timeout_s": 1, "retry_backoff_s": 0, **agent_kwargs}
        self.agent = Agent(self.llm, self.sessions, self.tools, "SYSTEM", **kwargs)

    def _count(self, name: str) -> int:
        self.calls[name] = self.calls.get(name, 0) + 1
        return self.calls[name]

    def _tools(self) -> list[Tool]:
        async def add(args: AddArgs) -> dict:
            self._count("add")
            return {"sum": args.a + args.b}

        async def slow(args: SlowArgs) -> dict:
            self._count("slow")
            await asyncio.sleep(args.delay)
            return {"slept": args.delay}

        async def boom(args: NoArgs) -> dict:
            self._count("boom")
            raise RuntimeError("secret internals")

        async def refuse(args: NoArgs) -> dict:
            self._count("refuse")
            raise ToolExecutionError("not_found", "No such airport.")

        async def flaky(args: NoArgs) -> dict:
            if self._count("flaky") == 1:
                raise ConnectionError("temporary")
            return {"ok": True}

        return [
            Tool("add", "Add two integers.", AddArgs, add),
            Tool("slow", "Sleep, then return.", SlowArgs, slow),
            Tool("boom", "Always fails unexpectedly.", NoArgs, boom),
            Tool("refuse", "Always fails with an expected error.", NoArgs, refuse),
            Tool("flaky", "Fails once, then works.", NoArgs, flaky),
        ]


@pytest.fixture
def rig():
    def make(script, **kwargs) -> Rig:
        return Rig(script, **kwargs)

    return make


class FakeLiveStatus:
    """Live status without the network: LAX has a ground delay, everything else is quiet."""

    def __init__(self, *, fail: bool = False) -> None:
        self._fail = fail

    async def get_status(self) -> LiveStatus:
        if self._fail:
            raise LiveStatusUnavailable("FAA feed unreachable")
        delay = LiveEvent(kind="Ground Delay Programs", details={"Reason": "rain", "Avg": "1 hour"})
        notice = LiveEvent(kind="Airport Closures", details={"Reason": "!BOS AD AP CLSD TO GA"})
        return LiveStatus(
            updated="Fri Oct 23 06:42:01 2026 GMT", events={"LAX": [delay], "BOS": [notice]}
        )


@pytest.fixture(scope="session")
def memory_repo():
    return MemoryRepository(DATA)


@pytest.fixture
def analytics(memory_repo):
    return Analytics(memory_repo, FakeLiveStatus(), load_config(DOMAIN / "config.yaml"))
