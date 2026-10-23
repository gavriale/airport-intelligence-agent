"""Which runways count for per-runway metrics.

A commercial-capable runway is open, paved and at least 5,000 ft long. Short or unpaved runways
(general aviation strips, seaplane lanes) do not carry airline traffic, so counting them would
make an airport look less busy per runway than it is. The snapshot already contains only open
runways, so the rule here checks surface and length.
"""

MIN_COMMERCIAL_RUNWAY_FT = 5_000
PAVED_SURFACE_PREFIXES = ("ASP", "CON", "PEM", "PER", "BIT", "TAR", "PAV")  # asphalt, concrete...
RULE_TEXT = f"open, paved, at least {MIN_COMMERCIAL_RUNWAY_FT:,} ft long"


def is_paved(surface: str | None) -> bool:
    """OurAirports surface codes vary (ASP, ASPH-G, CONCRETE, PEM ...); match on the start."""
    return bool(surface) and surface.upper().startswith(PAVED_SURFACE_PREFIXES)


def is_commercial_capable(length_ft: int | None, surface: str | None) -> bool:
    return length_ft is not None and length_ft >= MIN_COMMERCIAL_RUNWAY_FT and is_paved(surface)
