"""Typed domain errors. Each maps to a structured error result the model can read."""


class LLMError(Exception):
    """A provider failure worth retrying (network, timeout, rate limit, 5xx). Adapters wrap SDK
    errors in this."""


class LLMFatalError(LLMError):
    """A provider failure that a retry cannot fix (rejected key, unknown model, bad request).
    `user_message` is what the user is told; the exception text keeps the real error for logs."""

    def __init__(self, user_message: str, detail: str) -> None:
        super().__init__(detail)
        self.user_message = user_message


class ToolExecutionError(Exception):
    """An expected tool failure (bad input, unknown airport). `code` is shown to the model."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
