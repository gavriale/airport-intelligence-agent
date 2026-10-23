"""Live airport status (current delay programs and closures)."""

from typing import Protocol

from pydantic import BaseModel


class LiveStatusUnavailable(Exception):
    """The live source could not be reached or understood."""


class LiveEvent(BaseModel):
    kind: str  # e.g. "Ground Delay Programs", "Airport Closures"
    details: dict[str, str]


class LiveStatus(BaseModel):
    updated: str  # the source's own timestamp
    events: dict[str, list[LiveEvent]]  # IATA code -> active programs


class LiveStatusProvider(Protocol):
    async def get_status(self) -> LiveStatus: ...
