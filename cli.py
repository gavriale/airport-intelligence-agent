"""Interactive chat for demos: `python cli.py`. Type 'exit' to quit."""

import asyncio
import uuid

from app.container import build_container
from app.settings import Settings


async def main() -> None:
    container = await build_container(Settings())
    session_id = str(uuid.uuid4())
    try:
        while True:
            user_text = (await asyncio.to_thread(input, "you> ")).strip()
            if user_text.lower() in {"exit", "quit"}:
                break
            if not user_text:
                continue
            result = await container.agent.run_turn(session_id, user_text)
            tools = ", ".join(t.name for t in result.tool_calls) or "-"
            print(f"agent> {result.reply}")
            flags = f"tools: {tools}"
            print(f"       [{result.latency_ms:.0f} ms | {flags}]\n")
    finally:
        await container.close()


if __name__ == "__main__":
    asyncio.run(main())
