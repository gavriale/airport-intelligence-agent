"""Finding airports from the names people use. Pure function over airport records."""

import re
from collections.abc import Mapping, Sequence

from domain.repository import Airport

TYPE_RANK = {"large_airport": 0, "medium_airport": 1, "small_airport": 2}
NOISE_WORDS = {"airport", "international", "intl", "regional", "field"}


def _normalize(text: str) -> str:
    return " ".join(w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in NOISE_WORDS)


def _match(airport: Airport, query: str, tokens: list[str], aliases: Mapping[str, list[str]]):
    """Returns (score, reason) or None. Higher scores are better matches."""
    code = query.upper()
    if airport.iata == code or airport.ident == code:
        return 100, "airport code"
    if airport.iata in aliases.get(query, []):
        return 95 - aliases[query].index(airport.iata), "common name"
    city = _normalize(airport.city or "")
    name = _normalize(airport.name)
    if city == query:
        return 80, "city"
    if city.startswith(query):
        return 70, "city"
    if query in name:
        return 60, "airport name"
    if tokens and all(t in f"{city} {name}" for t in tokens):
        return 40, "airport name or city"
    return None


def search_airports(
    airports: Sequence[Airport],
    query: str,
    aliases: Mapping[str, list[str]],
    limit: int = 5,
) -> list[tuple[Airport, str]]:
    """Best matches first. Ties favour airports with traffic data, then bigger airport types."""
    normalized = _normalize(query)
    if not normalized:
        return []
    tokens = normalized.split()
    matches = []
    for airport in airports:
        found = _match(airport, normalized, tokens, aliases)
        if found:
            score, reason = found
            order = (-score, not airport.has_traffic, TYPE_RANK.get(airport.type, 9), airport.iata)
            matches.append((order, airport, reason))
    matches.sort(key=lambda m: m[0])
    return [(airport, reason) for _, airport, reason in matches[:limit]]
