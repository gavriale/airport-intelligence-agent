from core.errors import LLMError
from core.interfaces import LLMResponse, Message, ToolSpec


class FakeLLMProvider:
    """Scripted LLM for tests: each call pops the next item; an Exception item is raised."""

    def __init__(self, script: list[LLMResponse | Exception]) -> None:
        self._script = list(script)
        self.calls: list[tuple[str, list[Message]]] = []

    async def complete(
        self, system: str, messages: list[Message], tools: list[ToolSpec]
    ) -> LLMResponse:
        self.calls.append((system, list(messages)))
        if not self._script:
            raise LLMError("FakeLLMProvider script exhausted")
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
