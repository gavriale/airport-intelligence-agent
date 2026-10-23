"""LLM-as-judge for groundedness. The rubric is also recorded in docs/EVALS.md."""

import asyncio
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


class JudgeOutcome(BaseModel):
    """The majority verdict of several independent judge calls."""

    grounded: bool
    verdicts: list[JudgeVerdict]

    @property
    def unanimous(self) -> bool:
        return len({v.grounded for v in self.verdicts}) == 1

    def disagreement(self) -> str | None:
        """A one-line description when the judge calls did not agree, else None."""
        if self.unanimous:
            return None
        yes = sum(v.grounded for v in self.verdicts)
        dissent = [v.reason for v in self.verdicts if v.grounded != self.grounded]
        side = "grounded" if self.grounded else "not grounded"
        return (
            f"judge disagreed: {yes} of {len(self.verdicts)} said grounded, majority {side}; "
            f"dissent: {dissent[0]}"
        )


async def judge_majority(
    llm: LLMProvider, evidence: list[str], answer: str, votes: int = 3
) -> JudgeOutcome:
    """Ask the judge `votes` times (an odd number) and take the majority. A single call is noisy:
    the same sentence can pass in one call and fail in the next."""
    verdicts = list(
        await asyncio.gather(*(judge_groundedness(llm, evidence, answer) for _ in range(votes)))
    )
    return JudgeOutcome(grounded=sum(v.grounded for v in verdicts) * 2 > votes, verdicts=verdicts)


def _parse(text: str) -> JudgeVerdict:
    try:
        return JudgeVerdict(**json.loads(text[text.index("{") : text.rindex("}") + 1]))
    except ValueError:  # includes JSON and validation errors; an unreadable verdict fails closed
        return JudgeVerdict(grounded=False, reason=f"Unparseable judge output: {text[:80]!r}")
