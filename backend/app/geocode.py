"""Geocoder — turn a place string into (latitude, longitude).

Given input like "Los Angeles", "90210", or "123 Main St, Denver CO", we need
coordinates so we can hit the VA Facilities API. This module tries three tiers,
in order, and returns as soon as one succeeds:

    1. SQLite cache      — repeated lookups skip the network entirely.
    2. Nominatim (OSM)   — free, no API key. Handles cities, ZIPs, addresses.
    3. Curated city dict — hard-coded lat/long for ~48 major U.S. cities.
                           Kept as an offline safety net so the demo works
                           without internet.

Nominatim's usage policy: max 1 request/second and a *distinctive* User-Agent.
See `NOMINATIM_UA`. Generic UAs (e.g. anything containing "example.com") are
rejected with HTTP 403.
"""

import json
from typing import Optional

import httpx

from . import db
from .config import get_settings

# Endpoint + UA now come from Settings so forkers/deployers can override without
# editing source. See `Settings.nominatim_url` / `nominatim_user_agent`.
# Nominatim's abuse filter rejects generic contacts (e.g. example.com) with
# HTTP 403, so `nominatim_user_agent` MUST be distinctive per deployment.

# Offline fallback — hard-coded lat/long for cities that host major VA sites.
# Substring matched (case-insensitive), so "Los Angeles" wins for the query
# "mental health near Los Angeles, CA".
CITY_COORDS: dict[str, tuple[float, float]] = {
    "los angeles": (34.0522, -118.2437),
    "long beach": (33.7701, -118.1937),
    "san diego": (32.7157, -117.1611),
    "san francisco": (37.7749, -122.4194),
    "sacramento": (38.5816, -121.4944),
    "riverside": (33.9806, -117.3755),
    "fresno": (36.7378, -119.7871),
    "phoenix": (33.4484, -112.0740),
    "tucson": (32.2226, -110.9747),
    "las vegas": (36.1699, -115.1398),
    "portland": (45.5152, -122.6784),
    "seattle": (47.6062, -122.3321),
    "denver": (39.7392, -104.9903),
    "houston": (29.7604, -95.3698),
    "dallas": (32.7767, -96.7970),
    "austin": (30.2672, -97.7431),
    "san antonio": (29.4241, -98.4936),
    "chicago": (41.8781, -87.6298),
    "detroit": (42.3314, -83.0458),
    "minneapolis": (44.9778, -93.2650),
    "st louis": (38.6270, -90.1994),
    "kansas city": (39.0997, -94.5786),
    "new orleans": (29.9511, -90.0715),
    "miami": (25.7617, -80.1918),
    "tampa": (27.9506, -82.4572),
    "orlando": (28.5383, -81.3792),
    "atlanta": (33.7490, -84.3880),
    "charlotte": (35.2271, -80.8431),
    "raleigh": (35.7796, -78.6382),
    "nashville": (36.1627, -86.7816),
    "memphis": (35.1495, -90.0490),
    "washington": (38.9072, -77.0369),
    "washington dc": (38.9072, -77.0369),
    "baltimore": (39.2904, -76.6122),
    "philadelphia": (39.9526, -75.1652),
    "pittsburgh": (40.4406, -79.9959),
    "new york": (40.7128, -74.0060),
    "boston": (42.3601, -71.0589),
    "buffalo": (42.8864, -78.8784),
    "cleveland": (41.4993, -81.6944),
    "columbus": (39.9612, -82.9988),
    "cincinnati": (39.1031, -84.5120),
    "indianapolis": (39.7684, -86.1581),
    "milwaukee": (43.0389, -87.9065),
    "salt lake city": (40.7608, -111.8910),
    "albuquerque": (35.0844, -106.6504),
    "oklahoma city": (35.4676, -97.5164),
    "honolulu": (21.3099, -157.8581),
    "anchorage": (61.2181, -149.9003),
}


def _dict_lookup(text: str) -> Optional[tuple[float, float]]:
    """Look for any known city name inside `text`.

    Case-insensitive substring match. Longer names win first (so "long beach"
    beats "los angeles" for a query mentioning both).

    Args:
        text: Free-form query string.

    Returns:
        (lat, long) tuple if a city name appears in `text`, else None.
    """
    t = (text or "").lower()
    for name in sorted(CITY_COORDS, key=len, reverse=True):
        if name in t:
            return CITY_COORDS[name]
    return None


async def _nominatim_lookup(text: str) -> Optional[tuple[float, float]]:
    """Ask Nominatim (OpenStreetMap) to resolve `text` to coordinates.

    Never raises — any failure (network, HTTP error, bad JSON, empty result)
    returns None so the caller can try the next tier. Every failure branch
    logs a one-line hint so we can diagnose 403s / rate limits later.

    Args:
        text: A place string. Anything trimmable to empty short-circuits.

    Returns:
        (lat, long) tuple on success, otherwise None.
    """
    q = (text or "").strip()
    if not q:
        return None
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(
                settings.nominatim_url,
                params={
                    "q": q,
                    "format": "json",
                    "limit": 1,
                    "countrycodes": "us",
                },
                headers={
                    "User-Agent": settings.nominatim_user_agent,
                    "Accept": "application/json",
                },
            )
        if r.status_code != 200:
            print(f"[geocode] Nominatim HTTP {r.status_code} for {q!r}: {r.text[:200]!r}")
            return None
        try:
            results = r.json()
        except Exception as e:
            print(f"[geocode] Nominatim JSON parse failed for {q!r}: {e}; body={r.text[:200]!r}")
            return None
        # Nominatim should always return a JSON list. Anything else means
        # the response is unusable — fall through to the dict tier.
        if not isinstance(results, list):
            print(f"[geocode] Nominatim returned non-list for {q!r}: {type(results).__name__}")
            return None
        if not results:
            print(f"[geocode] Nominatim empty result list for {q!r}")
            return None
        top = results[0]
        lat = top.get("lat")
        lon = top.get("lon")
        if lat is None or lon is None:
            print(f"[geocode] Nominatim top result missing lat/lon for {q!r}: {top!r}")
            return None
        return (float(lat), float(lon))
    except Exception as e:
        print(f"[geocode] Nominatim exception for {q!r}: {type(e).__name__}: {e}")
        return None


def _cache_key(text: str) -> str:
    """Build the cache key for a geocode lookup.

    We stash a small JSON object so different query types (geocode, VA
    search, VA detail) can share the same table without collisions.

    Args:
        text: The place string being geocoded.

    Returns:
        A stable, canonical string suitable as a SQLite key.
    """
    return json.dumps({"kind": "geocode", "q": (text or "").strip().lower()}, sort_keys=True)


async def geocode(text: str) -> Optional[tuple[float, float]]:
    """Resolve a place string to (lat, long).

    Tries cache → Nominatim → curated dict, in that order. On success, the
    result is written back to the cache so the next call is free.

    Args:
        text: Anything a user might type — city, ZIP, or full address.
              Empty or None returns None immediately.

    Returns:
        (lat, long) tuple, or None if every tier failed.
    """
    if not text:
        return None
    key = _cache_key(text)
    cached = db.get_cached(key)
    if cached:
        return (cached[0], cached[1])

    coords = await _nominatim_lookup(text)
    if coords is None:
        coords = _dict_lookup(text)
        if coords is not None:
            print(f"[geocode] Nominatim miss for {text!r}; using curated dict fallback")
    if coords:
        db.set_cached(key, [coords[0], coords[1]])
    return coords


def geocode_city(text: str) -> Optional[tuple[float, float]]:
    """Synchronous, dict-only geocode. Kept for legacy callers.

    Args:
        text: A place string.

    Returns:
        (lat, long) tuple from the curated dict, or None if no match.
    """
    return _dict_lookup(text)
