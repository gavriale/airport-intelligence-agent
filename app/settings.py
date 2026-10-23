from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Blank is allowed: /chat then answers 503 and /ranking still works.
    anthropic_api_key: SecretStr = SecretStr("")
    model: str = "claude-sonnet-5-5"
    llm_timeout_s: float = 30
    log_format: Literal["console", "json"] = "json"
    # Development only: replay identical LLM calls from .llm_cache/ instead of paying again.
    llm_cache: bool = False
    tool_timeout_s: float = 10
    max_iterations: int = 6
    # "memory" serves the committed snapshot files from memory (no Docker needed).
    data_backend: Literal["postgres", "memory"] = "postgres"
    database_url: str = "postgresql://agent:agent@localhost:5432/agent"
