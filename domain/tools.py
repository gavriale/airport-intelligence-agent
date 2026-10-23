"""Airport tools. The tools themselves arrive in the scoring and tools stage."""

from core.tools import Tool
from domain.repository import AirportRepository


def build_tools(repository: AirportRepository) -> list[Tool]:
    return []
