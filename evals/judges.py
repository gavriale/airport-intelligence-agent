"""LLM-as-judge for groundedness. The rubric is also recorded in docs/EVALS.md."""

import json

from pydantic import BaseModel

from core.interfaces import LLMProvider, Message

JUDGE_SYSTEM = """You are a strict evaluator of an analyst assistant.
You get EVIDENCE and the assistant's ANSWER. The evidence lists every tool call the assistant made,
with its arguments and its result (an error counts as a result). It does not include the
assistant's own instructions.

Rubric. The answer is GROUNDED only if all of these hold:
1. Every number, date, name, status and policy statement in the answer appears in the evidence.
   What the assistant says about its own tool calls (which tool, which arguments, that it failed)
   is supported by the evidence when it matches the listed calls.
2. The answer does not contradict the evidence.
3. If the evidence is missing or contains an error, the answer says it cannot provide the data
   and does not state or guess any specific figure.
General politeness, offers to help, and refusals are always allowed.

Reply with JSON only: {"grounded": true|false, "reason": "<one short sentence>"}"""


class JudgeVerdict(BaseModel):
    grounded: bool
    reason: str


async def judge_groundedness(llm: LLMProvider, evidence: list[str], answer: str) -> JudgeVerdict:
    evidence_text = "\n".join(evidence) or "(the assistant made no tool calls)"
    prompt = f"EVIDENCE:\n{evidence_text}\n\nANSWER:\n{answer}"
    response = await llm.complete(JUDGE_SYSTEM, [Message(role="user", content=prompt)], [])
    return _parse(response.text)


def _parse(text: str) -> JudgeVerdict:
    try:
        return JudgeVerdict(**json.loads(text[text.index("{") : text.rindex("}") + 1]))
    except ValueError:  # includes JSON and validation errors; an unreadable verdict fails closed
        return JudgeVerdict(grounded=False, reason=f"Unparseable judge output: {text[:80]!r}")
