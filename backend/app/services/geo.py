"""Offline geocoding for Swiss postal codes and distance estimates.

Data: Amtliches Ortschaftenverzeichnis, Federal Office of Topography swisstopo
(open government data). Lookups are local, so a user's location is never sent to
a third-party geocoder or AI provider.
"""

from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from pathlib import Path

_DATA = Path(__file__).resolve().parent.parent / "data" / "ch_postcodes.json"


@lru_cache
def _postcodes() -> dict[str, list]:
    return json.loads(_DATA.read_text())["postcodes"]


@lru_cache
def _by_name() -> dict[str, str]:
    idx: dict[str, str] = {}
    for plz, (_lat, _lon, names, _canton) in _postcodes().items():
        for n in names:
            idx.setdefault(n.lower(), plz)
    return idx


def lookup_postcode(plz: str | None) -> tuple[float, float, str, str] | None:
    """Returns (lat, lon, place, canton) for a Swiss 4-digit postal code."""
    if not plz:
        return None
    m = re.search(r"\b(\d{4})\b", plz)
    if not m:
        return None
    row = _postcodes().get(m.group(1))
    if not row:
        return None
    lat, lon, names, canton = row
    return lat, lon, names[0], canton


def lookup_place(text: str | None) -> tuple[float, float, str, str] | None:
    """Best-effort: a postal code anywhere in the text, else an exact place name."""
    if not text:
        return None
    hit = lookup_postcode(text)
    if hit:
        return hit
    for token in [text.strip(), *re.split(r"[,/()]", text)]:
        plz = _by_name().get(token.strip().lower())
        if plz:
            return lookup_postcode(plz)
    return None


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def road_estimate_km(straight_km: float) -> float:
    """Straight-line distance × 1.3 is a common rough road-distance estimate in
    Switzerland. Always shown as an estimate."""
    return straight_km * 1.3
