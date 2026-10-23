"""Development-only record/replay cache around any LLMProvider. Never use in evals or production.

The key covers everything that can change the model's answer (model, system prompt, full
message history including tool results, tool schemas), so editing the prompt or a tool
invalidates old entries automatically.
"""

import hashlib
import json
import os
from pathlib import Path

from core.interfaces import LLMProvider, LLMResponse, Message, ToolSpec
from core.logging import log_event


class CachingLLMProvider:
    def __init__(self, inner: LLMProvider, cache_dir: Path, model: str) -> None:
        self._inner = inner
        self._dir = cache_dir
        self._model = model
        self._dir.mkdir(parents=True, exist_ok=True)

    async def complete(
        self, system: str, messages: list[Message], tools: list[ToolSpec]
    ) -> LLMResponse:
        key = self._key(system, messages, tools)
        path = self._dir / f"{key}.json"
        if path.exists():
            log_event("llm_cache_hit", key=key[:12])
            stored = LLMResponse.model_validate_json(path.read_text(encoding="utf-8"))
            # Nothing was spent on a replay, so don't report the original token counts.
            return stored.model_copy(update={"input_tokens": 0, "output_tokens": 0})

        log_event("llm_cache_miss", key=key[:12])
        response = await self._inner.complete(system, messages, tools)
        self._store(path, response)
        return response

    def _key(self, system: str, messages: list[Message], tools: list[ToolSpec]) -> str:
        payload = {
            "model": self._model,
            "system": system,
            "messages": [m.model_dump(mode="json") for m in messages],
            "tools": [t.model_dump(mode="json") for t in tools],
        }
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _store(path: Path, response: LLMResponse) -> None:
        """Write via a temp file so a crash never leaves a half-written entry."""
        tmp = path.with_suffix(".tmp")
        tmp.write_text(response.model_dump_json(), encoding="utf-8")
        os.replace(tmp, path)
