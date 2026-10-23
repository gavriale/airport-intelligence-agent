"""Typed domain errors. Each maps to a structured error result the model can read."""


class LLMError(Exception):
    """Any provider failure (network, rate limit, 5xx). Adapters wrap SDK errors in this."""


class IdentityNotVerified(Exception):
    """A tool that needs a verified customer was called before verification."""


class ToolExecutionError(Exception):
    """An expected tool failure (bad input, business rule). `code` is shown to the model."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class PolicyViolation(Exception):
    """The agent's draft reply breaks a policy (e.g. personalised investment advice)."""
