"""The commercial-runway rule: open (already filtered in the snapshot), paved, 5,000 ft or more."""

import pytest

from domain.runways import is_commercial_capable, is_paved


@pytest.mark.parametrize(
    "surface", ["ASP", "ASPH-G", "ASPHALT", "CON", "CONC-F", "CONCRETE", "PEM", "asp"]
)
def test_paved_surface_codes_are_recognised(surface):
    assert is_paved(surface)


@pytest.mark.parametrize(
    "surface", ["GRVL", "GRAVEL-G", "GRS", "TURF", "DIRT-G", "WATER", "", None]
)
def test_unpaved_or_missing_surfaces_are_not_paved(surface):
    assert not is_paved(surface)


@pytest.mark.parametrize(
    "length_ft,surface,expected",
    [
        (5000, "ASP", True),  # the minimum is inclusive
        (4999, "ASP", False),
        (12000, "CON", True),
        (7000, "GRVL", False),  # long but unpaved
        (None, "ASP", False),  # unknown length
        (8000, None, False),  # unknown surface
    ],
)
def test_commercial_capable_needs_paved_and_long_enough(length_ft, surface, expected):
    assert is_commercial_capable(length_ft, surface) is expected
