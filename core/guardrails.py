"""Policy checks that run in code, not in the prompt.

The prompt asks the model to behave; these checks are the backstop for when it doesn't.
"""

import re

from pydantic import BaseModel

from core.errors import PolicyViolation


class GuardrailConfig(BaseModel):
    max_failed_verifications: int = 2
    advice_output_patterns: list[str] = []
    advice_refusal_message: str
    escalated_reply: str


class Guardrails:
    def __init__(self, config: GuardrailConfig) -> None:
        self.config = config
        self._advice = [re.compile(p, re.IGNORECASE) for p in config.advice_output_patterns]

    def check_output(self, text: str) -> None:
        """Coarse backstop: block replies that read as a personal buy/sell recommendation."""
        for pattern in self._advice:
            if pattern.search(text):
                raise PolicyViolation(f"Reply matched advice pattern {pattern.pattern!r}")

    def verification_limit_reached(self, failed_verifications: int) -> bool:
        return failed_verifications >= self.config.max_failed_verifications
