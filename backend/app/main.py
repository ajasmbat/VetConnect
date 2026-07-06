"""VetConnect FastAPI app — the HTTP surface.

What lives here
---------------
Just the endpoint wiring. Business logic (VA API calls, geocoding, AI parsing)
lives in dedicated modules; this file's job is to receive requests, delegate,
cache, and return responses.

Endpoints
---------
  GET  /api/health                    — liveness probe
  GET  /api/debug/geocode?q=…         — tier-by-tier geocode diagnostic
  GET  /api/facilities/search         — VA search by coordinates
  GET  /api/facilities/{id}           — one facility by id
  POST /api/assistant                 — the "ask a question" endpoint

Privacy note
------------
This service consumes only the public VA Facilities API. It does not fetch,
store, or transmit any Protected Health Information (PHI). Secrets
(`VA_API_KEY`, `OPENAI_API_KEY`) are read from environment variables and are
never committed to the repo.
"""

import json
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from . import assistant, db
from .config import get_settings
from .geocode import _dict_lookup, _nominatim_lookup, geocode
from .models import (
    AssistantRequest,
    AssistantResponse,
    ErrorResponse,
    Facility,
    SearchResponse,
)
from .rate_limit import assistant_rate_limit
from .va_client import VAAPIError, get_facility, search_facilities


@asynccontextmanager
async def lifespan(_: FastAPI):
    """FastAPI startup/shutdown hook.

    Runs `db.init_db()` once at process start so the SQLite tables exist
    before any request is served. The `yield` marks the app as "running";
    nothing needs to happen at shutdown.
    """
    db.init_db()
    yield


app = FastAPI(
    title="VetConnect API",
    description=(
        "Helps U.S. veterans find nearby VA facilities and services. "
        "Uses only the public VA Facilities API — no PHI is processed."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# Only the configured frontend origin can call this API from the browser.
# Credentials are off because we don't use cookies.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().cors_origin],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _cache_key(**parts) -> str:
    """Build a stable cache key from arbitrary keyword arguments.

    We serialize with sorted keys so `_cache_key(a=1, b=2)` and
    `_cache_key(b=2, a=1)` produce the same string.

    Args:
        **parts: Any JSON-serializable kwargs describing the request.

    Returns:
        A canonical JSON string suitable as a SQLite cache key.
    """
    return json.dumps(parts, sort_keys=True, default=str)


@app.get("/api/health", summary="Liveness probe")
async def health() -> dict[str, str]:
    """Return a static OK response.

    Used by load balancers / uptime checks. No dependencies are touched, so
    a 200 here means "the process is up" — not "downstream APIs work."

    Returns:
        `{"status": "ok"}`.
    """
    return {"status": "ok"}


@app.get(
    "/api/debug/geocode",
    summary="Debug: show what each geocoder tier returns for a query",
)
async def debug_geocode(q: str) -> dict[str, object]:
    """Diagnostic endpoint — reports every geocode tier separately.

    Useful for spotting when Nominatim is blocked or rate-limited: you'll
    see `nominatim: null` but `dict: [lat, long]`. Safe to leave enabled
    in the demo — no auth is required and no PHI is involved.

    Args:
        q: The place string to test.

    Returns:
        `{query, nominatim, dict, final}` — where each tier is either a
        `[lat, long]` pair or null.
    """
    nominatim = await _nominatim_lookup(q)
    dict_hit = _dict_lookup(q)
    final = await geocode(q)
    return {
        "query": q,
        "nominatim": nominatim,
        "dict": dict_hit,
        "final": final,
    }


@app.get(
    "/api/facilities/search",
    response_model=SearchResponse,
    responses={502: {"model": ErrorResponse}},
    summary="Search VA facilities by location, type, and service",
)
async def search(
    lat: float = Query(..., ge=-90, le=90),
    long: float = Query(..., ge=-180, le=180),
    radius: Optional[float] = Query(50, gt=0, le=500, description="Miles"),
    type: Optional[str] = Query(
        None, description="health | benefits | cemetery | vet_center"
    ),
    service: Optional[str] = Query(None, description="e.g. MentalHealthCare"),
) -> SearchResponse:
    """Search VA facilities within `radius` miles of a coordinate.

    Results are cached for 15 minutes keyed by the full query (see
    `_cache_key`). Service filtering happens *after* the VA call because
    VA's service enum has shifted across API versions.

    Args:
        lat:     Latitude, `[-90, 90]`.
        long:    Longitude, `[-180, 180]`.
        radius:  Search radius in miles, `(0, 500]`. Default 50.
        type:    Optional facility type filter.
        service: Optional canonical service name (e.g. `MentalHealthCare`).

    Raises:
        HTTPException(502): if the VA API returns a non-2xx status.

    Returns:
        `SearchResponse` with `count` and `facilities`.
    """
    key = _cache_key(kind="search", lat=lat, long=long, radius=radius, type=type, service=service)
    cached = db.get_cached(key)
    if cached:
        return SearchResponse(**cached)

    try:
        results = await search_facilities(lat, long, radius, type)
    except VAAPIError as e:
        raise HTTPException(status_code=502, detail=e.message)

    if service:
        results = assistant.filter_by_service(results, service)

    resp = SearchResponse(count=len(results), facilities=results)
    db.set_cached(key, resp.model_dump())
    return resp


@app.get(
    "/api/facilities/{facility_id}",
    response_model=Facility,
    responses={404: {"model": ErrorResponse}, 502: {"model": ErrorResponse}},
    summary="Get one facility by VA facility id",
)
async def detail(facility_id: str) -> Facility:
    """Fetch a single facility by its VA id.

    Args:
        facility_id: The `id` field from a VA search result (e.g. `vha_691`).

    Raises:
        HTTPException(404): if VA says the id doesn't exist.
        HTTPException(502): for any other VA error.

    Returns:
        `Facility` — the full record for that id.
    """
    key = _cache_key(kind="detail", id=facility_id)
    cached = db.get_cached(key)
    if cached:
        return Facility(**cached)
    try:
        f = await get_facility(facility_id)
    except VAAPIError as e:
        raise HTTPException(status_code=e.status if e.status in (404,) else 502, detail=e.message)
    db.set_cached(key, f.model_dump())
    return f


@app.post(
    "/api/assistant",
    response_model=AssistantResponse,
    responses={
        429: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
    },
    dependencies=[Depends(assistant_rate_limit)],
    summary="Answer a plain-English question with matching facilities",
)
async def assistant_endpoint(req: AssistantRequest) -> AssistantResponse:
    """The "ask a question" endpoint — the flagship user-facing route.

    Pipeline:
        1. Parse question → (service, location_hint)  via `assistant.llm_parse`.
        2. Resolve coordinates:
             explicit req.lat/long > geocode(location_hint) > geocode(question).
        3. Log the question (for prompt iteration; contains no PHI).
        4. If no coordinates were found, return a helpful "try adding a city"
           message and stop.
        5. Search the VA API around those coordinates.
        6. If a service was detected, filter results by it.
        7. Write a friendly answer via `assistant.write_answer`.

    Args:
        req: `AssistantRequest` with `question` and optional `lat`/`long`.

    Raises:
        HTTPException(502): if the VA search step fails.

    Returns:
        `AssistantResponse` — answer text plus the parsed intent and
        matching facilities.
    """
    service, location_hint = await assistant.llm_parse(req.question)

    # Resolve coordinates. We prefer explicit lat/long from the browser
    # (fastest, no network hop), fall back to geocoding the parsed hint,
    # and finally geocode the full question as a last resort.
    lat, long_ = req.lat, req.long
    if lat is None or long_ is None:
        coords = None
        if location_hint:
            coords = await geocode(location_hint)
        if not coords:
            coords = await geocode(req.question)
        if coords:
            lat, long_ = coords

    db.log_question(req.question, service, location_hint)

    if lat is None or long_ is None:
        return AssistantResponse(
            answer=(
                "I couldn't figure out which city you meant. Try adding one — "
                "e.g. 'mental health near Los Angeles'."
            ),
            parsed_service=service,
            parsed_location=location_hint,
            facilities=[],
        )

    try:
        results = await search_facilities(lat, long_, radius=50)
    except VAAPIError as e:
        raise HTTPException(status_code=502, detail=e.message)

    if service:
        results = assistant.filter_by_service(results, service)

    answer = await assistant.write_answer(req.question, service, location_hint, results)
    return AssistantResponse(
        answer=answer,
        parsed_service=service,
        parsed_location=location_hint,
        facilities=results,
    )
