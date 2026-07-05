"""Minimal offline geocoder for common U.S. cities.

Keeps the demo self-contained: no external geocoding key required to try the
example queries. For real use you'd swap this out for a proper geocoder.
"""

from typing import Optional

# Curated set biased toward cities with major VA facilities.
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


def geocode_city(text: str) -> Optional[tuple[float, float]]:
    """Return (lat, long) for a substring matching a known city, else None."""
    t = (text or "").lower()
    # Prefer longer matches first (e.g. "san diego" over "san").
    for name in sorted(CITY_COORDS, key=len, reverse=True):
        if name in t:
            return CITY_COORDS[name]
    return None
